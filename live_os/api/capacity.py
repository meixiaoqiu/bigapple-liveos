"""Capacity assessment JSON API views."""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from core.models import CapacityAssessment

from .utils import error_response
from .serializers import public_capacity_assessment_to_contract


@require_GET
def latest_capacity_assessment(request: HttpRequest, **_kwargs) -> JsonResponse:
    assessment = CapacityAssessment.objects.order_by("-simulation_day", "-created_at").first()
    if assessment is None:
        return error_response("not_found", "No capacity assessment exists.", 404)
    return JsonResponse(public_capacity_assessment_to_contract(assessment))
