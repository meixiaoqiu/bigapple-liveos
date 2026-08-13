"""Workspace query assembly.

This module stays HTTP-free so API views and member-facing pages can share the
same member-centered read model without putting portal presentation queries in
the core rules engine.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Count, F, Q, Sum
from django.shortcuts import get_object_or_404

from core.access import is_finance_reviewer, member_can_administer
from core.authorization_services import AuthorizationService
from core.application_services import _application_role_gap_label
from core.identity_display import member_identity_display
from core.models import (
    CapacityAssessment,
    Dispute,
    Event,
    LedgerEntry,
    Member,
    MemberApplication,
    MerchantProfile,
    Proposal,
    ProposalVote,
    Resource,
    Task,
)

from core.proposals.voting import proposal_result


# Admission filter groups driven by the linked member_admission proposal lifecycle.
# There is no standalone "review" status — every application that reaches the
# governance review list already has an auto-created admission proposal.
ADMISSION_FILTER_GROUPS = ("voting", "passed_pending", "admitted", "rejected", "all")

ADMISSION_FILTER_LABELS: dict[str, str] = {
    "voting": "投票中",
    "passed_pending": "已通过待执行",
    "admitted": "已接纳",
    "rejected": "未通过/已拒绝",
    "all": "全部",
}


def member_has_full_workspace_access(member: Member) -> bool:
    """Return True if *member* is entitled to the full workspace.

    Full workspace access is primarily granted by the ``ROLE_COVENANTER``
    role.  Lifecycle-disabled statuses (``SUSPENDED``, ``EXITED``) act as a
    hard veto — even an active ``ROLE_COVENANTER`` assignment cannot
    override them.

    ``Member.status`` is a lifecycle display field and is NOT the source of
    truth for covenantership decisions.
    """
    return AuthorizationService().member_has_full_workspace_access(member)


def workspace_access_decision(member: Member):
    return AuthorizationService().full_workspace_access_decision(member)


def applicant_workspace_context(member_no: str, *, access_denial_reason: str = "not_authorized") -> dict[str, Any]:
    member = get_object_or_404(Member, member_no=member_no)
    latest_application = (
        MemberApplication.objects.filter(linked_member=member)
        .select_related("admission_proposal")
        .order_by("-submitted_at", "application_id")
        .first()
    )
    can_reapply = bool(
        latest_application
        and latest_application.status in {MemberApplication.Status.REJECTED, MemberApplication.Status.WITHDREW}
    )
    can_apply = latest_application is None or can_reapply
    role_gap_label = ""
    if latest_application:
        role_gap_label = _application_role_gap_label(latest_application)
    return {
        "member": member,
        "identity_display": member_identity_display(member),
        "application": latest_application,
        "can_reapply": can_reapply,
        "can_apply": can_apply,
        "role_gap_label": role_gap_label,
        "authorization_unavailable": access_denial_reason == "authorization_unavailable",
    }


def workspace_context(member_no: str) -> dict[str, Any]:
    member = get_object_or_404(Member, member_no=member_no)
    latest = CapacityAssessment.objects.order_by("-simulation_day", "-created_at").first()
    available_tasks = list(Task.objects.filter(status=Task.Status.OPEN).order_by("due_at", "task_id")[:10])
    active_task_statuses = [
        Task.Status.CLAIMED,
        Task.Status.IN_PROGRESS,
        Task.Status.PENDING_REVIEW,
        Task.Status.DISPUTED,
    ]
    active_tasks = list(
        Task.objects.filter(assignee_member=member, status__in=active_task_statuses).order_by("due_at", "task_id")[:10]
    )
    recent_ledger_entries = list(
        LedgerEntry.objects.filter(member=member).order_by("-system_event__seq", "-created_at", "ledger_entry_id")[:10]
    )
    all_member_disputes = Dispute.objects.filter(Q(claimant_member=member) | Q(respondent_member=member))
    open_disputes = list(
        all_member_disputes
        .exclude(status__in=[Dispute.Status.RESOLVED, Dispute.Status.REJECTED, Dispute.Status.REVERSED])
        .order_by("-submitted_at", "dispute_id")[:10]
    )
    dispute_history = list(all_member_disputes.order_by("-submitted_at", "dispute_id")[:10])
    resource_warnings = list(
        Resource.objects.filter(current_stock__lte=F("warning_threshold")).order_by("resource_type", "resource_id")
    )
    visible_tasks = Task.objects.filter(Q(status=Task.Status.OPEN) | Q(assignee_member=member))
    dispute_task_options = list(visible_tasks.order_by("-created_at", "task_id")[:20])
    task_counts = {
        row["status"]: row["count"]
        for row in visible_tasks.values("status").annotate(count=Count("task_id")).order_by("status")
    }
    from core.credit_services import (
        member_available_credit_balance,
        member_credit_balance,
        member_lifetime_contribution,
    )

    credit_balance = member_credit_balance(member)
    available_credit_balance = member_available_credit_balance(member)
    lifetime_contribution = member_lifetime_contribution(member)

    recent_events = []
    for event in Event.objects.order_by("-occurred_at", "event_id")[:50]:
        if member.member_no in event.involved_member_ids:
            recent_events.append(event)
        if len(recent_events) >= 10:
            break
    return {
        "simulation_day": latest.simulation_day if latest else 1,
        "member": member,
        "identity_display": member_identity_display(member),
        "is_governance": member_can_administer(member),
        "is_finance": is_finance_reviewer(member),
        "is_merchant_operator": MerchantProfile.objects.filter(
            operator_member=member,
            merchant_type=MerchantProfile.Type.CASH_SETTLEMENT,
        ).exists(),
        "credit_balance": credit_balance,
        "available_credit_balance": available_credit_balance,
        "lifetime_contribution": lifetime_contribution,
        "available_tasks": available_tasks,
        "active_tasks": active_tasks,
        "recent_ledger_entries": recent_ledger_entries,
        "recent_events": recent_events,
        "open_disputes": open_disputes,
        "dispute_history": dispute_history,
        "resource_warnings": resource_warnings,
        "task_counts": task_counts,
        "dispute_task_options": dispute_task_options,
        "dispute_type_options": [
            {"value": value, "label": label}
            for value, label in Dispute.DisputeType.choices
        ],
        "work_items": _member_work_items(member),
    }


def _member_work_items(member):
    """Lazy import work item builder to avoid circular deps."""
    from .work_item_context import build_member_work_items

    return build_member_work_items(member)


def _application_queryset():
    return MemberApplication.objects.select_related(
        "linked_member",
        "account_user",
        "admission_proposal",
        "decided_by",
    )


def _application_summary(application: MemberApplication) -> dict[str, Any]:
    proposal = application.admission_proposal
    return {
        "application_id": application.application_id,
        "applicant_name": application.applicant_name,
        "role_gap": application.role_gap,
        "role_gap_label": _application_role_gap_label(application),
        "status": application.status,
        "status_label": application.get_status_display(),
        "submitted_at": application.submitted_at,
        "linked_member_no": application.linked_member.member_no if application.linked_member_id else "",
        "admission_proposal_no": proposal.proposal_no if proposal else "",
        "admission_proposal_status": proposal.get_status_display() if proposal else "",
        "admission_proposal_id": proposal.pk if proposal else None,
    }


def applications_review_list_context(*, member: Member, status_filter: str) -> dict[str, Any]:
    """为管理员组装成员报名复核列表。

    ``status_filter`` is one of ``voting`` / ``passed_pending`` / ``admitted`` /
    ``rejected`` / ``all``, derived from the linked admission proposal lifecycle.
    Unknown values fall back to ``voting``.
    """

    if status_filter not in ADMISSION_FILTER_GROUPS:
        status_filter = "voting"
    base_qs = _application_queryset().order_by("-submitted_at", "application_id")
    if status_filter == "voting":
        queryset = base_qs.filter(
            admission_proposal__isnull=False,
            admission_proposal__status=Proposal.Status.VOTING,
        )
    elif status_filter == "passed_pending":
        queryset = base_qs.filter(
            admission_proposal__isnull=False,
            admission_proposal__status=Proposal.Status.PASSED,
        ).exclude(status=MemberApplication.Status.ADMITTED)
    elif status_filter == "admitted":
        queryset = base_qs.filter(status=MemberApplication.Status.ADMITTED)
    elif status_filter == "rejected":
        queryset = base_qs.filter(
            Q(status__in={MemberApplication.Status.REJECTED, MemberApplication.Status.WITHDREW})
            | Q(admission_proposal__isnull=False, admission_proposal__status=Proposal.Status.FAILED)
        )
    else:
        queryset = base_qs
    applications = [_application_summary(app) for app in queryset]
    counts = _admission_filter_counts()
    return {
        "member": member,
        "identity_display": member_identity_display(member),
        "is_governance": member_can_administer(member),
        "is_finance": is_finance_reviewer(member),
        "status_filter": status_filter,
        "applications": applications,
        "counts": counts,
        "filter_labels": ADMISSION_FILTER_LABELS,
        "filter_groups": ADMISSION_FILTER_GROUPS,
    }


def _admission_filter_counts() -> dict[str, int]:
    """Return per-filter-group application counts for the governance review list."""
    base_qs = _application_queryset()
    return {
        "voting": base_qs.filter(
            admission_proposal__isnull=False,
            admission_proposal__status=Proposal.Status.VOTING,
        ).count(),
        "passed_pending": base_qs.filter(
            admission_proposal__isnull=False,
            admission_proposal__status=Proposal.Status.PASSED,
        ).exclude(status=MemberApplication.Status.ADMITTED).count(),
        "admitted": base_qs.filter(status=MemberApplication.Status.ADMITTED).count(),
        "rejected": base_qs.filter(
            Q(status__in={MemberApplication.Status.REJECTED, MemberApplication.Status.WITHDREW})
            | Q(admission_proposal__isnull=False, admission_proposal__status=Proposal.Status.FAILED)
        ).count(),
        "all": base_qs.count(),
    }


def _proposal_view(proposal: Proposal | None, *, viewer: Member) -> dict[str, Any] | None:
    if proposal is None:
        return None
    votes = list(proposal.votes.select_related("voter_member").order_by("-voted_at", "id"))
    result = proposal_result(proposal)
    eligible_ids = {str(item) for item in (proposal.eligible_voters_snapshot_json or [])}
    return {
        "proposal_id": proposal.pk,
        "proposal_no": proposal.proposal_no,
        "status": proposal.status,
        "status_label": proposal.get_status_display(),
        "pass_ratio": proposal.pass_ratio,
        "quorum_count": proposal.quorum_count,
        "deadline_at": proposal.deadline_at,
        "passed_at": proposal.passed_at,
        "executed_at": proposal.executed_at,
        "body": proposal.body,
        "required_yes": result["required_yes"],
        "yes": result["yes"],
        "no": result["no"],
        "abstain": result["abstain"],
        "eligible": result["eligible"],
        "participated": result["participated"],
        "quorum_reached": result["quorum_reached"],
        "passed": result["passed"],
        "votes": [
            {
                "voter_member_no": vote.voter_member.member_no if vote.voter_member_id else "",
                "choice": vote.choice,
                "choice_label": vote.get_choice_display(),
                "reason": vote.reason,
                "voted_at": vote.voted_at,
            }
            for vote in votes
        ],
        "viewer_is_eligible": str(viewer.pk) in eligible_ids,
        "viewer_voted": any(vote.voter_member_id == viewer.pk for vote in votes),
    }


def application_review_detail_context(*, member: Member, application: MemberApplication) -> dict[str, Any]:
    """Assemble the review detail view for one member application.

    No ``review_status_choices`` are exposed — there is no standalone review
    action. Admission is exclusively driven by the linked member_admission
    proposal lifecycle (vote → pass → execute).
    """

    role_motivation_answers = list(application.dynamic_answers or [])
    return {
        "member": member,
        "is_governance": member_can_administer(member),
        "is_finance": is_finance_reviewer(member),
        "application": application,
        "role_gap_label": _application_role_gap_label(application),
        "availability_slots": list(application.availability_slots or []),
        "dynamic_answers": role_motivation_answers,
        "linked_member": application.linked_member,
        "decision_note": (application.metadata or {}).get("decision_note", ""),
        "admission_proposal": _proposal_view(application.admission_proposal, viewer=member),
    }


def workspace_public_profile_context(member: Member) -> dict[str, Any]:
    """Context for the self-service public profile page."""
    from core.models import MemberPublicProfile
    from core.credential_services import credentials_for_member

    profile = MemberPublicProfile.objects.filter(member=member).first()
    avatar_version = (
        str(int(profile.avatar_updated_at.timestamp() * 1_000_000))
        if profile and profile.avatar_updated_at
        else "default"
    )
    return {
        "member": member,
        "identity_display": member_identity_display(member),
        "profile": profile,
        "profile_form": {
            "public_name": profile.public_name if profile else "",
            "has_avatar": bool(profile and profile.avatar_key),
            "avatar_url": f"/u/{member.member_no}/avatar/?v={avatar_version}",
        },
        "observer_profile_url": f"/u/{member.member_no}/",
        "credentials": credentials_for_member(member),
    }
