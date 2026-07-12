"""Proposal voting and result evaluation services."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.utils import timezone

from core.event_ledger import append_event
from core.event_payloads import proposal_payload, proposal_vote_payload
from core.models import Member, Proposal, ProposalVote, Role, RoleAssignment, SystemEvent

from .voters import calculate_required_approvals


def proposal_vote_counts(proposal: Proposal) -> dict[str, int]:
    return {
        "eligible": len(proposal.eligible_voters_snapshot_json or []),
        "yes": proposal.votes.filter(choice=ProposalVote.Choice.YES).count(),
        "no": proposal.votes.filter(choice=ProposalVote.Choice.NO).count(),
        "abstain": proposal.votes.filter(choice=ProposalVote.Choice.ABSTAIN).count(),
    }


def proposal_result(proposal: Proposal) -> dict[str, Any]:
    counts = proposal_vote_counts(proposal)
    participated = counts["yes"] + counts["no"] + counts["abstain"]
    required_yes = calculate_required_approvals(counts["eligible"], proposal.pass_ratio)
    quorum_count = proposal.quorum_count or 0
    return {
        **counts,
        "participated": participated,
        "required_yes": required_yes,
        "quorum_count": quorum_count,
        "quorum_reached": participated >= quorum_count,
        "passed": counts["yes"] >= required_yes and participated >= quorum_count,
    }


def evaluate_proposal(proposal: Proposal, *, at_time=None) -> Proposal:
    checked_at = at_time or timezone.now()
    if proposal.status != Proposal.Status.VOTING:
        return proposal

    result = proposal_result(proposal)
    if result["passed"]:
        proposal.status = Proposal.Status.PASSED
        proposal.passed_at = checked_at
        proposal.result_json = result
        proposal.save(update_fields=["status", "passed_at", "result_json", "updated_at"])
        append_event(
            event_type=SystemEvent.EventType.PROPOSAL_PASSED,
            aggregate_type="Proposal",
            aggregate_id=str(proposal.pk),
            actor_member=proposal.proposer_member,
            actor_role_assignment=proposal.proposer_role_assignment,
            payload_json=proposal_payload(proposal),
            occurred_at=checked_at,
        )
    elif checked_at >= proposal.deadline_at:
        proposal.status = Proposal.Status.FAILED
        proposal.failed_at = checked_at
        proposal.result_json = result
        proposal.save(update_fields=["status", "failed_at", "result_json", "updated_at"])
        append_event(
            event_type=SystemEvent.EventType.PROPOSAL_FAILED,
            aggregate_type="Proposal",
            aggregate_id=str(proposal.pk),
            actor_member=proposal.proposer_member,
            actor_role_assignment=proposal.proposer_role_assignment,
            payload_json=proposal_payload(proposal),
            occurred_at=checked_at,
        )
    else:
        proposal.result_json = result
        proposal.save(update_fields=["result_json", "updated_at"])
    return proposal


def fail_expired_proposal(proposal: Proposal, *, at_time=None) -> Proposal:
    return evaluate_proposal(proposal, at_time=at_time or timezone.now())


def cast_proposal_vote(
    *,
    proposal: Proposal,
    voter_member: Member,
    choice: str,
    reason: str = "",
    voter_role_assignment: RoleAssignment | None = None,
    at_time=None,
) -> ProposalVote:
    checked_at = at_time or timezone.now()
    proposal.refresh_from_db()
    evaluate_proposal(proposal, at_time=checked_at)
    proposal.refresh_from_db()
    if proposal.status != Proposal.Status.VOTING:
        raise ValidationError("该提案已经不在表决中。")
    if checked_at > proposal.deadline_at:
        raise ValidationError("该提案已经超过投票截止时间。")
    valid_choices = {item[0] for item in ProposalVote.Choice.choices}
    if choice not in valid_choices:
        raise ValidationError("无效的提案投票选择。")
    eligible_voters = {str(item) for item in (proposal.eligible_voters_snapshot_json or [])}
    if str(voter_member.pk) not in eligible_voters:
        raise ValidationError("该成员不在此提案的投票资格范围内。")

    if voter_role_assignment is None and proposal.voter_scope_role_id:
        voter_role_assignment = (
            RoleAssignment.objects.filter(
                member=voter_member,
                role=proposal.voter_scope_role,
                status=RoleAssignment.Status.ACTIVE,
                start_at__lte=checked_at,
                end_at__gte=checked_at,
            )
            .order_by("-start_at")
            .first()
        )

    existing_vote = ProposalVote.objects.filter(proposal=proposal, voter_member=voter_member).first()
    previous_choice = existing_vote.choice if existing_vote else None
    if existing_vote and not proposal.allow_vote_change:
        raise ValidationError("该提案不允许改票。")

    vote, created = ProposalVote.objects.update_or_create(
        proposal=proposal,
        voter_member=voter_member,
        defaults={
            "voter_role_assignment": voter_role_assignment,
            "choice": choice,
            "reason": reason,
            "voted_at": checked_at,
        },
    )
    vote.refresh_from_db()
    append_event(
        event_type=(
            SystemEvent.EventType.PROPOSAL_VOTE_CAST if created else SystemEvent.EventType.PROPOSAL_VOTE_CHANGED
        ),
        aggregate_type="ProposalVote",
        aggregate_id=str(vote.pk),
        actor_member=voter_member,
        actor_role_assignment=voter_role_assignment,
        payload_json=proposal_vote_payload(vote, previous_choice=previous_choice),
        occurred_at=checked_at,
    )
    evaluate_proposal(proposal, at_time=checked_at)
    return vote
