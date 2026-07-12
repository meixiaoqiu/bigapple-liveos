"""Simulation run disposition services."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from django.conf import settings
from django.db import connections
from django.utils import timezone

from core.models import Event, SimulationRun, SimulationRunDisposition, SimulationSnapshot
from simulation.run_state import create_simulation_turn_and_event
from worlds.models import WorldRegistry


CONTROL_DATABASE_ALIAS = "default"
FINISHED_RUN_STATUSES = (
    SimulationRun.Status.FAILED,
    SimulationRun.Status.COMPLETED,
    SimulationRun.Status.PAUSED,
    SimulationRun.Status.ABORTED,
)


class UnresolvedSimulationRunError(RuntimeError):
    """Raised when a finished simulation run has not been archived or discarded."""


@dataclass(frozen=True)
class UnresolvedSimulationRun:
    run_id: str
    status: str
    started_at: object
    ended_at: object
    failure_summary: str


def source_alias_for_world(world: WorldRegistry) -> str:
    if not getattr(settings, "WORLD_DATABASE_ROUTING_ENABLED", True):
        return CONTROL_DATABASE_ALIAS
    return world.database_alias


def ensure_no_unresolved_finished_runs(*, world: WorldRegistry) -> None:
    unresolved = unresolved_finished_runs(world=world)
    if unresolved:
        run = unresolved[0]
        raise UnresolvedSimulationRunError(
            "存在已结束但未处置的仿真运行，必须先归档或人工放弃后才能启动下一轮："
            f"world={world.world_id}, run={run.run_id}, status={run.status}"
        )


def unresolved_finished_runs(*, world: WorldRegistry) -> list[UnresolvedSimulationRun]:
    source_alias = source_alias_for_world(world)
    disposed_run_ids = set(
        SimulationRunDisposition.objects.using(CONTROL_DATABASE_ALIAS)
        .filter(source_world_id=world.world_id)
        .values_list("source_run_id", flat=True)
    )
    archived_run_ids = set(
        SimulationSnapshot.objects.using(CONTROL_DATABASE_ALIAS)
        .filter(source_world_id=world.world_id)
        .values_list("source_run_id", flat=True)
    )
    resolved_run_ids = disposed_run_ids | archived_run_ids
    runs = (
        SimulationRun.objects.using(source_alias)
        .filter(status__in=FINISHED_RUN_STATUSES)
        .order_by("started_at", "run_id")
    )
    return [
        UnresolvedSimulationRun(
            run_id=run.run_id,
            status=run.status,
            started_at=run.started_at,
            ended_at=run.ended_at,
            failure_summary=run.failure_summary,
        )
        for run in runs
        if run.run_id not in resolved_run_ids and not is_continuable_zero_start_observation_run(run)
    ]


def is_continuable_zero_start_observation_run(run: SimulationRun) -> bool:
    """Return True for old zero-start observation-window failures that can continue.

    A startup gate miss is business evidence, not a terminal engine failure.
    System interaction failures remain terminal because they mean the real form
    or persistence path broke and must be reviewed before another run proceeds.
    """

    metadata = run.metadata if isinstance(run.metadata, dict) else {}
    return (
        run.status == SimulationRun.Status.FAILED
        and metadata.get("scenario") == "zero_start"
        and not metadata.get("startup_gate_satisfied")
        and not metadata.get("system_interaction_failed")
    )


def abort_simulation_run(
    *,
    run: SimulationRun,
    reason: str,
    decided_by: str = "",
) -> SimulationRun:
    """Abort a still-active simulation run and keep the reason on the run timeline."""

    reason = reason.strip()
    if not reason:
        raise ValueError("reason is required when aborting a simulation run.")
    if run.status not in {SimulationRun.Status.RUNNING} and not is_continuable_zero_start_observation_run(run):
        raise ValueError(f"Only a running or continuable zero-start run can be aborted: {run.run_id} ({run.status})")

    now = timezone.now()
    metadata = dict(run.metadata or {})
    metadata["aborted"] = {
        "aborted_by": decided_by,
        "aborted_at": now.isoformat(),
        "reason": reason,
        "previous_status": run.status,
    }
    run.status = SimulationRun.Status.ABORTED
    run.ended_at = now
    run.failure_summary = f"人工中止：{reason}"
    run.metadata = metadata
    run.save(update_fields=["status", "ended_at", "failure_summary", "metadata"])
    create_simulation_turn_and_event(
        run=run,
        title="人工中止本轮仿真",
        summary=f"本轮仿真由管理员人工中止：{reason}",
        simulation_day=run.current_day,
        severity=Event.Severity.WARNING,
        event_type=Event.EventType.SIMULATION_DAY,
        payload={
            "scenario": metadata.get("scenario") or "",
            "aborted_by": decided_by,
            "reason": reason,
        },
    )
    return run


def record_archived_disposition(
    *,
    world: WorldRegistry,
    run: SimulationRun,
    snapshot: SimulationSnapshot,
    reason: str = "",
    decided_by: str = "",
) -> SimulationRunDisposition:
    return _record_disposition(
        world=world,
        run=run,
        disposition=SimulationRunDisposition.Disposition.ARCHIVED,
        reason=reason or "仿真运行已归档为永久快照。",
        decided_by=decided_by,
        snapshot=snapshot,
        simulation_round=snapshot.simulation_round,
    )


def record_discarded_disposition(
    *,
    world: WorldRegistry,
    run: SimulationRun,
    reason: str,
    decided_by: str = "",
) -> SimulationRunDisposition:
    if not reason.strip():
        raise ValueError("reason is required when discarding a simulation run.")
    if SimulationSnapshot.objects.using(CONTROL_DATABASE_ALIAS).filter(
        source_world_id=world.world_id,
        source_run_id=run.run_id,
    ).exists():
        raise ValueError("Archived simulation run cannot be discarded.")
    return _record_disposition(
        world=world,
        run=run,
        disposition=SimulationRunDisposition.Disposition.DISCARDED,
        reason=reason,
        decided_by=decided_by,
        snapshot=None,
        simulation_round=None,
    )


def next_simulation_round(*, world_id: str) -> int:
    disposition_rounds = SimulationRunDisposition.objects.using(CONTROL_DATABASE_ALIAS).filter(source_world_id=world_id)
    snapshot_rounds = SimulationSnapshot.objects.using(CONTROL_DATABASE_ALIAS).filter(source_world_id=world_id)
    max_round = 0
    for value in disposition_rounds.values_list("simulation_round", flat=True):
        max_round = max(max_round, int(value or 0))
    for value in snapshot_rounds.values_list("simulation_round", flat=True):
        max_round = max(max_round, int(value or 0))
    return max_round + 1


def scenario_from_run(run: SimulationRun) -> str:
    metadata = run.metadata if isinstance(run.metadata, dict) else {}
    return str(metadata.get("scenario") or "")


def _record_disposition(
    *,
    world: WorldRegistry,
    run: SimulationRun,
    disposition: str,
    reason: str,
    decided_by: str,
    snapshot: SimulationSnapshot | None,
    simulation_round: int | None,
) -> SimulationRunDisposition:
    existing = SimulationRunDisposition.objects.using(CONTROL_DATABASE_ALIAS).filter(
        source_world_id=world.world_id,
        source_run_id=run.run_id,
    ).first()
    if existing is not None:
        return existing

    source_alias = source_alias_for_world(world)
    return SimulationRunDisposition.objects.using(CONTROL_DATABASE_ALIAS).create(
        disposition_id=_generate_disposition_id(),
        source_world_id=world.world_id,
        source_world_type=world.world_type,
        source_database_alias=source_alias,
        source_database_name=world.database_name or connections[source_alias].settings_dict.get("NAME", ""),
        source_run_id=run.run_id,
        run_status=run.status,
        run_started_at=run.started_at,
        run_ended_at=run.ended_at,
        simulation_round=simulation_round or next_simulation_round(world_id=world.world_id),
        scenario=scenario_from_run(run),
        disposition=disposition,
        reason=reason,
        decided_by=decided_by,
        decided_at=timezone.now(),
        snapshot=snapshot,
        metadata={},
    )


def _generate_disposition_id() -> str:
    for _ in range(10):
        disposition_id = f"sim-disposition-{uuid4().hex[:12]}"
        if not SimulationRunDisposition.objects.using(CONTROL_DATABASE_ALIAS).filter(disposition_id=disposition_id).exists():
            return disposition_id
    raise RuntimeError("Unable to allocate SimulationRunDisposition id.")
