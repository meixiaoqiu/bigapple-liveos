"""Translate simulation feedback proposals into declarative plan operations."""

from __future__ import annotations

from core.models import PlanChangeOperation, PlanRevisionProposal, SimulationFailure

from .feedback_operation_handlers import (
    budget_unrealistic_operations,
    dependency_unmet_operations,
    labor_shortage_operations,
    personnel_issue_operations,
    responsibility_closure_operations,
    resource_shortage_operations,
    skill_shortage_operations,
)

OPERATION_BUILDERS = {
    SimulationFailure.FailureType.SKILL_SHORTAGE: skill_shortage_operations,
    SimulationFailure.FailureType.RESPONSIBILITY_CLOSURE_MISSING: responsibility_closure_operations,
    SimulationFailure.FailureType.BUDGET_UNREALISTIC: budget_unrealistic_operations,
    SimulationFailure.FailureType.LABOR_SHORTAGE: labor_shortage_operations,
    SimulationFailure.FailureType.RESOURCE_SHORTAGE: resource_shortage_operations,
    SimulationFailure.FailureType.PERSONNEL_ISSUE: personnel_issue_operations,
    SimulationFailure.FailureType.DEPENDENCY_UNMET: dependency_unmet_operations,
}


def _note_operation_for_missing_failure(proposal: PlanRevisionProposal) -> dict[str, object]:
    return {
        "operation_type": PlanChangeOperation.OperationType.NOTE,
        "target_model": "PlanRevision",
        "target_id": proposal.plan_revision_id,
        "target_field": "",
        "old_value": {},
        "new_value": {"note": proposal.suggested_changes},
        "rationale": proposal.rationale,
        "is_required": False,
    }


def _fallback_note_operation(proposal: PlanRevisionProposal) -> dict[str, object]:
    return {
        "operation_type": PlanChangeOperation.OperationType.NOTE,
        "target_model": "PlanNode",
        "target_id": proposal.plan_node_id,
        "target_field": "",
        "old_value": {},
        "new_value": proposal.suggested_changes,
        "rationale": proposal.source_failure.description if proposal.source_failure else proposal.rationale,
        "is_required": False,
    }


def change_operations_for_proposal(proposal: PlanRevisionProposal) -> list[dict[str, object]]:
    """Translate one proposal into auditable plan-data operations.

    The operations are intentionally declarative. They describe how a future
    PlanRevision should change, but this function does not apply them.
    """

    if proposal.plan_node is None or proposal.source_failure is None:
        return [_note_operation_for_missing_failure(proposal)]

    builder = OPERATION_BUILDERS.get(proposal.source_failure.failure_type)
    operations = builder(proposal) if builder else []
    return operations or [_fallback_note_operation(proposal)]
