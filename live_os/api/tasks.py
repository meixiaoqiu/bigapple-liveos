"""Task JSON API views."""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_http_methods

from live_os.access import actor_ref_for_request, require_governance_json, require_member_json
from core.exceptions import DomainError
from core.models import Member, Task
from core.tasks.member_workflow import claim_task, submit_labor
from core.tasks.review import review_task

from .serializers import ledger_entry_to_contract, public_task_to_contract, task_to_contract
from .utils import error_response, read_json


@require_GET
def list_tasks(request: HttpRequest, **_kwargs) -> JsonResponse:
    tasks = Task.objects.all().order_by("created_at", "task_id")
    status = request.GET.get("status")
    if status:
        tasks = tasks.filter(status=status)
    return JsonResponse([public_task_to_contract(task) for task in tasks], safe=False)


@require_http_methods(["POST"])
def claim_task_view(request: HttpRequest, task_id: str, **_kwargs) -> JsonResponse:
    payload = read_json(request)
    task = get_object_or_404(Task, task_id=task_id)
    member_no = str(payload.get("member_no") or "").strip()
    denied = require_member_json(request, member_no)
    if denied:
        return denied
    member = get_object_or_404(Member, member_no=member_no)
    try:
        task = claim_task(task=task, member=member)
    except DomainError as exc:
        return error_response("state_conflict", str(exc), 409)
    return JsonResponse(task_to_contract(task))


@require_http_methods(["POST"])
def submit_labor_view(request: HttpRequest, task_id: str, **_kwargs) -> JsonResponse:
    payload = read_json(request)
    task = get_object_or_404(Task, task_id=task_id)
    member_no = str(payload.get("member_no") or "").strip()
    denied = require_member_json(request, member_no)
    if denied:
        return denied
    member = get_object_or_404(Member, member_no=member_no)
    try:
        task = submit_labor(
            task=task,
            member=member,
            labor_note=payload.get("labor_note", ""),
            evidence_refs=payload.get("evidence_refs", []),
        )
    except DomainError as exc:
        return error_response("state_conflict", str(exc), 409)
    return JsonResponse(task_to_contract(task))


@require_http_methods(["POST"])
def review_task_view(request: HttpRequest, task_id: str, **_kwargs) -> JsonResponse:
    denied = require_governance_json(request)
    if denied:
        return denied
    payload = read_json(request)
    task = get_object_or_404(Task, task_id=task_id)
    try:
        task, entries = review_task(
            task=task,
            reviewer=actor_ref_for_request(request),
            accepted=bool(payload.get("accepted")),
            reason=payload.get("reason", ""),
        )
    except DomainError as exc:
        return error_response("state_conflict", str(exc), 409)
    return JsonResponse(
        {
            "task": task_to_contract(task),
            "ledger_entries": [ledger_entry_to_contract(entry) for entry in entries],
        }
    )
