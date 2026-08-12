"""Merchant settlement read-only API."""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from core.access import member_can_administer
from core.models import Member, MerchantSettlementRecord
from live_os.access import require_current_full_workspace_member_json


@require_GET
def list_settlements(request: HttpRequest, **_kwargs) -> JsonResponse:
    current = require_current_full_workspace_member_json(request)
    if not isinstance(current, Member):
        return current

    merchant_id = request.GET.get("merchant_id", "").strip()
    qs = MerchantSettlementRecord.objects.select_related("merchant").order_by("-created_at")

    if merchant_id:
        qs = qs.filter(merchant_id=merchant_id)

    if member_can_administer(current):
        pass
    else:
        qs = qs.filter(merchant__operator_member=current)

    results = [
        {
            "settlement_id": s.settlement_id,
            "merchant_id": s.merchant_id,
            "merchant_name": s.merchant.display_name,
            "order_id": s.redemption_order_id or "",
            "covered_credit_amount": s.covered_credit_amount,
            "settlement_rate": str(s.settlement_rate),
            "payable_rmb": str(s.payable_rmb),
            "status": s.status,
            "reason": s.reason,
            "created_at": s.created_at.isoformat() if s.created_at else "",
        }
        for s in qs[:50]
    ]
    return JsonResponse({"settlements": results})
