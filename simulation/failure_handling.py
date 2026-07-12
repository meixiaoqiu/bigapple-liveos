"""Failure handling and feedback proposal creation for simulation runs."""

from __future__ import annotations

from django.utils import timezone

from core.models import Event, PlanNodeRunState, PlanRevisionProposal, SimulationFailure, SimulationRun

from .feedback_services import create_plan_change_set_for_proposal
from .feedback_suggestions import proposal_type_for_failure, suggested_changes_for_failure
from .ids import generate_plan_revision_proposal_id, generate_simulation_failure_id
from .run_state import create_simulation_turn_and_event


def fail_simulation_node(
    *,
    run: SimulationRun,
    state: PlanNodeRunState,
    failure_data: dict[str, object],
) -> tuple[SimulationFailure, PlanRevisionProposal]:
    node = state.plan_node
    now = timezone.now()
    state.status = PlanNodeRunState.Status.FAILED
    state.started_day = state.started_day or run.current_day
    state.blocker_reason = str(failure_data["description"])
    state.metadata = {**state.metadata, "failure_type": failure_data["failure_type"], **failure_data["metadata"]}
    state.save(update_fields=["status", "started_day", "blocker_reason", "metadata"])

    run.status = SimulationRun.Status.FAILED
    run.ended_at = now
    run.failure_summary = str(failure_data["description"])
    run.save(update_fields=["status", "ended_at", "failure_summary"])

    failure = SimulationFailure.objects.create(
        failure_id=generate_simulation_failure_id(),
        run=run,
        plan_node=node,
        failure_type=str(failure_data["failure_type"]),
        severity=SimulationFailure.Severity.CRITICAL,
        title=str(failure_data["title"]),
        description=str(failure_data["description"]),
        simulation_day=run.current_day,
        detected_at=now,
        metadata=failure_data["metadata"],
    )
    proposal_type = proposal_type_for_failure(failure.failure_type)
    proposal = PlanRevisionProposal.objects.create(
        proposal_id=generate_plan_revision_proposal_id(),
        run=run,
        source_failure=failure,
        plan_revision=run.plan_revision,
        plan_node=node,
        proposal_type=proposal_type,
        status=PlanRevisionProposal.Status.DRAFT,
        title=f"根据失败修订 {node.code} {node.title}",
        rationale=failure.description,
        suggested_changes=suggested_changes_for_failure(
            node=node,
            failure_type=failure.failure_type,
            metadata=failure.metadata,
        ),
        created_at=now,
        metadata={"source": "observer_auto_run"},
    )
    change_set = create_plan_change_set_for_proposal(proposal=proposal)
    create_simulation_turn_and_event(
        run=run,
        title=f"自动模拟失败：{node.code} {node.title}",
        summary=(
            f"{failure.description} 已生成计划修订建议 {proposal.proposal_id} "
            f"和结构化变更集 {change_set.change_set_id}，等待人工审核。"
        ),
        simulation_day=run.current_day,
        severity=Event.Severity.CRITICAL,
        event_type=Event.EventType.RANDOM_INCIDENT,
        payload={
            "failure_id": failure.failure_id,
            "proposal_id": proposal.proposal_id,
            "change_set_id": change_set.change_set_id,
            "plan_node_id": node.node_id,
            "failure_type": failure.failure_type,
        },
    )
    return failure, proposal
