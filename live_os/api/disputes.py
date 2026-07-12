"""Dispute JSON API views."""

from __future__ import annotations

from django.db.models import Q
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods

from live_os.access import require_member_json
from core.dispute_services import submit_dispute
from core.exceptions import DomainError
from core.models import Member, Task

from .serializers import dispute_to_contract
from .utils import error_response, read_json


@require_http_methods(["POST"])
def create_dispute(request: HttpRequest, **_kwargs) -> JsonResponse:
    payload = read_json(request)
    server_owned_fields = {
        "dispute_id",
        "status",
        "handler",
        "reviewer",
        "resolution",
        "appeal_path",
        "submitted_at",
        "resolved_at",
    }
    if server_owned_fields.intersection(payload):
        return error_response(
            "invalid_request",
            "Dispute identity, status, handlers, and timestamps are server-managed.",
            400,
        )

    claimant_member_no = str(payload.get("claimant_member_no") or payload.get("member_no") or "").strip()
    denied = require_member_json(request, claimant_member_no)
    if denied:
        return denied
    claimant = get_object_or_404(Member, member_no=claimant_member_no)

    related_task = None
    related_task_id = str(payload.get("related_task_id") or "").strip()
    if related_task_id:
        related_task = (
            Task.objects.filter(task_id=related_task_id)
            .filter(Q(status=Task.Status.OPEN) | Q(assignee_member=claimant))
            .first()
        )
        if related_task is None:
            return error_response("not_found", "Related task is not visible to the claimant.", 404)

    try:
        dispute = submit_dispute(
            claimant=claimant,
            dispute_type=payload.get("dispute_type", ""),
            facts=payload.get("facts", ""),
            evidence_refs=payload.get("evidence_refs", []),
            related_task=related_task,
        )
    except DomainError as exc:
        return error_response("state_conflict", str(exc), 409)
    return JsonResponse(dispute_to_contract(dispute), status=201)
