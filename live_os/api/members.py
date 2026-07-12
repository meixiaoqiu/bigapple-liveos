"""Member JSON API views."""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from live_os.access import require_member_json
from core.models import Member
from workspace.context import workspace_context

from .serializers import (
    dispute_to_contract,
    event_to_contract,
    ledger_entry_to_contract,
    member_to_contract,
    resource_to_contract,
    task_to_contract,
)


@require_GET
def get_member(request: HttpRequest, member_no: str, **_kwargs) -> JsonResponse:
    denied = require_member_json(request, member_no)
    if denied:
        return denied
    member = get_object_or_404(Member, member_no=member_no)
    return JsonResponse(member_to_contract(member))


@require_GET
def get_workspace_summary(request: HttpRequest, member_no: str, **_kwargs) -> JsonResponse:
    denied = require_member_json(request, member_no)
    if denied:
        return denied
    context = workspace_context(member_no)
    return JsonResponse(
        {
            "simulation_day": context["simulation_day"],
            "member": member_to_contract(context["member"]),
            "credit_balance": context["credit_balance"],
            "available_tasks": [task_to_contract(task) for task in context["available_tasks"]],
            "active_tasks": [task_to_contract(task) for task in context["active_tasks"]],
            "task_history": [task_to_contract(task) for task in context["task_history"]],
            "recent_ledger_entries": [
                ledger_entry_to_contract(entry)
                for entry in context["recent_ledger_entries"]
            ],
            "recent_events": [event_to_contract(event) for event in context["recent_events"]],
            "open_disputes": [dispute_to_contract(dispute) for dispute in context["open_disputes"]],
            "dispute_history": [dispute_to_contract(dispute) for dispute in context["dispute_history"]],
            "resource_warnings": [resource_to_contract(resource) for resource in context["resource_warnings"]],
            "task_counts": context["task_counts"],
            "next_actions": context["next_actions"],
        }
    )
