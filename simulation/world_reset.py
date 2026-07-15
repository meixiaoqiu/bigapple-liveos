"""Service module for resetting a simulation world to zero-start baseline.

This module is intentionally separated from views so the dangerous flush /
re-seed logic can be tested independently and audited through
WorldMaintenanceLog records in the control database.
"""

from __future__ import annotations

from collections import OrderedDict

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError

from core.exceptions import DomainError
from core.models import (
    Dispute,
    Event,
    LedgerEntry,
    Member,
    MemberApplication,
    PartnerApplication,
    PlanNode,
    PlanRevision,
    Proposal,
    ProposalExecution,
    ProposalVote,
    ProjectPlan,
    Resource,
    ResourceTransaction,
    SimulationRun,
    SimulationTurn,
    SystemEvent,
    Task,
)
from simulation.disposition import (
    CONTROL_DATABASE_ALIAS,
    UnresolvedSimulationRunError,
    ensure_no_unresolved_finished_runs,
    source_alias_for_world,
)
from worlds.models import WorldMaintenanceLog, WorldRegistry

# OrderedDict keeps table names in a stable, human-readable order on the UI.
COUNT_TABLES: OrderedDict[str, type] = OrderedDict([
    ("Member", Member),
    ("auth.User", None),  # handled specially
    ("MemberApplication", MemberApplication),
    ("PartnerApplication", PartnerApplication),
    ("Proposal", Proposal),
    ("ProposalVote", ProposalVote),
    ("ProposalExecution", ProposalExecution),
    ("SimulationRun", SimulationRun),
    ("SimulationTurn", SimulationTurn),
    ("Event", Event),
    ("SystemEvent", SystemEvent),
    ("ProjectPlan", ProjectPlan),
    ("PlanRevision", PlanRevision),
    ("PlanNode", PlanNode),
    ("Task", Task),
    ("Resource", Resource),
    ("ResourceTransaction", ResourceTransaction),
    ("LedgerEntry", LedgerEntry),
    ("Dispute", Dispute),
])


def count_world_rows(world: WorldRegistry) -> dict[str, int]:
    """Return per-table record counts for the target world database."""
    source_alias = source_alias_for_world(world)
    counts: dict[str, int] = OrderedDict()
    for label, model in COUNT_TABLES.items():
        if model is None:
            # auth.User is not imported from core.models; count via auth
            from django.contrib.auth import get_user_model
            User = get_user_model()
            counts[label] = User.objects.using(source_alias).count()
        else:
            counts[label] = model.objects.using(source_alias).count()
    return counts


