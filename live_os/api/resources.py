"""Resource JSON API views."""

from __future__ import annotations

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from core.models import Resource

from .serializers import public_resource_to_contract


@require_GET
def list_resources(request, **_kwargs) -> JsonResponse:
    resources = Resource.objects.all().order_by("resource_type", "resource_id")
    return JsonResponse([public_resource_to_contract(resource) for resource in resources], safe=False)
