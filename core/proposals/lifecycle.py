"""Proposal creation and cancellation services."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.core.exceptions import ValidationError
from django.utils import timezone

from core.event_ledger import append_event
from core.event_payloads import iso_or_none, member_display_name, proposal_payload
from core.governance_setup import default_role_assignment_end_at
from core.models import Member, Organization, Proposal, Resource, Role, RoleAssignment, SystemEvent

from .voters import eligible_voter_snapshot
from .voting import proposal_result


def create_proposal(
    *,
    title: str,
    proposal_type: str,
    body: str = "",
    proposer_member: Member | None = None,
    proposer_role_assignment: RoleAssignment | None = None,
    organization: Organization | None = None,
    voter_scope_type: str = Proposal.VoterScopeType.ROLE,
    voter_scope_role: Role | None = None,
    voter_scope_organization: Organization | None = None,
    pass_ratio: int = 50,
    quorum_count: int | None = None,
    allow_vote_change: bool = True,
    start_at=None,
    deadline_at=None,
    payload_json: dict[str, Any] | None = None,
    status: str = Proposal.Status.VOTING,
) -> Proposal:
    starts_at = start_at or timezone.now()
    if deadline_at is None:
        deadline_at = starts_at + timedelta(days=7)
    snapshot = eligible_voter_snapshot(
        voter_scope_type=voter_scope_type,
        voter_scope_role=voter_scope_role,
        voter_scope_organization=voter_scope_organization,
        at_time=starts_at,
    )
    proposal = Proposal.objects.create(
        title=title,
        body=body,
        proposal_type=proposal_type,
        status=status,
        proposer_member=proposer_member,
        proposer_role_assignment=proposer_role_assignment,
        organization=organization,
        voter_scope_type=voter_scope_type,
        voter_scope_role=voter_scope_role,
        voter_scope_organization=voter_scope_organization,
        eligible_voters_snapshot_json=snapshot,
        pass_ratio=pass_ratio,
        quorum_count=quorum_count if quorum_count is not None else min(1, len(snapshot)),
        allow_vote_change=allow_vote_change,
        start_at=starts_at,
        deadline_at=deadline_at,
        payload_json=payload_json or {},
    )
    return proposal


def create_role_appointment_proposal(
    *,
    target_member: Member,
    target_role: Role,
    proposer_member: Member | None = None,
    proposer_role_assignment: RoleAssignment | None = None,
    start_at=None,
    end_at=None,
    deadline_at=None,
    assignment_type: str = "role_assignment",
    resource: Resource | None = None,
    scope_json: dict[str, Any] | None = None,
    reason: str = "",
) -> Proposal:
    starts_at = start_at or timezone.now()
    assignment_end_at = end_at or default_role_assignment_end_at(starts_at)
    deadline = deadline_at or starts_at + timedelta(days=target_role.appointment_deadline_days)
    payload = {
        "target_member_id": target_member.pk,
        "target_member_no": target_member.member_no,
        "target_member_display_name": member_display_name(target_member),
        "role_id": target_role.pk,
        "role_name": target_role.name,
        "assignment_type": assignment_type,
        "resource_id": resource.pk if resource else None,
        "scope_json": scope_json or {},
        "reason": reason,
        "start_at": iso_or_none(starts_at),
        "end_at": iso_or_none(assignment_end_at),
    }
    return create_proposal(
        title=f"任命 {member_display_name(target_member)} 为 {target_role.name}",
        body=reason,
        proposal_type=Proposal.ProposalType.ROLE_APPOINTMENT,
        proposer_member=proposer_member,
        proposer_role_assignment=proposer_role_assignment,
        organization=target_role.organization,
        voter_scope_type=Proposal.VoterScopeType.ROLE,
        voter_scope_role=target_role.appointment_electorate_role,
        pass_ratio=target_role.appointment_required_percent,
        quorum_count=None,
        allow_vote_change=True,
        start_at=starts_at,
        deadline_at=deadline,
        payload_json=payload,
        status=Proposal.Status.VOTING,
    )

def cancel_proposal(
    *,
    proposal: Proposal,
    actor_member: Member | None = None,
    actor_role_assignment: RoleAssignment | None = None,
    at_time=None,
) -> Proposal:
    checked_at = at_time or timezone.now()
    if proposal.status not in {Proposal.Status.DRAFT, Proposal.Status.VOTING}:
        raise ValidationError("只有草稿或表决中的提案可以取消。")
    previous_status = proposal.status
    proposal.status = Proposal.Status.CANCELLED
    proposal.cancelled_at = checked_at
    proposal.result_json = proposal_result(proposal) if previous_status == Proposal.Status.VOTING else proposal.result_json
    proposal.save(update_fields=["status", "cancelled_at", "result_json", "updated_at"])
    append_event(
        event_type=SystemEvent.EventType.PROPOSAL_CANCELLED,
        aggregate_type="Proposal",
        aggregate_id=str(proposal.pk),
        actor_member=actor_member,
        actor_role_assignment=actor_role_assignment,
        payload_json=proposal_payload(proposal),
        occurred_at=checked_at,
    )
    return proposal
