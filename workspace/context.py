"""Workspace query assembly.

This module stays HTTP-free so API views and member-facing pages can share the
same member-centered read model without putting portal presentation queries in
the core rules engine.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Count, F, Q, Sum
from django.shortcuts import get_object_or_404

from core.models import CapacityAssessment, Dispute, Event, LedgerEntry, Member, Resource, Task


NEXT_ACTION_LABELS = {
    "claim_task": "领取开放任务",
    "submit_labor": "提交劳动记录",
    "wait_for_review": "等待验收结果",
    "review_dispute": "查看申诉进展",
    "check_resource_warning": "关注资源预警",
    "no_action": "暂无待处理动作",
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
