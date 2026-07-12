"""Snapshot payload builders for the unified event ledger."""

from __future__ import annotations

from typing import Any

from .models import Dispute, LedgerEntry, Member, Proposal, ProposalVote, Resource, RoleAssignment, SystemEvent, Task


def iso_or_none(value) -> str | None:
    return value.isoformat() if value else None


def member_display_name(member: Member | None) -> str:
    if member is None:
        return ""
    return str(member.display_name or member.profile.get("display_name") or member.member_no)


def role_assignment_payload(assignment: RoleAssignment) -> dict[str, Any]:
    role = assignment.role
    organization = role.organization
    return {
        "role_assignment_id": assignment.pk,
        "member_no": assignment.member.member_no,
        "member_display_name": member_display_name(assignment.member),
        "role_id": role.pk,
        "role_name": role.name,
        "organization_id": organization.pk,
        "organization_name": organization.name,
        "status": assignment.status,
        "start_at": iso_or_none(assignment.start_at),
        "end_at": iso_or_none(assignment.end_at),
        "granted_by_id": assignment.granted_by_id,
        "granted_by_display_name": member_display_name(assignment.granted_by),
        "revoked_by_id": assignment.revoked_by_id,
        "revoked_by_display_name": member_display_name(assignment.revoked_by),
        "source_type": assignment.source_type,
        "source_proposal_id": assignment.source_proposal_id,
        "source_proposal_execution_id": assignment.source_proposal_execution_id,
    }


def actor_member_from_ref(actor_ref: dict[str, Any] | None) -> Member | None:
    """Resolve a service-layer ActorRef JSON object back to a Member when possible."""

    if not actor_ref:
        return None
    actor_id = actor_ref.get("actor_id")
    if not actor_id:
        return None
    return Member.objects.filter(member_no=actor_id).first()


def ledger_entry_payload(entry: LedgerEntry) -> dict[str, Any]:
    """Snapshot a contribution ledger entry for the unified system event ledger."""

    return {
        "ledger_entry_id": entry.pk,
        "member_no": entry.member.member_no,
        "member_display_name": member_display_name(entry.member),
        "amount": entry.amount,
        "entry_type": entry.entry_type,
        "reason": entry.reason,
        "related_task_id": entry.related_task_id,
        "related_event_id": entry.related_event_id,
        "rule_version": entry.rule_version,
        "created_at": iso_or_none(entry.created_at),
        "created_by": entry.created_by,
        "reviewer": entry.reviewer,
        "status": entry.status,
        "reverses_entry_id": entry.reverses_entry_id,
        "system_event_id": entry.system_event_id,
        "system_event_seq": entry.system_event.seq if entry.system_event_id else None,
        "metadata": entry.metadata,
    }


def ledger_entry_event_type(entry: LedgerEntry) -> str:
    if entry.entry_type == LedgerEntry.EntryType.REVERSAL or entry.reverses_entry_id:
        return SystemEvent.EventType.CREDIT_REVERSED
    if entry.entry_type in {LedgerEntry.EntryType.CONSUMPTION, LedgerEntry.EntryType.PENALTY} or entry.amount < 0:
        return SystemEvent.EventType.CREDIT_DEDUCTED
    if entry.entry_type in {LedgerEntry.EntryType.CORRECTION, LedgerEntry.EntryType.COMPENSATION}:
        return SystemEvent.EventType.CREDIT_ADJUSTED
    return SystemEvent.EventType.CREDIT_EARNED


