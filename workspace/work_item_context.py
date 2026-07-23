"""Unified work-item builder for the workspace dashboard.

Collects pending actions across procurement, proposals, receipt,
payment and challenges — producing a flat list of ``work_items``
with type, status, priority and target URLs.
"""

from __future__ import annotations

from datetime import datetime, timezone as tz
from django.utils import timezone as dj_timezone

from core.access import is_finance_reviewer, is_governance_principal
from core.models import (
    ApprovalProposal,
    Member,
    ProcurementChallenge,
    SupplierQuote,
)
from core.proposal_services import (
    proposal_is_actionable_by,
    proposal_is_executable_by,
)

# ── overdue thresholds (hours) ──────────────────────────────────────

OVERDUE_APPROVAL_HOURS = 24
OVERDUE_EXECUTE_HOURS = 12
OVERDUE_RECEIPT_HOURS = 48
OVERDUE_PAYMENT_HOURS = 72


def _hours_since(dt_value) -> float:
    """Return hours elapsed since *dt_value* (timezone-aware)."""
    if dt_value is None:
        return 0
    now = dj_timezone.now()
    delta = now - dt_value
    return delta.total_seconds() / 3600


def _priority_for_proposal(p: ApprovalProposal) -> str:
    if p.approval_tier == ApprovalProposal.Tier.MAJOR:
        return "critical"
    if p.approval_tier == ApprovalProposal.Tier.STANDARD:
        return "high"
    return "normal"


def _priority_for_type(item_type: str) -> str:
    return "normal"


def build_member_work_items(member: Member) -> dict:
    is_gov = is_governance_principal(member)
    is_fin = is_finance_reviewer(member)

    items_approval: list[dict] = []
    items_execute: list[dict] = []
    items_receipt: list[dict] = []
    items_payment: list[dict] = []
    items_challenge: list[dict] = []
    total_overdue = 0

    if is_gov or is_fin:
        # ── approval pending ──
        proposals = list(
            ApprovalProposal.objects.filter(status=ApprovalProposal.Status.SUBMITTED)
            .select_related("submitted_by")
            .order_by("-submitted_at")
        )
        for p in proposals:
            if proposal_is_actionable_by(member, p):
                overdue = _hours_since(p.submitted_at) > OVERDUE_APPROVAL_HOURS
                if overdue:
                    total_overdue += 1
                items_approval.append({
                    "item_type": "approval",
                    "priority": _priority_for_proposal(p),
                    "title": p.title,
                    "summary": f"提案 {p.proposal_id} · {p.get_proposal_type_display()} · {p.get_approval_tier_display()}",
                    "target_url": "/workspace/proposals/",
                    "is_overdue": overdue,
                    "age_hours": int(_hours_since(p.submitted_at)),
                    "created_at": p.submitted_at,
                })

        # ── execute pending ──
        approved = list(
            ApprovalProposal.objects.filter(status=ApprovalProposal.Status.APPROVED)
            .order_by("-resolved_at")
        )
        for p in approved:
            if proposal_is_executable_by(member, p):
                overdue = _hours_since(p.resolved_at) > OVERDUE_EXECUTE_HOURS
                if overdue:
                    total_overdue += 1
                items_execute.append({
                    "item_type": "execute",
                    "priority": _priority_for_proposal(p),
                    "title": p.title,
                    "summary": f"提案 {p.proposal_id} · 可执行",
                    "target_url": "/workspace/proposals/",
                    "is_overdue": overdue,
                    "age_hours": int(_hours_since(p.resolved_at)),
                    "created_at": p.resolved_at,
                })

        # ── receipt pending ──
        from core.procurement_services import quote_is_ready_for_receipt

        receipt_pending = list(
            SupplierQuote.objects.filter(
                decision_status=SupplierQuote.DecisionStatus.ACCEPTED,
                receipt_status=SupplierQuote.ReceiptStatus.PENDING,
            )
            .select_related("resource", "submitted_by")
            .order_by("-created_at")
        )
        for q in receipt_pending:
            if quote_is_ready_for_receipt(q):
                overdue = _hours_since(q.updated_at or q.created_at) > OVERDUE_RECEIPT_HOURS
                if overdue:
                    total_overdue += 1
                items_receipt.append({
                    "item_type": "receipt",
                    "priority": "normal",
                    "title": f"验收：{q.resource.name or q.resource_id}",
                    "summary": f"报价 {q.quote_id} · 数量 {q.available_quantity} · {q.get_offer_type_display()}",
                    "target_url": "/workspace/procurement/?status=accepted",
                    "is_overdue": overdue,
                    "age_hours": int(_hours_since(q.updated_at or q.created_at)),
                    "created_at": q.updated_at or q.created_at,
                })

        # ── payment pending ──
        payment_pending = list(
            SupplierQuote.objects.filter(
                decision_status=SupplierQuote.DecisionStatus.ACCEPTED,
                receipt_status=SupplierQuote.ReceiptStatus.ACCEPTED,
                payment_status=SupplierQuote.PaymentStatus.PENDING,
            )
            .select_related("resource", "submitted_by")
            .order_by("-created_at")
        )
        for q in payment_pending:
            overdue = _hours_since(q.updated_at or q.created_at) > OVERDUE_PAYMENT_HOURS
            if overdue:
                total_overdue += 1
            items_payment.append({
                "item_type": "payment",
                "priority": "normal",
                "title": f"{'付款' if q.offer_type == SupplierQuote.OfferType.QUOTE else '捐赠完成'}：{q.resource.name or q.resource_id}",
                "summary": f"报价 {q.quote_id} · 金额 {q.estimated_total_amount} {q.currency}",
                "target_url": "/workspace/procurement/?status=accepted",
                "is_overdue": overdue,
                "age_hours": int(_hours_since(q.updated_at or q.created_at)),
                "created_at": q.updated_at or q.created_at,
            })

        # ── challenges pending ──
        challenges = list(
            ProcurementChallenge.objects.filter(status=ProcurementChallenge.Status.SUBMITTED)
            .select_related("quote__resource")
            .order_by("-created_at")
        )
        for ch in challenges:
            items_challenge.append({
                "item_type": "challenge",
                "priority": "normal",
                "title": f"质疑：{ch.get_challenge_type_display()}",
                "summary": f"报价 {ch.quote_id} · {ch.public_reason[:80]}",
                "target_url": "",
                "is_overdue": _hours_since(ch.created_at) > OVERDUE_APPROVAL_HOURS,
                "age_hours": int(_hours_since(ch.created_at)),
                "created_at": ch.created_at,
            })

    return {
        "approval_pending": items_approval,
        "execute_pending": items_execute,
        "receipt_pending": items_receipt,
        "payment_pending": items_payment,
        "challenge_pending": items_challenge,
        "total_pending": sum(
            len(x) for x in [items_approval, items_execute, items_receipt,
                              items_payment, items_challenge]
        ),
        "total_overdue": total_overdue,
    }
