"""Simulation node and run progress transitions."""

from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

from core.models import Event, PlanNode, PlanNodeRunState, SimulationRun

from .run_state import create_simulation_turn_and_event
from .world_snapshot import decimal_from_metadata


def mark_parent_stages_completed_if_ready(*, run: SimulationRun, node: PlanNode, completed_day: int) -> None:
    parent = node.parent
    while parent is not None:
        child_states = PlanNodeRunState.objects.filter(run=run, plan_node__parent=parent, plan_node__is_required=True)
        if child_states.exists() and not child_states.exclude(
            status__in=[PlanNodeRunState.Status.COMPLETED, PlanNodeRunState.Status.SKIPPED]
        ).exists():
            parent_state = PlanNodeRunState.objects.filter(run=run, plan_node=parent).first()
            if parent_state and parent_state.status != PlanNodeRunState.Status.COMPLETED:
                parent_state.status = PlanNodeRunState.Status.COMPLETED
                parent_state.progress_percent = Decimal("100.00")
                parent_state.completed_day = completed_day
                parent_state.blocker_reason = ""
                parent_state.metadata = {**parent_state.metadata, "auto_completed_by_children": True}
                parent_state.save(
                    update_fields=["status", "progress_percent", "completed_day", "blocker_reason", "metadata"]
                )
            parent = parent.parent
        else:
            break


def next_executable_state(run: SimulationRun) -> PlanNodeRunState | None:
    return (
        PlanNodeRunState.objects.select_related("plan_node", "plan_node__parent")
        .filter(run=run, plan_node__is_required=True)
        .exclude(plan_node__node_type=PlanNode.NodeType.STAGE)
        .exclude(status__in=[PlanNodeRunState.Status.COMPLETED, PlanNodeRunState.Status.SKIPPED])
        .order_by("plan_node__sequence", "plan_node__node_id")
        .first()
    )


def complete_simulation_node(*, run: SimulationRun, state: PlanNodeRunState) -> None:
    node = state.plan_node
    duration = max(1, node.planned_duration_days)
    start_day = run.current_day
    completed_day = start_day + duration - 1
    remaining_budget = decimal_from_metadata(run.metadata.get("remaining_budget"), default="0") - node.estimated_cost_expected
    spent_budget = decimal_from_metadata(run.metadata.get("spent_budget"), default="0") + node.estimated_cost_expected

    state.status = PlanNodeRunState.Status.COMPLETED
    state.started_day = start_day
    state.completed_day = completed_day
    state.progress_percent = Decimal("100.00")
    state.actual_cost = node.estimated_cost_expected
    state.actual_person_days = node.required_person_days
    state.blocker_reason = ""
    state.metadata = {
        **state.metadata,
        "duration_days": duration,
        "remaining_budget_after_completion": str(remaining_budget),
    }
    state.save(
        update_fields=[
            "status",
            "started_day",
            "completed_day",
            "progress_percent",
            "actual_cost",
            "actual_person_days",
            "blocker_reason",
            "metadata",
        ]
    )

    run.current_day = completed_day + 1
    run.status = SimulationRun.Status.RUNNING
    run.metadata = {
        **run.metadata,
        "remaining_budget": str(remaining_budget),
        "spent_budget": str(spent_budget),
    }
    run.save(update_fields=["current_day", "status", "metadata"])
    mark_parent_stages_completed_if_ready(run=run, node=node, completed_day=completed_day)

    day_range = f"D{start_day}" if start_day == completed_day else f"D{start_day}-D{completed_day}"
    create_simulation_turn_and_event(
        run=run,
        title=f"完成计划节点：{node.code} {node.title}",
        summary=(
            f"{day_range} 完成 {node.code} {node.title}，消耗预算 {node.estimated_cost_expected} 元，"
            f"投入 {node.required_person_days} 人天。剩余模拟预算 {remaining_budget} 元。"
        ),
        simulation_day=start_day,
        severity=Event.Severity.INFO,
        event_type=Event.EventType.SIMULATION_DAY,
        payload={
            "plan_node_id": node.node_id,
            "actual_cost": str(node.estimated_cost_expected),
            "actual_person_days": str(node.required_person_days),
            "remaining_budget": str(remaining_budget),
        },
    )


def complete_simulation_run(run: SimulationRun) -> None:
    now = timezone.now()
    run.status = SimulationRun.Status.COMPLETED
    run.ended_at = now
    run.failure_summary = ""
    run.save(update_fields=["status", "ended_at", "failure_summary"])
    create_simulation_turn_and_event(
        run=run,
        title="自动模拟完成",
        summary="当前计划版本中的必要可执行节点已全部在本次模拟中完成，未发现阻断性失败。",
        simulation_day=run.current_day,
        severity=Event.Severity.INFO,
        event_type=Event.EventType.SIMULATION_DAY,
        payload={"completed": True},
    )


def pause_simulation_run_at_limit(run: SimulationRun) -> SimulationRun:
    run.status = SimulationRun.Status.PAUSED
    run.ended_at = timezone.now()
    run.metadata = {**run.metadata, "pause_reason": "达到最大推进步数，尚未失败或完成。"}
    run.save(update_fields=["status", "ended_at", "metadata"])
    create_simulation_turn_and_event(
        run=run,
        title="自动模拟暂停",
        summary="本次模拟达到最大推进步数，尚未失败或完成。可以提高步数后重新运行新的模拟。",
        simulation_day=run.current_day,
        severity=Event.Severity.WARNING,
        event_type=Event.EventType.SIMULATION_DAY,
        payload={"pause_reason": "max_turns"},
    )
    return run
