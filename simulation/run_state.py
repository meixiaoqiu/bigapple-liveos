"""Simulation run, turn, and per-node state writes."""

from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

from core.db import atomic_for_model
from core.exceptions import DomainError
from core.models import Event, PlanNode, PlanNodeRunState, PlanRevision, SimulationRun, SimulationTurn

from .ids import (
    generate_plan_node_run_state_id,
    generate_simulation_event_id,
    generate_simulation_run_id,
    generate_simulation_turn_id,
)
from .world_snapshot import (
    active_plan_revision,
    latest_fatigue_score,
    simulation_available_budget,
    simulation_available_people,
    simulation_available_skills,
    simulation_start_day,
)


@atomic_for_model(SimulationRun)
def create_simulation_run(
    *,
    plan_revision: PlanRevision | None = None,
    max_turns: int = 30,
) -> SimulationRun:
    """Create one isolated automatic simulation run for the current plan revision."""

    revision = plan_revision or active_plan_revision()
    if max_turns <= 0:
        raise DomainError("最大推进步数必须大于 0。")
    now = timezone.now()
    run = SimulationRun.objects.create(
        run_id=generate_simulation_run_id(),
        plan_revision=revision,
        status=SimulationRun.Status.DRAFT,
        current_day=simulation_start_day(),
        max_turns=max_turns,
        started_at=now,
        ended_at=None,
        failure_summary="",
        metadata={
            "source": "observer_auto_run",
            "initial_budget": str(simulation_available_budget()),
            "remaining_budget": str(simulation_available_budget()),
            "spent_budget": "0",
            "available_people": simulation_available_people(),
            "available_skills": sorted(simulation_available_skills()),
            "average_fatigue": str(latest_fatigue_score()),
        },
    )
    ensure_plan_node_run_states(run)
    return run


def ensure_plan_node_run_states(run: SimulationRun) -> None:
    """Create per-node state rows for a run while preserving existing progress."""

    nodes = run.plan_revision.nodes.order_by("sequence", "node_id")
    for node in nodes:
        if node.status == PlanNode.Status.COMPLETED:
            initial_status = PlanNodeRunState.Status.COMPLETED
            progress = Decimal("100.00")
            completed_day = node.planned_end_day or run.current_day
        elif node.status == PlanNode.Status.CANCELLED:
            initial_status = PlanNodeRunState.Status.SKIPPED
            progress = Decimal("0.00")
            completed_day = None
        else:
            initial_status = PlanNodeRunState.Status.PENDING
            progress = Decimal("0.00")
            completed_day = None
        PlanNodeRunState.objects.get_or_create(
            run=run,
            plan_node=node,
            defaults={
                "state_id": generate_plan_node_run_state_id(),
                "status": initial_status,
                "started_day": node.planned_start_day if initial_status == PlanNodeRunState.Status.COMPLETED else None,
                "completed_day": completed_day,
                "progress_percent": progress,
                "actual_cost": node.estimated_cost_expected if initial_status == PlanNodeRunState.Status.COMPLETED else 0,
                "actual_person_days": node.required_person_days if initial_status == PlanNodeRunState.Status.COMPLETED else 0,
                "blocker_reason": "",
                "metadata": {"source_plan_status": node.status},
            },
        )


def is_executable_plan_node(node: PlanNode) -> bool:
    """Only leaf work nodes and gates consume run budget in the first automatic model."""

    return node.is_required and node.node_type != PlanNode.NodeType.STAGE


def next_turn_number(run: SimulationRun) -> int:
    latest = run.turns.order_by("-turn_number").first()
    return 1 if latest is None else latest.turn_number + 1


def create_simulation_turn_and_event(
    *,
    run: SimulationRun,
    title: str,
    summary: str,
    simulation_day: int,
    severity: str,
    event_type: str = Event.EventType.SIMULATION_DAY,
    payload: dict | None = None,
) -> tuple[SimulationTurn, Event]:
    """Append both the structured turn row and the public observer event."""

    now = timezone.now()
    payload = payload or {}
    turn = SimulationTurn.objects.create(
        turn_id=generate_simulation_turn_id(),
        run=run,
        turn_number=next_turn_number(run),
        simulation_day=simulation_day,
        summary=summary,
        occurred_at=now,
        metadata={
            "title": title,
            "severity": severity,
            "event_type": event_type,
            **payload,
        },
    )
    event = Event.objects.create(
        event_id=generate_simulation_event_id(),
        event_type=event_type,
        simulation_day=simulation_day,
        simulation_run=run,
        severity=severity,
        title=title,
        summary=summary,
        involved_member_ids=[],
        related_task=None,
        related_dispute_id="",
        occurred_at=now,
        generated_by=Event.GeneratedBy.SIMULATION_ENGINE,
        visibility=Event.Visibility.PUBLIC,
        payload={
            "source": "observer_auto_run",
            "run_id": run.run_id,
            "turn_id": turn.turn_id,
            **payload,
        },
    )
    return turn, event
