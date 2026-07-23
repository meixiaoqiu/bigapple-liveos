"""Unified work-item builder for the workspace dashboard.

Collects pending actions across procurement, proposals, receipt and
payment — producing a flat list of ``work_items`` with type, status,
priority and target URLs.
"""

from __future__ import annotations

from datetime import date

from django.db.models import Q

from core.access import is_finance_reviewer, is_governance_principal
from core.models import ApprovalProposal, ApprovalDecision, Member, SupplierQuote
from core.proposal_services import (
    member_available_approval_roles,
    proposal_is_actionable_by,
    proposal_is_executable_by,
)


def build_member_work_items(member: Member) -> dict:
    """Return a dict of work-item groups for *member*."""

    is_gov = is_governance_principal(member)
    is_fin = is_finance_reviewer(member)

    items_approval: list[dict] = []
    items_execute: list[dict] = []
    items_receipt: list[dict] = []
    items_payment: list[dict] = []

    if is_gov or is_fin:
        proposals = list(
            ApprovalProposal.objects.filter(status=ApprovalProposal.Status.SUBMITTED)
            .select_related("submitted_by")
            .order_by("-submitted_at")
        )
        for p in proposals:
            if proposal_is_actionable_by(member, p):
                items_approval.append({
                    "item_type": "approval",
                    "title": p.title,
                    "summary": f"提案 {p.proposal_id} · {p.get_proposal_type_display()} · {p.get_approval_tier_display()}",
                    "target_url": f"/workspace/proposals/",
                    "created_at": p.submitted_at,
                })

        approved = list(
            ApprovalProposal.objects.filter(status=ApprovalProposal.Status.APPROVED)
            .order_by("-resolved_at")
        )
        for p in approved:
            if proposal_is_executable_by(member, p):
                items_execute.append({
                    "item_type": "execute",
                    "title": p.title,
                    "summary": f"提案 {p.proposal_id} · 可执行",
                    "target_url": f"/workspace/proposals/",
                    "created_at": p.resolved_at,
                })

        # Receipt-pending quotes
        receipt_pending = list(
            SupplierQuote.objects.filter(
                decision_status=SupplierQuote.DecisionStatus.ACCEPTED,
                receipt_status=SupplierQuote.ReceiptStatus.PENDING,
            )
            .select_related("resource", "submitted_by")
            .order_by("-created_at")
        )
        from core.procurement_services import quote_is_ready_for_receipt

        for q in receipt_pending:
            if quote_is_ready_for_receipt(q):
                items_receipt.append({
                    "item_type": "receipt",
                    "title": f"验收：{q.resource.name or q.resource_id}",
                    "summary": f"报价 {q.quote_id} · 数量 {q.available_quantity} · {q.get_offer_type_display()}",
                    "target_url": f"/workspace/procurement/?status=accepted",
                    "created_at": q.updated_at or q.created_at,
                })

        # Payment-pending quotes
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
            items_payment.append({
                "item_type": "payment",
                "title": f"{'付款' if q.offer_type == SupplierQuote.OfferType.QUOTE else '捐赠完成'}：{q.resource.name or q.resource_id}",
                "summary": f"报价 {q.quote_id} · 金额 {q.estimated_total_amount} {q.currency}",
                "target_url": f"/workspace/procurement/?status=accepted",
                "created_at": q.updated_at or q.created_at,
            })

    return {
        "approval_pending": items_approval,
        "execute_pending": items_execute,
        "receipt_pending": items_receipt,
        "payment_pending": items_payment,
        "total_pending": len(items_approval) + len(items_execute) + len(items_receipt) + len(items_payment),
    }
