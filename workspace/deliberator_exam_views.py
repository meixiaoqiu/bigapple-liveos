"""Member workspace views for the deliberator qualification exam."""

from django.contrib import messages
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.deliberator_exam_services import member_exam_view, start_deliberator_exam, submit_deliberator_exam
from core.exceptions import DomainError
from core.member_roles import ROLE_DELIBERATOR, member_has_role
from core.models import DeliberatorExamAttempt
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
    return render(request, "workspace/deliberator_exam_home.html", {
        "member": member,
        "latest_attempt": latest,
        "has_active_term": member_has_role(member, ROLE_DELIBERATOR),
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
