"""Member-facing self-service workspace views."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST

from live_os.access import (
    is_authenticated,
    member_for_request,
    page_forbidden,
    world_login_url_for_request,
)
from core.access import is_governance_principal
from core.dispute_services import submit_dispute
from core.exceptions import DomainError
from core.models import Member, MemberApplication, Proposal, ProposalVote, Task
from core.proposals.execution import execute_proposal
from core.proposals.voting import cast_proposal_vote
from core.tasks.member_workflow import claim_task, submit_labor
from worlds.routing import world_redirect

from .context import (
    applicant_workspace_context,
    application_review_detail_context,
    applications_review_list_context,
    member_has_full_workspace_access,
    workspace_context,
)


PROPOSAL_VOTE_CHOICES = {
    ProposalVote.Choice.YES,
    ProposalVote.Choice.NO,
}


@require_GET
def workspace_public_profile_page(request: HttpRequest):
    member = current_member_or_forbidden(request)
    if isinstance(member, HttpResponseForbidden):
        return member
    from .context import workspace_public_profile_context
    return render(request, "workspace/profile.html", workspace_public_profile_context(member))


@require_POST
def workspace_public_profile_update(request: HttpRequest):
    member = current_member_or_forbidden(request)
    if isinstance(member, HttpResponseForbidden):
        return member
    public_name = request.POST.get("public_name", "").strip()
    avatar_url = request.POST.get("avatar_url", "").strip()
    try:
        from core.member_profile_services import update_member_public_profile
        update_member_public_profile(member=member, public_name=public_name, avatar_url=avatar_url)
        messages.success(request, "公开资料已更新。")
    except DjangoValidationError as exc:
        messages.error(request, f"保存失败：{exc}")
    except DomainError as exc:
        messages.error(request, f"保存失败：{exc}")
    return world_redirect(request, "workspace-public-profile")


def parse_evidence_refs(raw_value: str) -> list[str]:
    """Parse form evidence refs while keeping the API contract as a list."""

    normalized = raw_value.replace(",", "\n")
    return [line.strip() for line in normalized.splitlines() if line.strip()]


def current_member_or_forbidden(request: HttpRequest) -> Member | HttpResponseForbidden:
    member = member_for_request(request)
    if member is None:
        return page_forbidden("需要登录并绑定成员身份。")
    return member


def current_full_member_or_forbidden(request: HttpRequest) -> Member | HttpResponseForbidden:
    member = current_member_or_forbidden(request)
    if isinstance(member, HttpResponseForbidden):
        return member
    if not member_has_full_workspace_access(member):
        return page_forbidden("报名审核完成前不能执行该操作。")
    return member


@require_GET
def workspace_page(request: HttpRequest):
    member = current_member_or_forbidden(request)
    if isinstance(member, HttpResponseForbidden):
        return member
    if not member_has_full_workspace_access(member):
        return render(request, "workspace/applicant.html", applicant_workspace_context(member.member_no))
    return render(request, "workspace/index.html", workspace_context(member.member_no))


@require_POST
def workspace_claim_task(request: HttpRequest, task_id: str):
    member = current_full_member_or_forbidden(request)
    if isinstance(member, HttpResponseForbidden):
        return member
    task = get_object_or_404(Task, task_id=task_id)
    try:
        claim_task(task=task, member=member)
    except DomainError as exc:
        messages.error(request, f"领取失败：{exc}")
    else:
        messages.success(request, f"已领取任务：{task.title}")
    return world_redirect(request, "workspace-page")


@require_POST
def workspace_submit_labor(request: HttpRequest, task_id: str):
    member = current_full_member_or_forbidden(request)
    if isinstance(member, HttpResponseForbidden):
        return member
    task = get_object_or_404(Task, task_id=task_id)
    labor_note = request.POST.get("labor_note", "").strip()
    evidence_refs = parse_evidence_refs(request.POST.get("evidence_refs", ""))
    if not labor_note:
        messages.error(request, "提交失败：劳动说明不能为空。")
        return world_redirect(request, "workspace-page")
    try:
        submit_labor(
            task=task,
            member=member,
            labor_note=labor_note,
            evidence_refs=evidence_refs,
        )
    except DomainError as exc:
        messages.error(request, f"提交失败：{exc}")
    else:
        messages.success(request, f"已提交劳动记录：{task.title}")
    return world_redirect(request, "workspace-page")


@require_POST
def workspace_create_dispute(request: HttpRequest):
    member = current_full_member_or_forbidden(request)
    if isinstance(member, HttpResponseForbidden):
        return member
    dispute_type = request.POST.get("dispute_type", "")
    facts = request.POST.get("facts", "")
    evidence_refs = parse_evidence_refs(request.POST.get("evidence_refs", ""))
    related_task = None
    related_task_id = request.POST.get("related_task_id", "").strip()
    if related_task_id:
        related_task = (
            Task.objects.filter(task_id=related_task_id)
            .filter(Q(status=Task.Status.OPEN) | Q(assignee_member=member))
            .first()
        )
        if related_task is None:
            messages.error(request, "提交失败：关联任务不在当前成员可见范围内。")
            return world_redirect(request, "workspace-page")
    try:
        dispute = submit_dispute(
            claimant=member,
            dispute_type=dispute_type,
            facts=facts,
            evidence_refs=evidence_refs,
            related_task=related_task,
        )
    except DomainError as exc:
        messages.error(request, f"提交失败：{exc}")
    else:
        messages.success(request, f"已提交申诉：{dispute.dispute_id}")
    return world_redirect(request, "workspace-page")


# --- Member-application review module -------------------------------------------------
# Governance-only surface that exposes the application list and the
# proposal/voting/execution pipeline through the workspace. Views stay thin:
# every state change goes through the service layer so the invariants around
# proposal-driven admission are preserved.
#
# There is NO standalone "review" POST endpoint — admission is governed
# exclusively through the member_admission proposal lifecycle (vote → pass →
# execute). Applications are auto-rejected when their admission proposal fails.


def current_governance_member_or_forbidden(request: HttpRequest) -> Member | HttpResponse:
    """Resolve the governance viewer for a review action.

    Requires an authenticated, governance-permissioned Member. A Django
    staff/superuser without a bound Member is NOT allowed through — they cannot
    act as proposer/reviewer/voter without a member identity.
    """

    if not is_authenticated(request):
        return redirect_to_login(request.get_full_path(), login_url=world_login_url_for_request(request))
    member = member_for_request(request)
    if member is None:
        return page_forbidden("需要登录并绑定成员身份。")
    if not is_governance_principal(member):
        return page_forbidden("需要治理成员权限。")
    return member


def _application_for_review(application_id: str) -> MemberApplication:
    return get_object_or_404(
        MemberApplication.objects.select_related("linked_member", "account_user", "admission_proposal", "decided_by"),
        application_id=application_id,
    )


def _member_admission_proposal_and_application_or_404(proposal_id: str) -> tuple[Proposal, MemberApplication]:
    """Return ``(proposal, application)`` where proposal is an active member-admission
    proposal linked to the application, or raise Http404.

    This is the ONLY helper the vote / execute views may use — they must not look
    up arbitrary proposals by pk.  If the proposal is not ``MEMBER_ADMISSION`` or
    no ``MemberApplication`` references it, the call site gets a 404.
    """

    proposal = get_object_or_404(Proposal, pk=proposal_id)
    if proposal.proposal_type != Proposal.ProposalType.MEMBER_ADMISSION:
        from django.http import Http404

        raise Http404("不是成员准入提案。")
    application = MemberApplication.objects.filter(admission_proposal_id=proposal.pk).first()
    if application is None:
        from django.http import Http404

        raise Http404("成员准入提案未关联报名记录。")
    return proposal, application


def _admission_application_redirect(request: HttpRequest, application: MemberApplication):
    """Redirect to the review detail page for the given application."""

    return world_redirect(request, "workspace-application-detail", application.application_id)


@require_GET
def workspace_applications_review(request: HttpRequest):
    member = current_governance_member_or_forbidden(request)
    if isinstance(member, HttpResponse):
        return member
    status_filter = str(request.GET.get("status", "pending")).strip() or "pending"
    return render(
        request,
        "workspace/applications_review_list.html",
        applications_review_list_context(member=member, status_filter=status_filter),
    )


@require_GET
def workspace_application_detail(request: HttpRequest, application_id: str):
    member = current_governance_member_or_forbidden(request)
    if isinstance(member, HttpResponse):
        return member
    application = _application_for_review(application_id)
    return render(
        request,
        "workspace/applications_review_detail.html",
        application_review_detail_context(member=member, application=application),
    )


@require_POST
def workspace_proposal_vote(request: HttpRequest, proposal_id: str):
    member = current_governance_member_or_forbidden(request)
    if isinstance(member, HttpResponse):
        return member
    proposal, application = _member_admission_proposal_and_application_or_404(proposal_id)
    choice = str(request.POST.get("choice", "")).strip()
    reason = str(request.POST.get("reason", "")).strip()
    if choice not in PROPOSAL_VOTE_CHOICES:
        messages.error(request, "投票选项无效。")
        return _admission_application_redirect(request, application)
    if choice == ProposalVote.Choice.NO and not reason:
        messages.error(request, "反对准入必须填写理由。")
        return _admission_application_redirect(request, application)
    try:
        cast_proposal_vote(
            proposal=proposal,
            voter_member=member,
            choice=choice,
            reason=reason,
        )
    except (DomainError, DjangoValidationError) as exc:
        messages.error(request, f"投票失败：{exc}")
    else:
        messages.success(request, "已记录投票。")
    return _admission_application_redirect(request, application)


@require_POST
def workspace_proposal_execute(request: HttpRequest, proposal_id: str):
    member = current_governance_member_or_forbidden(request)
    if isinstance(member, HttpResponse):
        return member
    proposal, application = _member_admission_proposal_and_application_or_404(proposal_id)
    try:
        execute_proposal(proposal=proposal, executor_member=member)
    except (DomainError, DjangoValidationError) as exc:
        messages.error(request, f"执行准入提案失败：{exc}")
    else:
        messages.success(request, "准入提案已执行，成员已接纳。")
    return _admission_application_redirect(request, application)


# Removed _redirect_to_proposal_application (no longer needed — the only valid
# return from this module is the application detail page).
