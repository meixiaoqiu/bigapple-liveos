"""Member workspace for governed finance-reviewer appointments."""

from __future__ import annotations

from django.contrib import messages
from django.http import HttpRequest, HttpResponseForbidden
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from core.finance_role_services import (
    finance_review_role,
    member_can_manage_finance_roles,
)
from core.finance_setup import FINANCE_REVIEW_PERMISSION
from core.models import Member
from core.proposal_migration import PROPOSAL_FLOW_UNAVAILABLE_MESSAGE
from core.permission_services import members_with_permission
from live_os.access import page_forbidden
from worlds.routing import world_redirect

from .access import require_full_workspace_member


def _member_or_forbidden(request: HttpRequest) -> Member | HttpResponseForbidden:
    return require_full_workspace_member(request)


def _appointment_context(member: Member) -> dict:
    role = finance_review_role()
    can_manage = member_can_manage_finance_roles(member)
    reviewers = members_with_permission(FINANCE_REVIEW_PERMISSION).order_by("member_no")
    return {
        "member": member,
        "can_manage": can_manage,
        "proposals": [],
        "reviewers": reviewers,
        "proposal_flow_unavailable_message": PROPOSAL_FLOW_UNAVAILABLE_MESSAGE,
    }


@require_http_methods(["GET", "POST"])
def finance_reviewer_appointments(request: HttpRequest):
    member = _member_or_forbidden(request)
    if isinstance(member, HttpResponseForbidden):
        return member

    if request.method == "POST":
        messages.error(request, PROPOSAL_FLOW_UNAVAILABLE_MESSAGE)
        return world_redirect(request, "workspace-finance-reviewer-appointments")

    context = _appointment_context(member)
    if not context["can_manage"]:
        return page_forbidden("当前没有财务职责任命管理或表决权限。")
    return render(request, "workspace/finance_reviewer_appointments.html", context)
