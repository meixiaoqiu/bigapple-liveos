"""Workspace procurement management views (governance / finance only)."""

from __future__ import annotations

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_http_methods

from worlds.routing import world_redirect

from core.access import is_finance_reviewer, is_governance_principal
from core.exceptions import DomainError
from core.models import ApprovalProposal, ApprovalDecision, Member, SupplierQuote
from core.procurement_services import (
    mark_offer_paid_or_donated,
    quote_is_ready_for_receipt,
    record_offer_receipt,
    _compute_approval_tier,
)
from core.proposal_services import (
    create_approval_proposal,
    proposal_approved_roles,
    proposal_missing_roles,
    proposal_required_roles,
)
from live_os.access import member_for_request

from .context import member_has_full_workspace_access


def _check_member(request: HttpRequest) -> Member | None:
    member = member_for_request(request)
    if member is None:
        return None
    if not member_has_full_workspace_access(member):
        return None
    return member


def _governance_or_finance_or_forbidden(member: Member) -> bool:
    if is_governance_principal(member):
        return False
    if is_finance_reviewer(member):
        return False
    return True


@require_GET
def procurement_list(request: HttpRequest) -> HttpResponse:
    member = _check_member(request)
    if member is None:
        return render(request, "workspace/login_required.html", status=403)
    if _governance_or_finance_or_forbidden(member):
        return render(request, "workspace/login_required.html", status=403)

    quotes = list(
        SupplierQuote.objects.select_related("resource", "submitted_by")
        .order_by("-created_at")
    )
    status_filter = request.GET.get("status", "submitted")
    filtered = [q for q in quotes if q.decision_status == status_filter]

    # Attach proposal info for each quote
    for q in filtered:
        q.proposal = (
            ApprovalProposal.objects.filter(
                target_type="supplier_quote",
                target_id=q.quote_id,
                proposal_type=ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE,
            ).order_by("-submitted_at").first()
        )
        q.ready_for_receipt = quote_is_ready_for_receipt(q)
        q.receipt_pending = q.receipt_status == SupplierQuote.ReceiptStatus.PENDING

    return render(
        request,
        "workspace/procurement_list.html",
        {
            "member": member,
            "filtered": filtered,
            "status_filter": status_filter,
            "statuses": SupplierQuote.DecisionStatus.choices,
            "is_governance": is_governance_principal(member),
            "is_finance": is_finance_reviewer(member),
        },
    )


@require_http_methods(["POST"])
def procurement_create_proposal(request: HttpRequest, quote_id: str) -> HttpResponse:
    """Create a PROCUREMENT_ACCEPTANCE proposal for a submitted quote."""
    member = _check_member(request)
    if member is None:
        return render(request, "workspace/login_required.html", status=403)
    if _governance_or_finance_or_forbidden(member):
        return render(request, "workspace/login_required.html", status=403)

    quote = get_object_or_404(SupplierQuote, quote_id=quote_id)
    try:
        tier_map = {"small": "single", "standard": "standard", "major": "major"}
        tier = tier_map.get(_compute_approval_tier(quote.offer_type, quote.estimated_total_amount), "single")
        proposal = create_approval_proposal(
            proposal_type=ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE,
            dedupe_key=f"supplier_quote:{quote.quote_id}:acceptance",
            title=f"采购采纳：{quote.resource.name or quote.resource_id}",
            submitted_by=member,
            target_type="supplier_quote",
            target_id=quote.quote_id,
            summary=f"报价 {quote.quote_id}，数量 {quote.available_quantity}，金额 {quote.estimated_total_amount} {quote.currency}",
            approval_tier=tier,
        )
        messages.success(request, f"采纳提案 {proposal.proposal_id} 已创建。")
    except DomainError as exc:
        messages.error(request, str(exc))
    return world_redirect(request, "workspace-procurement")


@require_http_methods(["POST"])
def procurement_receipt(request: HttpRequest, quote_id: str) -> HttpResponse:
    member = _check_member(request)
    if member is None:
        return render(request, "workspace/login_required.html", status=403)
    if _governance_or_finance_or_forbidden(member):
        return render(request, "workspace/login_required.html", status=403)

    quote = get_object_or_404(SupplierQuote, quote_id=quote_id)
    receipt_status = request.POST.get("receipt_status", "").strip()
    receipt_notes = request.POST.get("receipt_notes", "").strip()
    try:
        quote, _txn = record_offer_receipt(
            quote=quote, received_by=member,
            receipt_status=receipt_status, receipt_notes=receipt_notes,
        )
        if receipt_status == SupplierQuote.ReceiptStatus.ACCEPTED:
            messages.success(request, f"报价 {quote_id} 验收通过，库存已更新。")
        else:
            messages.success(request, f"报价 {quote_id} 已记录验收结果。")
    except DomainError as exc:
        messages.error(request, str(exc))
    return world_redirect(request, "workspace-procurement")


@require_http_methods(["POST"])
def procurement_complete(request: HttpRequest, quote_id: str) -> HttpResponse:
    member = _check_member(request)
    if member is None:
        return render(request, "workspace/login_required.html", status=403)
    if _governance_or_finance_or_forbidden(member):
        return render(request, "workspace/login_required.html", status=403)

    quote = get_object_or_404(SupplierQuote, quote_id=quote_id)
    try:
        mark_offer_paid_or_donated(quote=quote, actor=member)
        messages.success(request, f"报价 {quote_id} 完成，履约凭证已发放。")
    except DomainError as exc:
        messages.error(request, str(exc))
    return world_redirect(request, "workspace-procurement")
