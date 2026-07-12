"""Member-facing self-service workspace views."""

from __future__ import annotations

from django.contrib import messages
from django.db.models import Q
from django.http import HttpRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from live_os.access import member_for_request, page_forbidden
from core.dispute_services import submit_dispute
from core.exceptions import DomainError
from core.models import Member, Task
from core.tasks.member_workflow import claim_task, submit_labor
from worlds.routing import world_redirect

from .context import workspace_context


def parse_evidence_refs(raw_value: str) -> list[str]:
    """Parse form evidence refs while keeping the API contract as a list."""

    normalized = raw_value.replace(",", "\n")
    return [line.strip() for line in normalized.splitlines() if line.strip()]


def current_member_or_forbidden(request: HttpRequest) -> Member | HttpResponseForbidden:
    member = member_for_request(request)
    if member is None:
        return page_forbidden("需要登录并绑定成员身份。")
    return member


@require_GET
def workspace_page(request: HttpRequest):
    member = current_member_or_forbidden(request)
    if isinstance(member, HttpResponseForbidden):
        return member
    return render(request, "workspace/index.html", workspace_context(member.member_no))


@require_POST
def workspace_claim_task(request: HttpRequest, task_id: str):
    member = current_member_or_forbidden(request)
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
    member = current_member_or_forbidden(request)
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
    member = current_member_or_forbidden(request)
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