def task_event_payload(
    task: Task,
    *,
    action: str,
    actor: dict[str, Any] | None = None,
    previous_status: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Snapshot a task lifecycle transition for the unified system event ledger."""

    payload = {
        "task_id": task.pk,
        "title": task.title,
        "task_type": task.task_type,
        "action": action,
        "previous_status": previous_status,
        "status": task.status,
        "assignee_member_id": task.assignee_member_id,
        "assignee_member_no": task.assignee_member.member_no if task.assignee_member_id else "",
        "assignee_display_name": member_display_name(task.assignee_member),
        "plan_node_id": task.plan_node_id,
        "source_type": task.source_type,
        "source_proposal_id": task.source_proposal_id,
        "source_proposal_execution_id": task.source_proposal_execution_id,
        "rule_version": task.rule_version,
        "created_at": iso_or_none(task.created_at),
        "due_at": iso_or_none(task.due_at),
        "submitted_at": iso_or_none(task.submitted_at),
        "reviewed_at": iso_or_none(task.reviewed_at),
        "actor": actor or {},
        "metadata": task.metadata,
    }
    if extra:
        payload.update(extra)
    return payload


def resource_adjustment_payload(
    resource: Resource,
    *,
    actor: dict[str, Any] | None = None,
    old_stock,
    delta,
    reason: str,
    warning: bool,
    transaction_id: str = "",
) -> dict[str, Any]:
    """Snapshot a resource stock adjustment for the unified system event ledger."""

    return {
        "resource_id": resource.pk,
        "transaction_id": transaction_id,
        "name": resource.name,
        "resource_type": resource.resource_type,
        "unit": resource.unit,
        "old_stock": str(old_stock),
        "delta": str(delta),
        "new_stock": str(resource.current_stock),
        "warning_threshold": str(resource.warning_threshold),
        "is_warning": warning,
        "replenishment_method": resource.replenishment_method,
        "reason": reason,
        "actor": actor or {},
        "updated_at": iso_or_none(resource.updated_at),
        "metadata": resource.metadata,
    }


def dispute_event_payload(
    dispute: Dispute,
    *,
    action: str,
    actor: dict[str, Any] | None = None,
    previous_status: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Snapshot a dispute lifecycle transition for the unified system event ledger."""

    payload = {
        "dispute_id": dispute.pk,
        "dispute_type": dispute.dispute_type,
        "action": action,
        "previous_status": previous_status,
        "status": dispute.status,
        "claimant_member_id": dispute.claimant_member_id,
        "claimant_member_no": dispute.claimant_member.member_no,
        "claimant_display_name": member_display_name(dispute.claimant_member),
        "respondent_member_id": dispute.respondent_member_id,
        "respondent_member_no": dispute.respondent_member.member_no if dispute.respondent_member_id else "",
        "respondent_display_name": member_display_name(dispute.respondent_member),
        "related_task_id": dispute.related_task_id,
        "related_ledger_entry_id": dispute.related_ledger_entry_id,
        "facts": dispute.facts,
        "evidence_refs": dispute.evidence_refs,
        "handler": dispute.handler,
        "reviewer": dispute.reviewer,
        "resolution": dispute.resolution,
        "appeal_path": dispute.appeal_path,
        "submitted_at": iso_or_none(dispute.submitted_at),
        "resolved_at": iso_or_none(dispute.resolved_at),
        "actor": actor or {},
        "metadata": dispute.metadata,
    }
    if extra:
        payload.update(extra)
    return payload


def proposal_payload(proposal: Proposal) -> dict[str, Any]:
    return {
        "proposal_id": proposal.pk,
        "proposal_no": proposal.proposal_no,
        "proposal_type": proposal.proposal_type,
        "title": proposal.title,
        "status": proposal.status,
        "proposer_member_id": proposal.proposer_member_id,
        "proposer_member_no": proposal.proposer_member.member_no if proposal.proposer_member_id else "",
        "proposer_member_display_name": member_display_name(proposal.proposer_member),
        "proposer_role_assignment_id": proposal.proposer_role_assignment_id,
        "organization_id": proposal.organization_id,
        "pass_ratio": proposal.pass_ratio,
        "quorum_count": proposal.quorum_count,
        "deadline_at": iso_or_none(proposal.deadline_at),
        "result": proposal.result_json,
        "payload": proposal.payload_json,
    }


def proposal_vote_payload(vote: ProposalVote, *, previous_choice: str | None = None) -> dict[str, Any]:
    proposal = vote.proposal
    return {
        "proposal_id": proposal.pk,
        "proposal_no": proposal.proposal_no,
        "proposal_type": proposal.proposal_type,
        "title": proposal.title,
        "voter_member_id": vote.voter_member_id,
        "voter_member_no": vote.voter_member.member_no,
        "voter_member_display_name": member_display_name(vote.voter_member),
        "voter_role_assignment_id": vote.voter_role_assignment_id,
        "choice": vote.choice,
        "previous_choice": previous_choice,
        "reason": vote.reason,
        "voted_at": iso_or_none(vote.voted_at),
    }
