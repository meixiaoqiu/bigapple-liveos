"""Public and internal event JSON API views."""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from live_os.access import require_governance_json
from core.models import Event

from .serializers import event_to_contract, public_event_to_contract
from .utils import error_response


@require_GET
def list_events(request: HttpRequest, **_kwargs) -> JsonResponse:
    requested_visibility = request.GET.get("visibility", Event.Visibility.PUBLIC)
    valid_visibilities = {value for value, _label in Event.Visibility.choices}
    if requested_visibility not in valid_visibilities:
        return error_response("invalid_request", "Invalid event visibility.", 400)
    if requested_visibility != Event.Visibility.PUBLIC:
        denied = require_governance_json(request)
        if denied:
            return denied
    events = Event.objects.filter(visibility=requested_visibility).order_by("occurred_at", "event_id")
    simulation_day = request.GET.get("simulation_day")
    if simulation_day:
        events = events.filter(simulation_day=int(simulation_day))
    serializer = public_event_to_contract if requested_visibility == Event.Visibility.PUBLIC else event_to_contract
    return JsonResponse([serializer(event) for event in events], safe=False)
