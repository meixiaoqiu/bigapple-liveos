"""Create auditable plan change sets from simulation feedback."""

from __future__ import annotations

from django.utils import timezone

from core.db import atomic_for_model
from core.models import PlanChangeOperation, PlanChangeSet, PlanRevisionProposal

from .feedback_operations import change_operations_for_proposal
from .ids import generate_plan_change_operation_id, generate_plan_change_set_id


@atomic_for_model(PlanChangeSet)
def create_plan_change_set_for_proposal(*, proposal: PlanRevisionProposal) -> PlanChangeSet:
    """Create an auditable structured patch from a simulation proposal."""

    existing = proposal.change_sets.order_by("-created_at", "change_set_id").first()
    if existing:
        return existing
    change_set = PlanChangeSet.objects.create(
        change_set_id=generate_plan_change_set_id(),
        run=proposal.run,
        proposal=proposal,
        plan_revision=proposal.plan_revision,
        status=PlanChangeSet.Status.DRAFT,
        title=f"结构化变更：{proposal.title}",
        summary=proposal.rationale,
        created_at=timezone.now(),
        metadata={"source": "observer_auto_run", "proposal_type": proposal.proposal_type},
    )
    for index, operation in enumerate(change_operations_for_proposal(proposal), start=1):
        PlanChangeOperation.objects.create(
            operation_id=generate_plan_change_operation_id(),
            change_set=change_set,
            sequence=index * 10,
            operation_type=operation["operation_type"],
            target_model=str(operation["target_model"]),
            target_id=str(operation.get("target_id") or ""),
            target_field=str(operation.get("target_field") or ""),
            old_value=operation.get("old_value", {}),
            new_value=operation.get("new_value", {}),
            rationale=str(operation["rationale"]),
            is_required=bool(operation.get("is_required", True)),
            metadata=operation.get("metadata", {}),
        )
    return change_set
