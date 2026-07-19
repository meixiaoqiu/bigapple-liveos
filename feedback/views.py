"""Community feedback views."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.access import is_governance_principal
from core.exceptions import DomainError
from core.feedback_services import (
    hide_feedback,
    link_feedback_to_proposal,
    respond_to_feedback,
    submit_feedback,
)
from core.identity_services import ensure_basic_member_for_user
from core.models import CommunityFeedback, Member, Proposal
from live_os.access import is_authenticated, member_for_request
from observer.member_profiles import public_member_identity as _identity

from .forms import FeedbackForm, FeedbackResponseForm


@require_GET
def feedback_list(request: HttpRequest) -> HttpResponse:
    feedbacks = CommunityFeedback.objects.exclude(
        status=CommunityFeedback.Status.HIDDEN
    ).select_related("author_member", "responded_by").order_by("-created_at", "-id")[:50]
    return render(request, "feedback/list.html", {"feedbacks": feedbacks})


@require_http_methods(["GET", "POST"])
def feedback_create(request: HttpRequest) -> HttpResponse:
    if not is_authenticated(request):
        return redirect_to_login("/feedback/new/", login_url="/login/")

    member = member_for_request(request)
    if member is None:
        member = ensure_basic_member_for_user(request.user)

    if member.status in {Member.Status.SUSPENDED, Member.Status.EXITED}:
        return HttpResponseForbidden("你的成员状态已停用，不能提交反馈。")

    if request.method == "POST":
        form = FeedbackForm(request.POST)
        if form.is_valid():
            try:
                feedback = submit_feedback(
                    author_member=member,
                    title=form.cleaned_data["title"],
                    category=form.cleaned_data["category"],
                    body=form.cleaned_data["body"],
                )
            except DomainError as exc:
                messages.error(request, f"提交失败：{exc}")
            else:
                messages.success(request, "反馈已提交。")
                return redirect("feedback-detail", feedback_id=feedback.feedback_id)
    else:
        form = FeedbackForm()

    return render(request, "feedback/form.html", {"form": form})


@require_GET
def feedback_detail(request: HttpRequest, feedback_id: str) -> HttpResponse:
    feedback = get_object_or_404(
        CommunityFeedback.objects.select_related(
            "author_member", "responded_by", "linked_proposal",
        ),
        feedback_id=feedback_id,
    )
    if feedback.status == CommunityFeedback.Status.HIDDEN:
        # Only governance members can view hidden feedback.
        member = member_for_request(request)
        if member is None or not is_governance_principal(member):
            raise Http404("反馈不存在。")

    is_gov = False
    member = member_for_request(request)
    if member is not None and is_governance_principal(member):
        is_gov = True

    return render(request, "feedback/detail.html", {
        "feedback": feedback,
        "is_gov": is_gov,
        "response_form": FeedbackResponseForm() if is_gov else None,
        "author_identity": _identity(feedback.author_member),
    })


@require_POST
def feedback_respond(request: HttpRequest, feedback_id: str) -> HttpResponse:
    feedback = get_object_or_404(CommunityFeedback, feedback_id=feedback_id)
    member = member_for_request(request)
    if member is None or not is_governance_principal(member):
        return HttpResponseForbidden("只有治理成员才能回应反馈。")

    action = request.POST.get("action", "respond")
    try:
        if action == "hide":
            hide_feedback(
                feedback=feedback,
                actor_member=member,
                reason=request.POST.get("official_response", ""),
            )
            messages.success(request, "反馈已隐藏。")
        elif action == "link":
            proposal_no = request.POST.get("proposal_no", "").strip()
            if not proposal_no:
                messages.error(request, "请提供提案编号。")
                return redirect("feedback-detail", feedback_id=feedback_id)
            proposal = get_object_or_404(Proposal, proposal_no=proposal_no)
            link_feedback_to_proposal(
                feedback=feedback, proposal=proposal, actor_member=member,
            )
            messages.success(request, f"已关联提案 {proposal_no}。")
        else:
            form = FeedbackResponseForm(request.POST)
            if not form.is_valid():
                messages.error(request, "请填写回应内容和状态。")
                return redirect("feedback-detail", feedback_id=feedback_id)
            respond_to_feedback(
                feedback=feedback,
                responder_member=member,
                response=form.cleaned_data.get("official_response", ""),
                status=form.cleaned_data["status"],
            )
            messages.success(request, "回应已记录。")
    except DomainError as exc:
        messages.error(request, str(exc))

    return redirect("feedback-detail", feedback_id=feedback_id)
