"""Governance task creation, publishing, and management views."""

from __future__ import annotations

from decimal import Decimal

from django.contrib import messages
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.views.decorators.http import require_http_methods

from worlds.routing import world_redirect
from live_os.access import is_authenticated, member_for_request, page_forbidden
from core.access import is_governance_principal
from core.credit_services import ensure_system_accounts, task_locked_credit_balance
from core.exceptions import DomainError
from core.models import Member, Task
from workspace.context import member_has_full_workspace_access, workspace_context


def _require_governance(request: HttpRequest) -> Member | HttpResponseForbidden:
    if not is_authenticated(request):
        return page_forbidden("需要登录。")
    member = member_for_request(request)
    if member is None:
        return page_forbidden("需要绑定成员身份。")
    if not member_has_full_workspace_access(member):
        return page_forbidden("正式成员以上才能访问此功能。")
    if not is_governance_principal(member):
        return page_forbidden("仅治理成员可访问。")
    return member


def render_with(request, template, context):
    from django.shortcuts import render
    return render(request, template, context)


# ── task create ──────────────────────────────────────────────────────


@require_http_methods(["GET", "POST"])
def task_create_page(request: HttpRequest) -> HttpResponse:
    member = _require_governance(request)
    if isinstance(member, HttpResponseForbidden):
        return member

    ensure_system_accounts()

    if request.method == "POST":
        return _handle_create(member, request)

    return _task_manage_page(member, request)


def _actor_ref(member):
    return {"actor_id": member.member_no, "display_name": str(member.profile.get("display_name", member.member_no))}


def _handle_create(member, request):
    title = request.POST.get("title", "").strip()
    task_type = request.POST.get("task_type", "").strip()
    standard_hours_str = request.POST.get("standard_hours", "").strip()
    base_points_str = request.POST.get("base_points", "0").strip()
    requires_review = request.POST.get("requires_review", "true").strip().lower() in ("1", "true", "on", "yes")

    # Validate
    if not title:
        messages.error(request, "任务标题不能为空。")
        return _task_manage_page(member, request)

    valid_types = {v for v, _ in Task.TaskType.choices}
    if task_type not in valid_types:
        messages.error(request, f"无效的任务类型: {task_type}。")
        return _task_manage_page(member, request)

    try:
        standard_hours = Decimal(standard_hours_str)
        if standard_hours <= 0:
            raise ValueError
    except (ValueError, TypeError, Exception):
        messages.error(request, "标准工时必须是正数。")
        return _task_manage_page(member, request)

    try:
        base_points = int(base_points_str)
        if base_points < 0:
            raise ValueError
    except (ValueError, TypeError):
        messages.error(request, "基础积分必须是非负整数。")
        return _task_manage_page(member, request)

    try:
        from core.tasks.authoring import create_task_draft
        task = create_task_draft(
            title=title,
            task_type=task_type,
            standard_hours=standard_hours,
            base_points=base_points,
            role_coefficient=Decimal("1.0"),
            failure_consequence="",
            can_be_delayed=True,
            requires_review=requires_review,
            rule_version="ruleset-v0.1.0",
            created_by=_actor_ref(member),
        )
    except DomainError as exc:
        messages.error(request, str(exc))
        return _task_manage_page(member, request)

    messages.success(request, f"任务 {task.task_id} 已创建为草稿。")
    return world_redirect(request, "workspace-tasks-manage")


# ── task publish ─────────────────────────────────────────────────────


@require_http_methods(["POST"])
def task_publish_page(request: HttpRequest, task_id: str) -> HttpResponse:
    member = _require_governance(request)
    if isinstance(member, HttpResponseForbidden):
        return member

    task = Task.objects.filter(task_id=task_id).first()
    if task is None:
        messages.error(request, f"任务 {task_id} 不存在。")
        return world_redirect(request, "workspace-tasks-manage")

    try:
        from core.tasks.authoring import publish_task
        publish_task(task=task, publisher=_actor_ref(member))
    except DomainError as exc:
        messages.error(request, str(exc))
        return world_redirect(request, "workspace-tasks-manage")

    messages.success(request, f"任务 {task_id} 已发布为开放领取。")
    return world_redirect(request, "workspace-tasks-manage")


# ── shared page renderer ─────────────────────────────────────────────


def _task_manage_page(member, request):
    from django.shortcuts import render

    tasks = list(
        Task.objects.exclude(status__in=["closed", "cancelled"])
        .order_by("-created_at")[:50]
    )
    task_rows = []
    for t in tasks:
        task_rows.append({
            "task": t,
            "locked_budget": task_locked_credit_balance(t),
        })

    ctx = workspace_context(member.member_no)
    ctx["member"] = member
    ctx["task_rows"] = task_rows
    ctx["task_types"] = [v for v, _ in Task.TaskType.choices]
    return render(request, "workspace/tasks_manage.html", ctx)


# ── task review ──────────────────────────────────────────────────────


@require_http_methods(["GET", "POST"])
def task_review_page(request: HttpRequest) -> HttpResponse:
    member = _require_governance(request)
    if isinstance(member, HttpResponseForbidden):
        return member

    ensure_system_accounts()

    if request.method == "POST":
        return _handle_review(member, request)

    return _review_list_page(member, request)


def _handle_review(member, request):
    task_id = request.POST.get("task_id", "").strip()
    decision = request.POST.get("decision", "").strip()
    reason = request.POST.get("reason", "").strip()[:512]

    if not task_id:
        messages.error(request, "请输入任务 ID。")
        return _review_list_page(member, request)

    if decision not in ("accepted", "rejected"):
        messages.error(request, "决策只能是 accepted 或 rejected。")
        return _review_list_page(member, request)

    task = Task.objects.filter(task_id=task_id).first()
    if task is None:
        messages.error(request, f"任务 {task_id} 不存在。")
        return _review_list_page(member, request)

    try:
        from core.tasks.review import review_task
        review_task(task=task, reviewer=_actor_ref(member), accepted=(decision == "accepted"), reason=reason)
    except DomainError as exc:
        messages.error(request, str(exc))
        return _review_list_page(member, request)

    messages.success(request, f"任务 {task_id} 已{'验收通过' if decision == 'accepted' else '驳回'}。")
    return world_redirect(request, "workspace-tasks-review")


def _review_list_page(member, request):
    from decimal import Decimal
    from django.shortcuts import render

    pending = list(
        Task.objects.filter(status=Task.Status.PENDING_REVIEW)
        .select_related("assignee_member")
        .order_by("-submitted_at")[:50]
    )
    task_rows = []
    for t in pending:
        meta = t.metadata or {}
        labor_note = meta.get("labor_note", "")
        evidence_refs = meta.get("evidence_refs", [])
        reward = int((Decimal(t.base_points) * t.role_coefficient).to_integral_value()) if t.base_points > 0 else 0
        task_rows.append({
            "task": t,
            "labor_note": labor_note,
            "evidence_refs": evidence_refs,
            "reward": reward,
            "locked_budget": task_locked_credit_balance(t),
        })

    ctx = workspace_context(member.member_no)
    ctx["member"] = member
    ctx["task_rows"] = task_rows
    return render(request, "workspace/tasks_review.html", ctx)
