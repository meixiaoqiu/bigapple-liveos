"""Member JSON API views."""

from __future__ import annotations

import json

from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from live_os.access import require_full_workspace_member_json, require_member_json
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
    denied = require_full_workspace_member_json(request, member_no)
    if denied:
        return denied
    context = workspace_context(member_no)
    return JsonResponse(
        {
            "simulation_day": context["simulation_day"],
            "member": member_to_contract(context["member"]),
            "credit_balance": context["credit_balance"],
            "available_credit_balance": context.get("available_credit_balance", context["credit_balance"]),
            "lifetime_contribution": context.get("lifetime_contribution", 0),
            "available_tasks": [task_to_contract(task) for task in context["available_tasks"]],
            "active_tasks": [task_to_contract(task) for task in context["active_tasks"]],
            "recent_ledger_entries": [
                ledger_entry_to_contract(entry)
                for entry in context["recent_ledger_entries"]
            ],
            "recent_events": [event_to_contract(event) for event in context["recent_events"]],
            "open_disputes": [dispute_to_contract(dispute) for dispute in context["open_disputes"]],
            "dispute_history": [dispute_to_contract(dispute) for dispute in context["dispute_history"]],
            "resource_warnings": [resource_to_contract(resource) for resource in context["resource_warnings"]],
            "task_counts": context["task_counts"],
        }
    )


@require_POST
def post_credit_transfer(request: HttpRequest, member_no: str, **_kwargs) -> JsonResponse:
    """POST /api/v0.1/members/<member_no>/credit-transfers

    Transfer credits from *member_no* to another member.  Only the
    authenticated member may initiate their own outgoing transfers.
    """
    denied = require_full_workspace_member_json(request, member_no)
    if denied:
        return denied

    # Explicit self-only check: no governance/admin delegation
    from live_os.access import member_for_request as _mfr
    current_member = _mfr(request)
    if current_member is None or current_member.member_no != member_no:
        return JsonResponse(
            {"error": "只能由本人发起积分转出。"}, status=403,
        )

    try:
        body = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "请求体必须是合法 JSON。"}, status=400)

    if not isinstance(body, dict):
        return JsonResponse({"error": "请求体必须是 JSON object。"}, status=400)

    to_member_no = body.get("to_member_no")
    amount = body.get("amount")
    reason = body.get("reason")
    idempotency_key = body.get("idempotency_key")

    if not isinstance(to_member_no, str) or not to_member_no.strip():
        return JsonResponse({"error": "to_member_no 必须是非空字符串。"}, status=400)
    to_member_no = to_member_no.strip()

    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        return JsonResponse({"error": "amount 必须是正整数。"}, status=400)

    if reason is not None and not isinstance(reason, str):
        return JsonResponse({"error": "reason 必须是字符串。"}, status=400)
    reason_str = str(reason or "")[:256]

    if idempotency_key is not None and not isinstance(idempotency_key, str):
        return JsonResponse({"error": "idempotency_key 必须是字符串。"}, status=400)

    from_member = get_object_or_404(Member, member_no=member_no)
    to_member = get_object_or_404(Member, member_no=to_member_no)

    from core.credit_services import transfer_member_credits
    from core.exceptions import DomainError

    try:
        txn = transfer_member_credits(
            from_member=from_member,
            to_member=to_member,
            amount=amount,
            reason=reason_str,
            initiated_by=from_member,
            idempotency_key=idempotency_key,
        )
    except DomainError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    return JsonResponse(
        {
            "transaction_id": txn.transaction_id,
            "transaction_type": txn.transaction_type,
            "amount": txn.amount,
            "from_member_no": from_member.member_no,
            "to_member_no": to_member.member_no,
            "reason": txn.reason,
            "created_at": txn.created_at.isoformat(),
        },
        status=201,
    )
