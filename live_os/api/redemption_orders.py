"""Redemption order API views."""

from __future__ import annotations

import json

from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST, require_http_methods

from live_os.access import require_full_workspace_member_json, member_for_request as _mfr
from core.models import Member, MerchantProfile, RedemptionOrder


_ITEM_TYPES = {v for v, _ in RedemptionOrder.ItemType.choices}


def _order_to_contract(order: RedemptionOrder) -> dict:
    return {
        "order_id": order.order_id,
        "member_no": order.member.member_no,
        "status": order.status,
        "item_type": order.item_type,
        "title": order.title,
        "original_amount_rmb": float(order.original_amount_rmb) if order.original_amount_rmb else None,
        "credit_amount": order.credit_amount,
        "cash_amount_rmb": float(order.cash_amount_rmb) if order.cash_amount_rmb else None,
        "merchant_id": order.merchant.merchant_id if order.merchant else "",
        "related_task_id": order.related_task_id or "",
        "related_event_id": order.related_event_id,
        "resource_id": order.resource_id,
        "item_snapshot": order.item_snapshot or {},
        "finance_treatment_ref": order.finance_treatment_ref,
        "reason": order.reason,
        "metadata": order.metadata or {},
        "created_by_member_no": order.created_by.member_no if order.created_by else "",
        "reviewed_by_member_no": order.reviewed_by.member_no if order.reviewed_by else "",
        "created_at": order.created_at.isoformat() if order.created_at else "",
        "updated_at": order.updated_at.isoformat() if order.updated_at else "",
        "fulfilled_at": order.fulfilled_at.isoformat() if order.fulfilled_at else None,
        "cancelled_at": order.cancelled_at.isoformat() if order.cancelled_at else None,
    }


@require_http_methods(["GET", "POST"])
def list_create_redemption_orders(request: HttpRequest, member_no: str, **_kwargs) -> JsonResponse:
    """GET/POST /api/v0.1/members/<no>/redemption-orders"""
    if request.method == "GET":
        return _list_orders(request, member_no)
    return _create_order(request, member_no)


def _list_orders(request, member_no):
    denied = require_full_workspace_member_json(request, member_no)
    if denied:
        return denied
    current_member = _mfr(request)
    if current_member is None or current_member.member_no != member_no:
        return JsonResponse({"error": "只能查看本人的兑换订单。"}, status=403)
    orders = list(
        RedemptionOrder.objects.filter(member__member_no=member_no).order_by("-created_at")
    )
    return JsonResponse({"orders": [_order_to_contract(o) for o in orders]})


def _parse_body(request) -> tuple[dict | None, JsonResponse | None]:
    try:
        body = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, JsonResponse({"error": "请求体必须是合法 JSON。"}, status=400)
    if not isinstance(body, dict):
        return None, JsonResponse({"error": "请求体必须是 JSON object。"}, status=400)
    return body, None


