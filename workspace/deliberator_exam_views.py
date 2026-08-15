"""Member workspace views for the deliberator qualification exam."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.deliberator_exam_services import (
    EXAM_UNAVAILABLE_MESSAGE,
    create_exam_question,
    deliberator_exam_readiness,
    member_exam_view,
    publish_exam_policy,
    start_deliberator_exam,
    submit_deliberator_exam,
)
from core.authorization_services import AuthorizationService
from core.governance_setup import DELIBERATOR_EXAM_MANAGE_PERMISSION
from core.exceptions import DomainError
from core.member_roles import ROLE_DELIBERATOR, member_has_role
from core.models import DeliberatorExamAttempt, DeliberatorExamPolicy, DeliberatorExamQuestion
from live_os.access import page_forbidden
from worlds.routing import world_redirect

from .access import require_full_workspace_member


@require_http_methods(["GET", "POST"])
def deliberator_exam_home(request: HttpRequest) -> HttpResponse:
    member = require_full_workspace_member(request)
    if isinstance(member, HttpResponse):
        return member
    if request.method == "POST":
        try:
            attempt = start_deliberator_exam(member=member)
        except DomainError as exc:
            messages.error(request, str(exc))
        else:
            return world_redirect(request, "workspace-deliberator-exam-attempt", attempt.attempt_id)
    latest = member.deliberator_exam_attempts.select_related("role_assignment").order_by("-started_at").first()
    readiness = deliberator_exam_readiness()
    return render(request, "workspace/deliberator_exam_home.html", {
        "member": member,
        "latest_attempt": latest,
        "has_active_term": member_has_role(member, ROLE_DELIBERATOR),
        "exam_ready": readiness.ready,
        "exam_unavailable_message": EXAM_UNAVAILABLE_MESSAGE,
    })


@require_http_methods(["GET", "POST"])
def deliberator_exam_attempt(request: HttpRequest, attempt_id: str) -> HttpResponse:
    member = require_full_workspace_member(request)
    if isinstance(member, HttpResponse):
        return member
    attempt = get_object_or_404(DeliberatorExamAttempt, attempt_id=attempt_id, member=member)
    if request.method == "POST":
        answers = {
            item["snapshot_id"]: request.POST.get(f"answer_{item['snapshot_id']}", "")
            for item in attempt.question_snapshot_json
        }
        try:
            attempt = submit_deliberator_exam(member=member, attempt=attempt, answers=answers)
        except DomainError as exc:
            messages.error(request, str(exc))
            attempt.refresh_from_db()
        else:
            if attempt.status == DeliberatorExamAttempt.Status.PASSED:
                messages.success(request, "考试通过，执衡者任期已生效。")
            else:
                messages.error(request, "本次考试未达到及格线，可以重新参加考试。")
            return world_redirect(request, "workspace-deliberator-exam-attempt", attempt.attempt_id)
    return render(request, "workspace/deliberator_exam_attempt.html", {
        "member": member, "attempt": attempt, "exam": member_exam_view(attempt),
    })


@require_http_methods(["GET", "POST"])
def deliberator_exam_configuration(request: HttpRequest) -> HttpResponse:
    """Provide the minimal business-authorized exam configuration entry."""
    member = require_full_workspace_member(request)
    if isinstance(member, HttpResponse):
        return member
    if not AuthorizationService().member_has_permission(member, DELIBERATOR_EXAM_MANAGE_PERMISSION):
        return page_forbidden("没有维护执衡者题库的权限。")

    if request.method == "POST":
        try:
            if request.POST.get("action") == "publish_question":
                create_exam_question(
                    actor=member,
                    prompt=request.POST.get("prompt", ""),
                    options=[
                        {"id": "a", "text": request.POST.get("option_a", "").strip()},
                        {"id": "b", "text": request.POST.get("option_b", "").strip()},
                    ],
                    correct_option_id=request.POST.get("correct_option_id", ""),
                    explanation=request.POST.get("explanation", "").strip(),
                    publish=True,
                )
                messages.success(request, "题目已创建并发布。")
            elif request.POST.get("action") == "publish_policy":
                publish_exam_policy(
                    actor=member,
                    question_count=int(request.POST.get("question_count", "0")),
                    passing_percent=int(request.POST.get("passing_percent", "0")),
                )
                messages.success(request, "考试政策已发布。")
        except (DomainError, ValidationError, ValueError) as exc:
            messages.error(request, str(exc) or "输入格式不正确。")
        else:
            return world_redirect(request, "workspace-deliberator-exam-configuration")

    active_policy = DeliberatorExamPolicy.objects.filter(status=DeliberatorExamPolicy.Status.ACTIVE).first()
    return render(request, "workspace/deliberator_exam_configuration.html", {
        "published_question_count": DeliberatorExamQuestion.objects.filter(
            status=DeliberatorExamQuestion.Status.PUBLISHED,
        ).count(),
        "active_policy": active_policy,
    })
