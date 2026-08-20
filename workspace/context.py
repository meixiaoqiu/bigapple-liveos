"""Workspace query assembly.

This module stays HTTP-free so API views and member-facing pages can share the
same member-centered read model without putting portal presentation queries in
the core rules engine.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404

from core.access import is_finance_reviewer, member_can_administer
from core.authorization_services import AuthorizationService
from core.application_services import _application_role_gap_label
from core.identity_display import member_identity_display
from core.governance_setup import DELIBERATOR_EXAM_MANAGE_PERMISSION
from core.models import (
    CapacityAssessment,
    EventFeedback,
    LedgerEntry,
    Member,
    MemberApplication,
    MerchantProfile,
    Task,
)


ADMISSION_FILTER_GROUPS = ("pending", "admitted", "rejected", "all")

ADMISSION_FILTER_LABELS: dict[str, str] = {
    "pending": "待决议",
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
        MemberApplication.objects.select_related("admission_proposal").filter(linked_member=member)
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
        "admission_proposal": (
            latest_application.admission_proposal
            if latest_application and latest_application.admission_proposal_id
            else None
        ),
    }


def workspace_context(member_no: str) -> dict[str, Any]:
    member = get_object_or_404(Member, member_no=member_no)
    latest = CapacityAssessment.objects.order_by("-simulation_day", "-created_at").first()
    recent_ledger_entries = list(
        LedgerEntry.objects.filter(member=member).order_by("-system_event__seq", "-created_at", "ledger_entry_id")[:10]
    )
    all_member_feedbacks = EventFeedback.objects.filter(
        Q(submitted_by=member) | Q(subject_member=member) | Q(assigned_handler=member)
    ).select_related("related_event", "submitted_by", "subject_member", "assigned_handler", "concluded_by")
    open_feedbacks = list(all_member_feedbacks.exclude(
        status__in=[EventFeedback.Status.CLOSED, EventFeedback.Status.WITHDRAWN]
    ).order_by("-submitted_at", "feedback_id")[:10])
    feedback_history = list(all_member_feedbacks.order_by("-submitted_at", "feedback_id")[:10])
    visible_tasks = Task.objects.filter(Q(status=Task.Status.OPEN) | Q(assignee_member=member))
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

    return {
        "simulation_day": latest.simulation_day if latest else 1,
        "member": member,
        "identity_display": member_identity_display(member),
        "is_governance": member_can_administer(member),
        "can_manage_deliberator_exam": AuthorizationService().member_has_permission(
            member, DELIBERATOR_EXAM_MANAGE_PERMISSION,
        ),
        "is_finance": is_finance_reviewer(member),
        "is_merchant_operator": MerchantProfile.objects.filter(
            operator_member=member,
            merchant_type=MerchantProfile.Type.CASH_SETTLEMENT,
        ).exists(),
        "credit_balance": credit_balance,
        "available_credit_balance": available_credit_balance,
        "lifetime_contribution": lifetime_contribution,
        "recent_ledger_entries": recent_ledger_entries,
        "open_feedbacks": open_feedbacks,
        "feedback_history": feedback_history,
        "task_counts": task_counts,
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
        "decided_by",
        "admission_proposal",
    )


def _application_summary(application: MemberApplication) -> dict[str, Any]:
    return {
        "application_id": application.application_id,
        "applicant_name": application.applicant_name,
        "role_gap": application.role_gap,
        "role_gap_label": _application_role_gap_label(application),
        "status": application.status,
        "status_label": application.get_status_display(),
        "submitted_at": application.submitted_at,
        "linked_member_no": application.linked_member.member_no if application.linked_member_id else "",
        "proposal_status": application.admission_proposal.status if application.admission_proposal_id else "",
        "proposal_status_label": (
            application.admission_proposal.get_status_display() if application.admission_proposal_id else "尚未建立"
        ),
    }


def applications_review_list_context(*, member: Member, status_filter: str) -> dict[str, Any]:
    """为管理员组装成员报名复核列表。

    尚未形成终态的准入决策统一归入 ``pending``；未知筛选回退到该分组。
    """

    if status_filter not in ADMISSION_FILTER_GROUPS:
        status_filter = "pending"
    base_qs = _application_queryset().order_by("-submitted_at", "application_id")
    if status_filter == "pending":
        queryset = base_qs.filter(status=MemberApplication.Status.SUBMITTED)
    elif status_filter == "admitted":
        queryset = base_qs.filter(status=MemberApplication.Status.ADMITTED)
    elif status_filter == "rejected":
        queryset = base_qs.filter(status__in={MemberApplication.Status.REJECTED, MemberApplication.Status.WITHDREW})
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
        "pending": base_qs.filter(
            status=MemberApplication.Status.SUBMITTED,
        ).count(),
        "admitted": base_qs.filter(status=MemberApplication.Status.ADMITTED).count(),
        "rejected": base_qs.filter(status__in={MemberApplication.Status.REJECTED, MemberApplication.Status.WITHDREW}).count(),
        "all": base_qs.count(),
    }


def application_review_detail_context(*, member: Member, application: MemberApplication) -> dict[str, Any]:
    """组装管理员可见的报名资料和统一准入提案状态。"""

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
        "admission_proposal": application.admission_proposal if application.admission_proposal_id else None,
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
