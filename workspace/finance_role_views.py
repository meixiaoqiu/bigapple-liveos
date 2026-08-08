"""Member workspace for governed finance-reviewer appointments."""

from __future__ import annotations

from django.contrib import messages
from django.http import HttpRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods

from core.exceptions import DomainError
from core.finance_role_services import (
    execute_finance_reviewer_appointment,
    finance_review_appointment_proposals,
    finance_review_role,
    member_can_manage_finance_roles,
    nominate_finance_reviewer,
    vote_on_finance_reviewer_appointment,
)
from core.finance_setup import FINANCE_REVIEW_PERMISSION
from core.member_roles import ROLE_COVENANTER, member_has_role
from core.models import Member, Proposal, ProposalVote
from core.permission_services import members_with_permission
from live_os.access import page_forbidden
from worlds.routing import world_redirect

from .access import require_full_workspace_member


def _member_or_forbidden(request: HttpRequest) -> Member | HttpResponseForbidden:
    return require_full_workspace_member(request)


def _finance_proposal_or_404(proposal_id: str) -> Proposal:
    proposal = get_object_or_404(Proposal, pk=proposal_id)
    # The domain service performs the authoritative role/type validation.
    return proposal


def _appointment_context(member: Member) -> dict:
    role = finance_review_role()
    can_manage = member_can_manage_finance_roles(member)
    candidates = []
    reviewers = members_with_permission(FINANCE_REVIEW_PERMISSION).order_by("member_no")
    if can_manage:
        reviewer_ids = set(reviewers.values_list("pk", flat=True))
        candidates = [
            candidate
            for candidate in Member.objects.select_related("user").order_by("member_no")
            if member_has_role(candidate, ROLE_COVENANTER)
            and candidate.pk not in reviewer_ids
        ]
    proposals = []
    for proposal in finance_review_appointment_proposals().select_related("proposer_member"):
        payload = proposal.payload_json or {}
        proposals.append({
            "proposal": proposal,
            "target_name": payload.get("target_member_display_name") or payload.get("target_member_no") or "未知成员",
            "can_vote": str(member.pk) in {str(item) for item in (proposal.eligible_voters_snapshot_json or [])}
            and proposal.status == Proposal.Status.VOTING,
            "can_execute": can_manage and proposal.status == Proposal.Status.PASSED,
        })
    return {
        "member": member,
        "can_manage": can_manage,
        "candidates": candidates,
        "proposals": proposals,
        "reviewers": reviewers,
        "vote_choices": ProposalVote.Choice,
    }


@require_http_methods(["GET", "POST"])
def finance_reviewer_appointments(request: HttpRequest):
    member = _member_or_forbidden(request)
    if isinstance(member, HttpResponseForbidden):
        return member

    if request.method == "POST":
        action = str(request.POST.get("action", "")).strip()
        try:
            if action == "nominate":
                target = get_object_or_404(Member, pk=request.POST.get("target_member_id"))
                proposal = nominate_finance_reviewer(
                    actor=member,
                    target_member=target,
                    reason=str(request.POST.get("reason", "")),
                )
                messages.success(request, f"已创建财务审核职责任命提案：{proposal.title}")
            elif action == "vote":
                proposal = _finance_proposal_or_404(str(request.POST.get("proposal_id", "")))
                vote_on_finance_reviewer_appointment(
                    actor=member,
                    proposal=proposal,
                    choice=str(request.POST.get("choice", "")),
                    reason=str(request.POST.get("reason", "")),
                )
                messages.success(request, "已记录财务审核职责任命表决。")
            elif action == "execute":
                proposal = _finance_proposal_or_404(str(request.POST.get("proposal_id", "")))
                execute_finance_reviewer_appointment(actor=member, proposal=proposal)
                messages.success(request, "财务审核职责任命已执行。")
            else:
                raise DomainError("未知的财务职责任命操作。")
        except DomainError as exc:
            messages.error(request, str(exc))
        return world_redirect(request, "workspace-finance-reviewer-appointments")

    context = _appointment_context(member)
    if not context["can_manage"] and not any(item["can_vote"] for item in context["proposals"]):
        return page_forbidden("当前没有财务职责任命管理或表决权限。")
    return render(request, "workspace/finance_reviewer_appointments.html", context)
