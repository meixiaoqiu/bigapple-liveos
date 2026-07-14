"""Workspace query assembly.

This module stays HTTP-free so API views and member-facing pages can share the
same member-centered read model without putting portal presentation queries in
the core rules engine.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Count, F, Q, Sum
from django.shortcuts import get_object_or_404

from core.access import is_governance_principal
from core.models import (
    CapacityAssessment,
    Dispute,
    Event,
    LedgerEntry,
    Member,
    MemberApplication,
    Proposal,
    ProposalVote,
    Resource,
    Task,
)
from core.proposals.voting import proposal_result


NEXT_ACTION_LABELS = {
    "claim_task": "领取开放任务",
    "submit_labor": "提交劳动记录",
    "wait_for_review": "等待验收结果",
    "review_dispute": "查看申诉进展",
    "check_resource_warning": "关注资源预警",
    "no_action": "暂无待处理动作",
}

FULL_WORKSPACE_MEMBER_STATUSES = {Member.Status.ACTIVE, Member.Status.ADMITTED}

# Statuses that are still in the review funnel (not yet decided). Everything
# else (admitted/rejected/withdrew) is considered "processed".
PENDING_APPLICATION_STATUSES = {
    MemberApplication.Status.SUBMITTED,
    MemberApplication.Status.UNDER_REVIEW,
    MemberApplication.Status.CANDIDATE,
    MemberApplication.Status.STANDBY,
}
PROCESSED_APPLICATION_STATUSES = {
    MemberApplication.Status.ADMITTED,
    MemberApplication.Status.REJECTED,
    MemberApplication.Status.WITHDREW,
}
APPLICATION_FILTER_GROUPS = ("pending", "processed", "all")


def member_has_full_workspace_access(member: Member) -> bool:
    return member.status in FULL_WORKSPACE_MEMBER_STATUSES


def applicant_workspace_context(member_no: str) -> dict[str, Any]:
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
    return {
        "member": member,
        "application": latest_application,
        "can_reapply": can_reapply,
    }


def workspace_next_actions(
    *,
    available_tasks: list[Task],
    active_tasks: list[Task],
    open_disputes: list[Dispute],
    resource_warnings: list[Resource],
) -> list[str]:
    actions = []
    if any(task.status in {Task.Status.CLAIMED, Task.Status.IN_PROGRESS} for task in active_tasks):
        actions.append("submit_labor")
    if any(task.status == Task.Status.PENDING_REVIEW for task in active_tasks):
        actions.append("wait_for_review")
    if available_tasks:
        actions.append("claim_task")
    if open_disputes:
        actions.append("review_dispute")
    if resource_warnings:
        actions.append("check_resource_warning")
    return actions or ["no_action"]


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
    task_history_statuses = [
        Task.Status.ACCEPTED,
        Task.Status.REJECTED,
        Task.Status.REVERSED,
    ]
    task_history = list(
        Task.objects.filter(assignee_member=member, status__in=task_history_statuses)
        .order_by("-reviewed_at", "-submitted_at", "-created_at", "task_id")[:10]
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
    credit_balance = (
        LedgerEntry.objects.filter(member=member, status=LedgerEntry.Status.POSTED).aggregate(total=Sum("amount"))[
            "total"
        ]
        or 0
    )

    recent_events = []
    for event in Event.objects.order_by("-occurred_at", "event_id")[:50]:
        if member.member_no in event.involved_member_ids:
            recent_events.append(event)
        if len(recent_events) >= 10:
            break
    next_actions = workspace_next_actions(
        available_tasks=available_tasks,
        active_tasks=active_tasks,
        open_disputes=open_disputes,
        resource_warnings=resource_warnings,
    )
    return {
        "simulation_day": latest.simulation_day if latest else 1,
        "member": member,
        "is_governance": is_governance_principal(member),
        "credit_balance": credit_balance,
        "available_tasks": available_tasks,
        "active_tasks": active_tasks,
        "task_history": task_history,
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
        "next_actions": next_actions,
        "next_action_rows": [
            {"value": action, "label": NEXT_ACTION_LABELS[action]}
            for action in next_actions
        ],
    }


ROLE_GAP_LABELS = {
    "settled_resident": "安居成员",
    "service_resident": "生活服务成员",
    "developer_ai_engineer": "系统开发与 AI 工程",
    "community_contributor": "社区贡献者",
}


def _application_queryset():
    return MemberApplication.objects.select_related(
        "linked_member",
        "account_user",
        "admission_proposal",
        "reviewed_by",
    )


def _application_summary(application: MemberApplication) -> dict[str, Any]:
    proposal = application.admission_proposal
    return {
        "application_id": application.application_id,
        "applicant_name": application.applicant_name,
        "role_gap": application.role_gap,
        "role_gap_label": ROLE_GAP_LABELS.get(application.role_gap, application.role_gap or "未记录"),
        "status": application.status,
        "status_label": application.get_status_display(),
        "submitted_at": application.submitted_at,
        "linked_member_no": application.linked_member.member_no if application.linked_member_id else "",
        "admission_proposal_no": proposal.proposal_no if proposal else "",
        "admission_proposal_status": proposal.get_status_display() if proposal else "",
        "admission_proposal_id": proposal.pk if proposal else None,
    }


def applications_review_list_context(*, member: Member, status_filter: str) -> dict[str, Any]:
    """Assemble the member-application review list for governance members.

    ``status_filter`` is one of ``pending`` / ``processed`` / ``all``; unknown
    values fall back to ``pending`` so the landing view always shows actionable
    rows.
    """

    if status_filter not in APPLICATION_FILTER_GROUPS:
        status_filter = "pending"
    queryset = _application_queryset().order_by("-submitted_at", "application_id")
    if status_filter == "pending":
        queryset = queryset.filter(status__in=PENDING_APPLICATION_STATUSES)
    elif status_filter == "processed":
        queryset = queryset.filter(status__in=PROCESSED_APPLICATION_STATUSES)
    applications = [_application_summary(app) for app in queryset]
    counts = {
        "pending": _application_queryset().filter(status__in=PENDING_APPLICATION_STATUSES).count(),
        "processed": _application_queryset().filter(status__in=PROCESSED_APPLICATION_STATUSES).count(),
        "all": _application_queryset().count(),
    }
    return {
        "member": member,
        "is_governance": is_governance_principal(member),
        "status_filter": status_filter,
        "applications": applications,
        "counts": counts,
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
    """Assemble the review detail view for one member application."""

    role_motivation_answers = list(application.dynamic_answers or [])
    return {
        "member": member,
        "is_governance": is_governance_principal(member),
        "application": application,
        "role_gap_label": ROLE_GAP_LABELS.get(application.role_gap, application.role_gap or "未记录"),
        "availability_slots": list(application.availability_slots or []),
        "dynamic_answers": role_motivation_answers,
        "linked_member": application.linked_member,
        "review_note": (application.metadata or {}).get("review_note", ""),
        "admission_proposal": _proposal_view(application.admission_proposal, viewer=member),
        "review_status_choices": [
            {"value": MemberApplication.Status.UNDER_REVIEW, "label": "标记审核中"},
            {"value": MemberApplication.Status.CANDIDATE, "label": "标记候选"},
            {"value": MemberApplication.Status.STANDBY, "label": "标记备用"},
            {"value": MemberApplication.Status.REJECTED, "label": "拒绝报名"},
        ],
    }
