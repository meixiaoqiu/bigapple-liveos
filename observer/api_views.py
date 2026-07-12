"""Observer JSON endpoints."""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from live_os.api.serializers import public_event_to_contract, public_resource_to_contract

from .page_context import observer_context


@require_GET
def observer_summary(request: HttpRequest, **_kwargs) -> JsonResponse:
    context = observer_context()
    return JsonResponse(
        {
            "simulation_day": context["latest_day"],
            "formal_members": context["formal_members"],
            "candidate_members": context["candidate_members"],
            "resources": [public_resource_to_contract(resource) for resource in context["resources"]],
            "task_completion_rate": context["task_completion_rate"],
            "average_satisfaction": 0,
            "average_fatigue": 0,
            "open_disputes": context["open_disputes"],
            "events": [public_event_to_contract(event) for event in context["events"]],
        }
    )