def reset_simulation_world_to_zero_start(
    world: WorldRegistry,
    *,
    actor: str,
    force: bool = False,
) -> dict:
    """Flush the target simulation world and re-seed to the zero-start baseline.

    This function:
    1. Validates the world is an active simulation world (refuses realworld).
    2. Counts records before flush for audit / UI display.
    3. Checks for unresolved or running runs (blocks unless force=True).
    4. Flushes the target world database without touching the control DB.
    5. Calls seed_world --template zero_start on the target world.
    6. Counts records after re-seed.
    7. Writes a WorldMaintenanceLog in the control database.
    8. Returns a result dict with counts and metadata.

    Note: This function does NOT run run_zero_start_simulation. The world
    after reset will have only the zero-start baseline: one founder member,
    one ProjectPlan, and one published PlanRevision with no SimulationRun,
    SimulationTurn, or application/proposal history.

    Raises:
        DomainError: if validation fails (wrong world type, status, etc.)
        CommandError: if seed_world fails.
    """
    # ---- Validate world ----
    if world is None:
        raise DomainError("目标仿真世界不存在。")
    if world.world_type != WorldRegistry.WorldType.SIMULATION:
        raise DomainError(
            f"只允许对仿真世界执行重置操作，当前世界类型为 {world.get_world_type_display()}。"
        )
    if world.status != WorldRegistry.Status.ACTIVE:
        raise DomainError(
            f"只允许对启用状态的仿真世界重置，当前状态为 {world.get_status_display()}。"
        )

    # ---- Validate no sensitive alias ----
    database_alias = source_alias_for_world(world)
    if getattr(settings, "WORLD_DATABASE_ROUTING_ENABLED", True) and database_alias == CONTROL_DATABASE_ALIAS:
        raise DomainError(
            f"不能通过 control/default 数据库别名执行清空操作：{database_alias}。"
        )

    # ---- Count before ----
    counts_before = count_world_rows(world)

    # ---- Check for unresolved / running runs ----
    try:
        if not force:
            ensure_no_unresolved_finished_runs(world=world)
    except UnresolvedSimulationRunError as exc:
        raise DomainError(
            str(exc) + " 如果需要强制重置，请勾选 force_reset。"
        ) from exc

    if not force:
        source_alias = source_alias_for_world(world)
        running_run = (
            SimulationRun.objects.using(source_alias)
            .filter(status=SimulationRun.Status.RUNNING)
            .first()
        )
        if running_run is not None:
            raise DomainError(
                f"仿真世界 {world.world_id} 仍有运行中的仿真 {running_run.run_id}。"
                " 如需强制重置，请勾选 force_reset。"
            )

    # ---- Flush target world database ----
    # Save world registry fields before flush so we can restore it.
    world_kwargs = {
        "world_id": world.world_id,
        "name": world.name,
        "world_type": world.world_type,
        "database_alias": world.database_alias,
        "database_name": world.database_name,
        "status": world.status,
    }
    try:
        call_command("flush", database=database_alias, interactive=False, verbosity=0)
    except CommandError as exc:
        _record_maintenance_log(
            world=world,
            actor=actor,
            force=force,
            counts_before=counts_before,
            counts_after={},
            status=WorldMaintenanceLog.StatusChoices.FAILED,
            message=f"flush/清空目标世界数据库失败：{exc}",
        )
        raise CommandError(f"清空目标世界数据库失败：{exc}") from exc

    # Restore the WorldRegistry row in the control database so seed_world can find it.
    world, _created = WorldRegistry.objects.using(CONTROL_DATABASE_ALIAS).update_or_create(
        world_id=world_kwargs["world_id"],
        defaults=world_kwargs,
    )

    # ---- Re-seed zero_start baseline ----
    try:
        call_command("seed_world", world.world_id, "--template", "zero_start")
    except CommandError as exc:
        _record_maintenance_log(
            world=world,
            actor=actor,
            force=force,
            counts_before=counts_before,
            counts_after={},
            status=WorldMaintenanceLog.StatusChoices.FAILED,
            message=f"seed_world 失败：{exc}",
        )
        raise

    # ---- Count after ----
    counts_after = count_world_rows(world)

    # ---- Write audit log ----
    _record_maintenance_log(
        world=world,
        actor=actor,
        force=force,
        counts_before=counts_before,
        counts_after=counts_after,
        status=WorldMaintenanceLog.StatusChoices.SUCCEEDED,
        message="已成功重置到 zero_start 基线。",
    )

    return {
        "world_id": world.world_id,
        "database_alias": database_alias,
        "seed_template": "zero_start",
        "actor": actor,
        "counts_before": counts_before,
        "counts_after": counts_after,
    }


def _record_maintenance_log(
    *,
    world: WorldRegistry,
    actor: str,
    force: bool,
    counts_before: dict[str, int],
    counts_after: dict[str, int],
    status: str,
    message: str,
) -> WorldMaintenanceLog:
    """Write a maintenance audit record in the control database."""
    return WorldMaintenanceLog.objects.using(CONTROL_DATABASE_ALIAS).create(
        world=world,
        action=WorldMaintenanceLog.Action.RESET_ZERO_START,
        actor_username=actor,
        status=status,
        force=force,
        counts_before_json=counts_before,
        counts_after_json=counts_after,
        message=message,
    )
