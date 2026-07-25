"""Merchant settlement read-only API."""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from live_os.access import member_for_request as _mfr
from core.access import is_governance_principal
from core.models import MerchantProfile, MerchantSettlementRecord


@require_GET
def list_settlements(request: HttpRequest, **_kwargs) -> JsonResponse:
    current = _mfr(request)
    if current is None:
        return JsonResponse({"error": "需要登录。"}, status=403)

    merchant_id = request.GET.get("merchant_id", "").strip()
    qs = MerchantSettlementRecord.objects.select_related("merchant").order_by("-created_at")

    if merchant_id:
        qs = qs.filter(merchant_id=merchant_id)

    if is_governance_principal(current):
        # governance sees all
        pass
    else:
        # Merchants see only their own; unrelated members see nothing
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
