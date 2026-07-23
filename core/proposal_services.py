"""Unified approval-proposal services for cross-subsystem governance.

Handles creation, approval, rejection and execution of
``ApprovalProposal`` instances.  All mutations emit ``SystemEvent``
entries.

**Approval tier policy** (centralised here – DO NOT duplicate in
procurement or other subsystems):

- amount == 0 or donation → ``SINGLE`` (any one of governance / finance)
- 0 < amount <= 500         → ``SINGLE``
- 500 < amount <= 5000      → ``STANDARD`` (governance + finance)
- amount > 5000             → ``MAJOR`` (governance + finance + second_governance)

These thresholds are code-level constants.  They can be promoted to
database configuration later without changing callers.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from .access import is_finance_reviewer, is_governance_principal
from .event_ledger import append_event
from .event_payloads import approval_proposal_payload
from .exceptions import DomainError
from .models import (
    ApprovalDecision,
    ApprovalProposal,
    Member,
    SystemEvent,
)

SMALL_PURCHASE_LIMIT = Decimal("500")
STANDARD_PURCHASE_LIMIT = Decimal("5000")

# ── reusable tier helpers (public API) ───────────────────────────────


def compute_procurement_approval_tier(
    offer_type: str, estimated_total_amount: Decimal,
) -> str:
    """Return the ``SupplierQuote.ApprovalTier`` for a new offer.

    Called from ``procurement_services.submit_resource_offer``` (the
    **only** call site for setting the quote-tier snapshot).  All
    other consumers should use the higher-level role-group functions
    below.

    *offer_type* values: ``"quote"`` or ``"donation"``.
    """
    if offer_type == "donation" or estimated_total_amount == 0:
        return "small"
    if estimated_total_amount <= SMALL_PURCHASE_LIMIT:
        return "small"
    if estimated_total_amount <= STANDARD_PURCHASE_LIMIT:
        return "standard"
    return "major"


def supplier_quote_tier_to_proposal_tier(quote_tier: str) -> str:
    """Map SupplierQuote.ApprovalTier → ApprovalProposal.Tier."""
    tier_map = {"small": "single", "standard": "standard", "major": "major"}
    return tier_map.get(quote_tier, "single")


# ── internal helpers ──────────────────────────────────────────────────


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def _valid_approval_roles(proposal: ApprovalProposal) -> set[str]:
    """Return the flat set of all roles that can approve this proposal."""
    groups = proposal_required_role_groups(proposal)
    roles: set[str] = set()
    for g in groups:
        roles.update(g)
    return roles


def proposal_required_role_groups(proposal: ApprovalProposal) -> list[set[str]]:
    """Return required approval role-groups.

    Each inner set represents one required slot.  A ``SINGLE`` tier
    procurement returns ``[{"governance","finance"}]`` (any one of
    these).  ``STANDARD`` returns ``[{"governance"},{"finance"}]``
    (both needed).  ``MAJOR`` returns ``[{"governance"},{"finance"},
    {"second_governance"}]`` (all three needed).
    """
    if proposal.proposal_type == ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE:
        tier = proposal.approval_tier
        if tier == ApprovalProposal.Tier.SINGLE:
            return [{"governance", "finance"}]
        elif tier == ApprovalProposal.Tier.STANDARD:
            return [{"governance"}, {"finance"}]
        elif tier == ApprovalProposal.Tier.MAJOR:
            return [{"governance"}, {"finance"}, {"second_governance"}]
    elif proposal.proposal_type == ApprovalProposal.ProposalType.PROCUREMENT_PAYMENT:
        return [{"finance"}]
    return [{"governance"}]


def proposal_required_roles(proposal: ApprovalProposal) -> list[str]:
    """Flat list of required roles (for display)."""
    return sorted(_valid_approval_roles(proposal))


def proposal_approved_roles(proposal: ApprovalProposal) -> list[str]:
    """Return roles that have already approved."""
    return list(
        ApprovalDecision.objects.filter(
            proposal=proposal, decision=ApprovalDecision.Decision.APPROVED,
        ).values_list("role", flat=True)
    )


def proposal_missing_roles(proposal: ApprovalProposal) -> list[str]:
    """Return role-group display strings for missing slots."""
    groups = proposal_required_role_groups(proposal)
    approved = set(proposal_approved_roles(proposal))
    missing: list[str] = []
    for g in groups:
        if not (g & approved):
            missing.append("/".join(sorted(g)))
    return missing


def proposal_is_approved(proposal: ApprovalProposal) -> bool:
    """True when at least one role in each group has approved."""
    groups = proposal_required_role_groups(proposal)
    approved = set(proposal_approved_roles(proposal))
    for g in groups:
        if not (g & approved):
            return False
    return True


def _member_role_for_proposal(member: Member, proposal: ApprovalProposal) -> list[str]:
    """Return roles a member can fill for this proposal."""
    roles: list[str] = []
    if is_governance_principal(member):
        roles.append("governance")
        roles.append("second_governance")
    if is_finance_reviewer(member):
        roles.append("finance")
    return roles


def _member_can_approve(member: Member, proposal: ApprovalProposal, role: str) -> bool:
    return role in _member_role_for_proposal(member, proposal)


def member_available_approval_roles(
    member: Member, proposal: ApprovalProposal,
) -> list[str]:
    """Return roles this member could fill that are still needed."""
    member_roles = set(_member_role_for_proposal(member, proposal))
    approved = set(proposal_approved_roles(proposal))
    already = set(
        ApprovalDecision.objects.filter(
            proposal=proposal, approver=member,
        ).values_list("role", flat=True)
    )
    # A member can fill a role if: the role is in one of the missing groups,
    # the member has that role, and hasn't already approved.
    groups = proposal_required_role_groups(proposal)
    available: list[str] = []
    for g in groups:
        if g & approved:
            continue  # this group is already satisfied
        candidates = g & member_roles - already
        if candidates:
            available.extend(sorted(candidates))
    return available


def proposal_is_actionable_by(member: Member, proposal: ApprovalProposal) -> bool:
    return len(member_available_approval_roles(member, proposal)) > 0


def proposal_is_executable_by(member: Member, proposal: ApprovalProposal) -> bool:
    if proposal.status != ApprovalProposal.Status.APPROVED:
        return False
    return is_governance_principal(member) or is_finance_reviewer(member)


def proposal_target_url(proposal: ApprovalProposal) -> str:
    if proposal.target_type == "supplier_quote":
        return "/workspace/procurement/?status=submitted"
    return ""


# ── lifecycle ────────────────────────────────────────────────────────


def create_approval_proposal(
    *,
    proposal_type: str,
    title: str,
    submitted_by: Member,
    dedupe_key: str,
    target_type: str = "",
    target_id: str = "",
    summary: str = "",
    public_reason: str = "",
    approval_tier: str = "",
    metadata: dict | None = None,
) -> ApprovalProposal:
    """Create an approval proposal.  *dedupe_key* is required and unique
    per *proposal_type*."""
    if not dedupe_key:
        raise DomainError("dedupe_key 不能为空。")

    if proposal_type not in {v for v, _ in ApprovalProposal.ProposalType.choices}:
        raise DomainError("提案类型无效。")

    if not approval_tier:
        approval_tier = ApprovalProposal.Tier.SINGLE

    if approval_tier not in {v for v, _ in ApprovalProposal.Tier.choices}:
        raise DomainError("审批层级无效。")

    # Dedupe by proposal_type + dedupe_key
    existing = ApprovalProposal.objects.filter(
        proposal_type=proposal_type,
        dedupe_key=dedupe_key,
    ).first()
    if existing is not None:
        return existing

    proposal = ApprovalProposal.objects.create(
        proposal_id=_new_id("proposal"),
        proposal_type=proposal_type,
        dedupe_key=dedupe_key,
        title=title,
        summary=summary,
        public_reason=public_reason,
        approval_tier=approval_tier,
        target_type=target_type,
        target_id=target_id,
        submitted_by=submitted_by,
        metadata=dict(metadata or {}),
        created_at=timezone.now(),
        updated_at=timezone.now(),
    )

    append_event(
        event_type=SystemEvent.EventType.APPROVAL_PROPOSAL_SUBMITTED,
        aggregate_type="ApprovalProposal",
        aggregate_id=proposal.proposal_id,
        actor_member=submitted_by,
        payload_json=approval_proposal_payload(proposal, action="submitted", actor=submitted_by),
        occurred_at=proposal.submitted_at,
    )
    return proposal


@transaction.atomic
def approve_proposal(
    *,
    proposal: ApprovalProposal,
    approved_by: Member,
    role: str,
    reason: str = "",
) -> ApprovalProposal:
    """Approve a proposal for one required role-slot."""
    proposal = ApprovalProposal.objects.select_for_update().get(pk=proposal.pk)

    if proposal.status != ApprovalProposal.Status.SUBMITTED:
        raise DomainError("只能审批状态为'已提交'的提案。")

    valid_roles = _valid_approval_roles(proposal)
    if role not in valid_roles:
        raise DomainError(f"该提案不需要 {role} 审批。")

    if not _member_can_approve(approved_by, proposal, role):
        raise DomainError("你不具备该审批角色。")

    # Same person cannot fill multiple roles in this proposal
    existing_approvals = ApprovalDecision.objects.filter(
        proposal=proposal, decision=ApprovalDecision.Decision.APPROVED,
    )
    if existing_approvals.filter(approver=approved_by).exists():
        raise DomainError("同一人不能同时满足多个审批角色。")

    if role == "second_governance":
        if existing_approvals.filter(role="governance", approver=approved_by).exists():
            raise DomainError("治理二次确认人不能与第一次治理审批人为同一人。")

    if role == "second_governance" and not existing_approvals.filter(role="finance").exists():
        raise DomainError("需先完成财务确认。")
    if role == "finance" and not existing_approvals.filter(role="governance").exists():
        raise DomainError("需先完成治理采纳。")

    ApprovalDecision.objects.create(
        approval_id=_new_id("approval"),
        proposal=proposal,
        approver=approved_by,
        role=role,
        decision=ApprovalDecision.Decision.APPROVED,
        reason=reason,
        created_at=timezone.now(),
    )

    if proposal_is_approved(proposal):
        proposal.status = ApprovalProposal.Status.APPROVED
        proposal.resolved_at = timezone.now()
        event_type = SystemEvent.EventType.APPROVAL_PROPOSAL_APPROVED
    else:
        event_type = SystemEvent.EventType.APPROVAL_PROPOSAL_SUBMITTED

    proposal.updated_at = timezone.now()
    proposal.save(update_fields=["status", "resolved_at", "updated_at"])

    append_event(
        event_type=event_type,
        aggregate_type="ApprovalProposal",
        aggregate_id=proposal.proposal_id,
        actor_member=approved_by,
        payload_json=approval_proposal_payload(proposal, action=f"approved_{role}", actor=approved_by),
        occurred_at=timezone.now(),
    )
    return proposal


@transaction.atomic
def reject_proposal(
    *,
    proposal: ApprovalProposal,
    rejected_by: Member,
    role: str,
    reason: str = "",
) -> ApprovalProposal:
    """Reject a proposal.  *role* must be a valid approval role for this
    proposal (same validation as ``approve_proposal``)."""
    proposal = ApprovalProposal.objects.select_for_update().get(pk=proposal.pk)

    if proposal.status != ApprovalProposal.Status.SUBMITTED:
        raise DomainError("只能拒绝状态为'已提交'的提案。")

    valid_roles = _valid_approval_roles(proposal)
    if role not in valid_roles:
        raise DomainError(f"该提案不支持 {role} 拒绝。")

    if not _member_can_approve(rejected_by, proposal, role):
        raise DomainError("你不具备该审批角色。")

    ApprovalDecision.objects.create(
        approval_id=_new_id("approval"),
        proposal=proposal,
        approver=rejected_by,
        role=role,
        decision=ApprovalDecision.Decision.REJECTED,
        reason=reason,
        created_at=timezone.now(),
    )

    proposal.status = ApprovalProposal.Status.REJECTED
    proposal.resolved_at = timezone.now()
    proposal.updated_at = timezone.now()
    proposal.save(update_fields=["status", "resolved_at", "updated_at"])

    # Sync rejection to the target
    if (
        proposal.proposal_type == ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE
        and proposal.target_type == "supplier_quote"
    ):
        from .procurement_services import reject_resource_offer as _reject_quote
        from .models import SupplierQuote
        try:
            quote = SupplierQuote.objects.get(quote_id=proposal.target_id)
            _reject_quote(quote=quote, rejected_by=rejected_by, decision_reason=reason)
        except SupplierQuote.DoesNotExist:
            pass
    elif proposal.proposal_type == ApprovalProposal.ProposalType.MEMBER_APPLICATION:
        from .application_services import reject_member_application_from_approval_proposal
        reject_member_application_from_approval_proposal(proposal=proposal, reason=reason)

    append_event(
        event_type=SystemEvent.EventType.APPROVAL_PROPOSAL_REJECTED,
        aggregate_type="ApprovalProposal",
        aggregate_id=proposal.proposal_id,
        actor_member=rejected_by,
        payload_json=approval_proposal_payload(proposal, action="rejected", actor=rejected_by),
        occurred_at=proposal.resolved_at,
    )
    return proposal


@transaction.atomic
def execute_proposal(
    *,
    proposal: ApprovalProposal,
    actor: Member,
) -> ApprovalProposal:
    """Execute an approved proposal. Idempotent."""
    proposal = ApprovalProposal.objects.select_for_update().get(pk=proposal.pk)

    if proposal.status == ApprovalProposal.Status.EXECUTED:
        return proposal

    if proposal.status != ApprovalProposal.Status.APPROVED:
        raise DomainError("只能执行已通过的提案。")

    if proposal.proposal_type == ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE:
        from .procurement_services import _execute_procurement_acceptance
        _execute_procurement_acceptance(proposal=proposal, actor=actor)
    elif proposal.proposal_type == ApprovalProposal.ProposalType.MEMBER_APPLICATION:
        from .application_services import admit_member_application_from_approval_proposal
        admit_member_application_from_approval_proposal(proposal=proposal, actor=actor)

    proposal.status = ApprovalProposal.Status.EXECUTED
    proposal.executed_at = timezone.now()
    proposal.updated_at = timezone.now()
    proposal.save(update_fields=["status", "executed_at", "updated_at"])

    append_event(
        event_type=SystemEvent.EventType.APPROVAL_PROPOSAL_EXECUTED,
        aggregate_type="ApprovalProposal",
        aggregate_id=proposal.proposal_id,
        actor_member=actor,
        payload_json=approval_proposal_payload(proposal, action="executed", actor=actor),
        occurred_at=proposal.executed_at,
    )
    return proposal
