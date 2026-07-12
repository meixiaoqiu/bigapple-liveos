"""Contribution ledger JSON API views."""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from live_os.access import require_governance_json, require_member_json
from core.models import LedgerEntry

from .serializers import ledger_entry_to_contract


@require_GET
def list_ledger_entries(request: HttpRequest, **_kwargs) -> JsonResponse:
    entries = LedgerEntry.objects.all().order_by("system_event__seq", "created_at", "ledger_entry_id")
    member_no = request.GET.get("member_no")
    if member_no:
        denied = require_member_json(request, member_no)
        if denied:
            return denied
        entries = entries.filter(member__member_no=member_no)
    else:
        denied = require_governance_json(request)
        if denied:
            return denied
    return JsonResponse([ledger_entry_to_contract(entry) for entry in entries], safe=False)
