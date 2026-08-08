"""Governed appointment services for finance responsibilities."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .authorization_services import AuthorizationService
from .db import atomic_for_model
from .exceptions import DomainError
from .finance_setup import FINANCE_REVIEW_ROLE_NAME, ensure_finance_roles
from .governance_setup import MANAGE_ROLES_PERMISSION
from .models import Member, Proposal, ProposalExecution, ProposalVote, Role, RoleAssignment
from .proposals.execution import execute_proposal
from .proposals.lifecycle import create_role_appointment_proposal
from .proposals.voting import cast_proposal_vote
from .role_assignment_services import validate_role_assignment_prerequisites


OPEN_APPOINTMENT_STATUSES = {
    Proposal.Status.DRAFT,
    Proposal.Status.VOTING,
    Proposal.Status.PASSED,
}


def member_can_manage_finance_roles(member: Member) -> bool:
    """Return whether a member may nominate or execute finance appointments."""
    return AuthorizationService().member_has_permission(member, MANAGE_ROLES_PERMISSION)


def finance_review_role() -> Role:
    """Return the canonical finance review role, creating its baseline if needed."""
    return ensure_finance_roles()["review_role"]


def _assert_manager(actor: Member) -> None:
    if not member_can_manage_finance_roles(actor):
        raise DomainError("没有提名或执行财务职责任命的权限。")


def _assert_finance_review_proposal(proposal: Proposal) -> Role:
    role = finance_review_role()
    payload = proposal.payload_json or {}
    if proposal.proposal_type != Proposal.ProposalType.ROLE_APPOINTMENT:
        raise DomainError("该提案不是角色任命提案。")
    if str(payload.get("role_id", "")) != str(role.pk) or payload.get("role_name") != FINANCE_REVIEW_ROLE_NAME:
        raise DomainError("该提案不是财务审核职责任命提案。")
    return role


def finance_review_appointment_proposals():
    """Return finance-review appointment proposals without trusting client role ids."""
    role = finance_review_role()
    return Proposal.objects.filter(
        proposal_type=Proposal.ProposalType.ROLE_APPOINTMENT,
        payload_json__role_id=role.pk,
    ).order_by("-created_at")


@atomic_for_model(Proposal)
def nominate_finance_reviewer(*, actor: Member, target_member: Member, reason: str = "") -> Proposal:
    """Create a governed proposal to appoint one covenanter as finance reviewer."""
    _assert_manager(actor)
    target_member = Member.objects.select_for_update().select_related("user").get(pk=target_member.pk)
    role = finance_review_role()
    validate_role_assignment_prerequisites(target_member, role)
    now = timezone.now()
    if RoleAssignment.objects.filter(
        member=target_member,
        role=role,
        status=RoleAssignment.Status.ACTIVE,
        start_at__lte=now,
        end_at__gt=now,
    ).exists():
        raise DomainError("目标成员已经具有有效财务审核职责。")
    for proposal in finance_review_appointment_proposals().filter(status__in=OPEN_APPOINTMENT_STATUSES):
        if str((proposal.payload_json or {}).get("target_member_id", "")) == str(target_member.pk):
            raise DomainError("目标成员已经存在待处理的财务审核职责任命提案。")
    proposal = create_role_appointment_proposal(
        target_member=target_member,
        target_role=role,
        proposer_member=actor,
        reason=reason.strip(),
    )
    from .openfga_projection_services import project_voting_proposal

    transaction.on_commit(lambda: project_voting_proposal(proposal))
    return proposal


def vote_on_finance_reviewer_appointment(
    *, actor: Member, proposal: Proposal, choice: str, reason: str = "",
) -> ProposalVote:
    """Cast a vote on a finance-review appointment using the proposal electorate."""
    _assert_finance_review_proposal(proposal)
    try:
        return cast_proposal_vote(
            proposal=proposal,
            voter_member=actor,
            choice=choice,
            reason=reason.strip(),
        )
    except ValidationError as exc:
        raise DomainError("；".join(exc.messages)) from exc


@atomic_for_model(ProposalExecution)
def execute_finance_reviewer_appointment(*, actor: Member, proposal: Proposal) -> ProposalExecution:
    """Execute one passed finance-review appointment after manager authorization."""
    _assert_manager(actor)
    _assert_finance_review_proposal(proposal)
    proposal.refresh_from_db()
    if proposal.status != Proposal.Status.PASSED:
        raise DomainError("只有已通过的财务审核职责任命提案可以执行。")
    try:
        execution = execute_proposal(proposal=proposal, executor_member=actor)
    except ValidationError as exc:
        raise DomainError("；".join(exc.messages)) from exc
    return execution
