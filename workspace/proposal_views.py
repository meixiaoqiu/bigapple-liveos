"""Workspace views for unified ApprovalProposal management."""

from __future__ import annotations

from django.contrib import messages
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_http_methods

from worlds.routing import world_redirect

from core.access import is_finance_reviewer, is_governance_principal
from core.exceptions import DomainError
from core.models import ApprovalProposal, ApprovalDecision, Member, SupplierQuote
from core.proposal_services import (
    approve_proposal,
    execute_proposal,
    member_available_approval_roles,
    proposal_approved_roles,
    proposal_is_actionable_by,
    proposal_is_executable_by,
    proposal_missing_roles,
    proposal_required_roles,
    proposal_target_url,
    reject_proposal,
)
from live_os.access import member_for_request

from .context import member_has_full_workspace_access


def _check_member(request: HttpRequest) -> Member | None:
    member = member_for_request(request)
    if member is None:
        return None
    if not member_has_full_workspace_access(member):
        return None
    return member


def _governance_or_finance_or_forbidden(member: Member) -> bool:
    if is_governance_principal(member):
        return False
    if is_finance_reviewer(member):
        return False
    return True


def _proposal_display(proposal: ApprovalProposal, member: Member) -> dict:
    """Build a template-safe dict for one proposal."""
    return {
        "proposal_id": proposal.proposal_id,
        "proposal_type": proposal.proposal_type,
        "proposal_type_label": proposal.get_proposal_type_display(),
        "title": proposal.title,
        "summary": proposal.summary,
        "status": proposal.status,
        "status_label": proposal.get_status_display(),
        "approval_tier": proposal.approval_tier,
        "approval_tier_label": proposal.get_approval_tier_display(),
        "required_roles": proposal_required_roles(proposal),
        "approved_roles": proposal_approved_roles(proposal),
        "missing_roles": proposal_missing_roles(proposal),
        "submitted_by_display": proposal.submitted_by.display_name or proposal.submitted_by.member_no,
        "submitted_at": proposal.submitted_at,
        "target_url": proposal_target_url(proposal),
        "is_actionable": proposal_is_actionable_by(member, proposal),
        "is_executable": proposal_is_executable_by(member, proposal),
        "available_roles": member_available_approval_roles(member, proposal),
    }


@require_GET
def proposal_list(request: HttpRequest) -> HttpResponse:
    member = _check_member(request)
    if member is None:
        return render(request, "workspace/login_required.html", status=403)
    if _governance_or_finance_or_forbidden(member):
        return render(request, "workspace/login_required.html", status=403)

    all_proposals = list(
        ApprovalProposal.objects.select_related("submitted_by")
        .order_by("-submitted_at")
    )

    # Partition
    awaiting_action = [
        p for p in all_proposals
        if p.status == ApprovalProposal.Status.SUBMITTED
        and proposal_is_actionable_by(member, p)
    ]
    awaiting_execute = [
        p for p in all_proposals
        if p.status == ApprovalProposal.Status.APPROVED
        and proposal_is_executable_by(member, p)
    ]
    recent = all_proposals[:20]

    dispatched = [
        _proposal_display(p, member) for p in awaiting_action
    ]
    executable = [
        _proposal_display(p, member) for p in awaiting_execute
    ]
    recent_displays = [
        _proposal_display(p, member) for p in recent
    ]

    return render(
        request,
        "workspace/proposal_list.html",
        {
            "member": member,
            "pending_count": len(awaiting_action),
            "execute_count": len(awaiting_execute),
            "dispatched": dispatched,
            "executable": executable,
            "recent": recent_displays,
            "is_governance": is_governance_principal(member),
            "is_finance": is_finance_reviewer(member),
        },
    )


@require_http_methods(["POST"])
def approval_proposal_approve(request: HttpRequest, proposal_id: str) -> HttpResponse:
    member = _check_member(request)
    if member is None:
        return render(request, "workspace/login_required.html", status=403)
    if _governance_or_finance_or_forbidden(member):
        return render(request, "workspace/login_required.html", status=403)

    proposal = get_object_or_404(ApprovalProposal, proposal_id=proposal_id)
    available = member_available_approval_roles(member, proposal)

    if not available:
        messages.error(request, "你没有可用的审批角色，或已审批过该提案。")
        return world_redirect(request, "workspace-approval-proposals")

    role = available[0]
    reason = request.POST.get("reason", "").strip()

    try:
        approve_proposal(proposal=proposal, approved_by=member, role=role, reason=reason)
        missing = proposal_missing_roles(proposal)
        if missing:
            messages.success(request, f"提案 {proposal_id} {role} 审批通过，尚缺：{'、'.join(missing)}。")
        else:
            messages.success(request, f"提案 {proposal_id} 审批通过，可执行。")
    except DomainError as exc:
        messages.error(request, str(exc))

    return world_redirect(request, "workspace-approval-proposals")


@require_http_methods(["POST"])
def approval_proposal_reject(request: HttpRequest, proposal_id: str) -> HttpResponse:
    member = _check_member(request)
    if member is None:
        return render(request, "workspace/login_required.html", status=403)
    if _governance_or_finance_or_forbidden(member):
        return render(request, "workspace/login_required.html", status=403)

    proposal = get_object_or_404(ApprovalProposal, proposal_id=proposal_id)
    available = member_available_approval_roles(member, proposal)

    if not available:
        messages.error(request, "你没有可用的审批角色。")
        return world_redirect(request, "workspace-approval-proposals")

    role = available[0]
    reason = request.POST.get("reason", "").strip()

    try:
        reject_proposal(proposal=proposal, rejected_by=member, role=role, reason=reason)
        messages.success(request, f"提案 {proposal_id} 已拒绝。")
    except DomainError as exc:
        messages.error(request, str(exc))

    return world_redirect(request, "workspace-approval-proposals")


@require_http_methods(["POST"])
def approval_proposal_execute(request: HttpRequest, proposal_id: str) -> HttpResponse:
    member = _check_member(request)
    if member is None:
        return render(request, "workspace/login_required.html", status=403)
    if _governance_or_finance_or_forbidden(member):
        return render(request, "workspace/login_required.html", status=403)

    proposal = get_object_or_404(ApprovalProposal, proposal_id=proposal_id)

    try:
        execute_proposal(proposal=proposal, actor=member)
        messages.success(request, f"提案 {proposal_id} 已执行。")
    except DomainError as exc:
        messages.error(request, str(exc))

    return world_redirect(request, "workspace-approval-proposals")