def _create_order(request, member_no):
    denied = require_full_workspace_member_json(request, member_no)
    if denied:
        return denied
    current_member = _mfr(request)
    if current_member is None or current_member.member_no != member_no:
        return JsonResponse({"error": "只能由本人创建兑换订单。"}, status=403)

    body, err = _parse_body(request)
    if err:
        return err

    credit_amount = body.get("credit_amount")
    if not isinstance(credit_amount, int) or isinstance(credit_amount, bool) or credit_amount <= 0:
        return JsonResponse({"error": "credit_amount 必须是正整数。"}, status=400)

    item_type = body.get("item_type", RedemptionOrder.ItemType.OTHER)
    if not isinstance(item_type, str) or item_type not in _ITEM_TYPES:
        return JsonResponse({"error": f"item_type 无效，允许值: {', '.join(sorted(_ITEM_TYPES))}。"}, status=400)

    for field in ("title", "reason"):
        val = body.get(field, "")
        if not isinstance(val, str):
            return JsonResponse({"error": f"{field} 必须是字符串。"}, status=400)

    for field in ("original_amount_rmb", "cash_amount_rmb"):
        val = body.get(field)
        if val is not None and not isinstance(val, (int, float)):
            return JsonResponse({"error": f"{field} 必须是数字或 null。"}, status=400)

    resource_id = body.get("resource_id", "")
    if not isinstance(resource_id, str):
        return JsonResponse({"error": "resource_id 必须是字符串。"}, status=400)
    finance_treatment_ref = body.get("finance_treatment_ref", "")
    if not isinstance(finance_treatment_ref, str):
        return JsonResponse({"error": "finance_treatment_ref 必须是字符串。"}, status=400)
    item_snapshot = body.get("item_snapshot")
    if item_snapshot is not None and not isinstance(item_snapshot, dict):
        return JsonResponse({"error": "item_snapshot 必须是 JSON object。"}, status=400)
    idempotency_key = body.get("idempotency_key")
    if idempotency_key is not None and not isinstance(idempotency_key, str):
        return JsonResponse({"error": "idempotency_key 必须是字符串。"}, status=400)

    merchant_id = body.get("merchant_id")
    if merchant_id is not None and not isinstance(merchant_id, str):
        return JsonResponse({"error": "merchant_id 必须是字符串。"}, status=400)
    merchant = None
    if merchant_id:
        merchant = MerchantProfile.objects.filter(merchant_id=merchant_id).first()
        if merchant is None:
            return JsonResponse({"error": f"商户 {merchant_id} 不存在。"}, status=400)

    from core.credit_services import create_redemption_order as _create_ro
    from core.exceptions import DomainError

    try:
        order, txn = _create_ro(
            member=current_member,
            credit_amount=credit_amount,
            item_type=item_type,
            title=str(body.get("title", "") or "")[:256],
            reason=str(body.get("reason", "") or "")[:256],
            original_amount_rmb=body.get("original_amount_rmb"),
            cash_amount_rmb=body.get("cash_amount_rmb"),
            resource_id=resource_id,
            item_snapshot=item_snapshot or {},
            finance_treatment_ref=finance_treatment_ref,
            merchant=merchant,
            idempotency_key=idempotency_key,
            created_by=current_member,
        )
    except DomainError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    return JsonResponse(_order_to_contract(order), status=201)


@require_POST
def cancel_redemption_order_view(request: HttpRequest, order_id: str, **_kwargs) -> JsonResponse:
    order = get_object_or_404(RedemptionOrder, order_id=order_id)
    denied = require_full_workspace_member_json(request, order.member.member_no)
    if denied:
        return denied
    current_member = _mfr(request)
    if current_member is None or current_member.member_no != order.member.member_no:
        return JsonResponse({"error": "只能取消本人的兑换订单。"}, status=403)

    body, err = _parse_body(request)
    if err:
        return err
    reason = body.get("reason", "")
    if not isinstance(reason, str):
        return JsonResponse({"error": "reason 必须是字符串。"}, status=400)

    from core.credit_services import cancel_redemption_order as _cancel_ro
    from core.exceptions import DomainError
    try:
        order = _cancel_ro(order=order, reason=str(reason)[:256], cancelled_by=current_member)
    except DomainError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse(_order_to_contract(order))


@require_POST
def dispute_redemption_order_view(request: HttpRequest, order_id: str, **_kwargs) -> JsonResponse:
    order = get_object_or_404(RedemptionOrder, order_id=order_id)
    denied = require_full_workspace_member_json(request, order.member.member_no)
    if denied:
        return denied
    current_member = _mfr(request)
    if current_member is None or current_member.member_no != order.member.member_no:
        return JsonResponse({"error": "只能申诉本人的兑换订单。"}, status=403)

    body, err = _parse_body(request)
    if err:
        return err
    reason = body.get("reason", "")
    if not isinstance(reason, str):
        return JsonResponse({"error": "reason 必须是字符串。"}, status=400)

    from core.credit_services import dispute_redemption_order as _dispute_ro
    from core.exceptions import DomainError
    try:
        order = _dispute_ro(order=order, reason=str(reason)[:256])
    except DomainError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse(_order_to_contract(order))


@require_POST
def fulfill_redemption_order_view(request: HttpRequest, order_id: str, **_kwargs) -> JsonResponse:
    from core.access import is_governance_principal
    current_member = _mfr(request)
    if current_member is None or not is_governance_principal(current_member):
        return JsonResponse({"error": "只有治理成员可以履约兑换订单。"}, status=403)

    order = get_object_or_404(RedemptionOrder, order_id=order_id)

    body, err = _parse_body(request)
    if err:
        return err
    reason = body.get("reason", "")
    if not isinstance(reason, str):
        return JsonResponse({"error": "reason 必须是字符串。"}, status=400)

    from core.credit_services import fulfill_redemption_order as _fulfill_ro
    from core.exceptions import DomainError
    try:
        order = _fulfill_ro(order=order, reason=str(reason)[:256], reviewed_by=current_member)
    except DomainError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse(_order_to_contract(order))
