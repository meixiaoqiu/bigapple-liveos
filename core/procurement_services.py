"""Procurement / supplier-quote workflow services.

Handles offer submission, acceptance, rejection, receipt and payment
marking — with automatic credential issuance on fulfilment, event
ledger entries for every state change, and lightweight tiered approval.

State changes are wrapped in atomic blocks.  Stock mutations flow through
``core.resource_services.record_resource_adjustment`` which creates
``ResourceTransaction`` and ``SystemEvent`` records.  Procurement
decision-status updates also emit dedicated ``SystemEvent`` entries
so that the entire lifecycle is auditable.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .credential_services import ensure_builtin_credential_templates, issue_credential
from .event_ledger import append_event
from .event_payloads import supplier_offer_payload
from .exceptions import DomainError
from .models import (
    CredentialGrant,
    CredentialTemplate,
    Member,
    Resource,
    ResourceTransaction,
    SupplierQuote,
    SystemEvent,
)


# ── tier thresholds (service-layer constants) ────────────────────────

SMALL_PURCHASE_LIMIT = Decimal("500")
STANDARD_PURCHASE_LIMIT = Decimal("5000")


def _compute_approval_tier(offer_type: str, estimated_total_amount: Decimal) -> str:
    """Return the ``SupplierQuote.ApprovalTier`` for a new offer."""
    if offer_type == SupplierQuote.OfferType.DONATION or estimated_total_amount == 0:
        return SupplierQuote.ApprovalTier.SMALL
    if estimated_total_amount <= SMALL_PURCHASE_LIMIT:
        return SupplierQuote.ApprovalTier.SMALL
    if estimated_total_amount <= STANDARD_PURCHASE_LIMIT:
        return SupplierQuote.ApprovalTier.STANDARD
    return SupplierQuote.ApprovalTier.MAJOR


# ── helpers ──────────────────────────────────────────────────────────


def _new_quote_id() -> str:
    from uuid import uuid4

    return f"quote-{uuid4().hex[:12]}"


def quote_is_ready_for_receipt(quote: SupplierQuote) -> bool:
    """Return True when acceptance proposal is executed (or quote accepted directly)."""
    if quote.decision_status != SupplierQuote.DecisionStatus.ACCEPTED:
        return False
    from .models import ApprovalProposal

    # If an acceptance proposal exists, it must be executed
    prop = (
        ApprovalProposal.objects.filter(
            target_type="supplier_quote",
            target_id=quote.quote_id,
            proposal_type=ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE,
        )
        .order_by("-submitted_at")
        .first()
    )
    if prop is not None:
        return prop.status == ApprovalProposal.Status.EXECUTED
    # No proposal exists yet — allow legacy direct-accepted quotes
    return True


def _execute_procurement_acceptance(*, proposal, actor: Member):
    """Callback from ``execute_proposal`` for PROCUREMENT_ACCEPTANCE."""
    from .models import ApprovalProposal as AP, SupplierQuote
    from .exceptions import DomainError as DE

    quote = SupplierQuote.objects.get(quote_id=proposal.target_id)
    if quote.decision_status == SupplierQuote.DecisionStatus.ACCEPTED:
        return  # already accepted, idempotent
    accept_resource_offer(quote=quote, accepted_by=actor, decision_reason=proposal.public_reason)


# ── offer submission ─────────────────────────────────────────────────


def _tier_to_approval_tier(quote_tier: str) -> str:
    """Map SupplierQuote.ApprovalTier → ApprovalProposal.Tier."""
    tier_map = {"small": "single", "standard": "standard", "major": "major"}
    return tier_map.get(quote_tier, "single")


@transaction.atomic
def submit_resource_offer(
    *,
    resource: Resource,
    submitted_by: Member,
    offer_type: str,
    available_quantity: Decimal,
    unit_price: Decimal = Decimal("0"),
    currency: str = "CNY",
    minimum_order_quantity: Decimal = Decimal("0"),
    lead_time_days: int = 0,
    quality_summary: str = "",
    notes: str = "",
) -> SupplierQuote:
    """Submit a resource offer (quote or donation) by a logged-in member.

    Raises ``DomainError`` when:
    - *resource.accepts_offers* is False
    - *available_quantity* <= 0
    - *offer_type* is invalid
    - *unit_price* < 0
    - *offer_type* is ``donation`` and *unit_price* != 0

    After creating the ``SupplierQuote``, a ``PROCUREMENT_ACCEPTANCE``
    ``ApprovalProposal`` is automatically created so that governance
    members see a pending action immediately.
    """
    if not resource.accepts_offers:
        raise DomainError("该资源当前不接受公开报价。")

    if available_quantity <= 0:
        raise DomainError("可供数量必须大于 0。")

    if offer_type not in {v for v, _ in SupplierQuote.OfferType.choices}:
        raise DomainError("供给类型无效。")

    if unit_price < 0:
        raise DomainError("单价不能为负数。")

    if offer_type == SupplierQuote.OfferType.DONATION and unit_price != 0:
        raise DomainError("捐赠单价必须为 0。")

    estimated_total_amount = available_quantity * unit_price
    approval_tier = _compute_approval_tier(offer_type, estimated_total_amount)

    quote = SupplierQuote.objects.create(
        quote_id=_new_quote_id(),
        resource=resource,
        submitted_by=submitted_by,
        offer_type=offer_type,
        unit_price=unit_price,
        currency=currency,
        available_quantity=available_quantity,
        minimum_order_quantity=minimum_order_quantity,
        lead_time_days=lead_time_days,
        quality_summary=quality_summary or "",
        notes=notes or "",
        status=SupplierQuote.Status.ACTIVE,
        decision_status=SupplierQuote.DecisionStatus.SUBMITTED,
        payment_status=(
            SupplierQuote.PaymentStatus.NOT_REQUIRED
            if offer_type == SupplierQuote.OfferType.DONATION
            else SupplierQuote.PaymentStatus.PENDING
        ),
        receipt_status=SupplierQuote.ReceiptStatus.PENDING,
        estimated_total_amount=estimated_total_amount,
        approval_tier=approval_tier,
        created_at=timezone.now(),
        updated_at=timezone.now(),
    )

    append_event(
        event_type=SystemEvent.EventType.SUPPLIER_OFFER_SUBMITTED,
        aggregate_type="SupplierQuote",
        aggregate_id=quote.quote_id,
        actor_member=submitted_by,
        payload_json=supplier_offer_payload(quote, action="submitted", actor=submitted_by),
        occurred_at=quote.created_at,
    )

    # ── auto-create Proposal ──────────────────────────────────
    from .models import ApprovalProposal
    from .proposal_services import create_approval_proposal

    resource_name = resource.name or resource.resource_id
    create_approval_proposal(
        proposal_type=ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE,
        dedupe_key=f"supplier_quote:{quote.quote_id}:acceptance",
        title=f"采纳{'捐赠' if offer_type == SupplierQuote.OfferType.DONATION else '报价'}：{resource_name}",
        submitted_by=submitted_by,
        target_type="supplier_quote",
        target_id=quote.quote_id,
        summary=f"数量 {available_quantity} {resource.unit}，金额 {estimated_total_amount} {currency}",
        public_reason=quality_summary or "",
        approval_tier=_tier_to_approval_tier(approval_tier),
    )

    return quote


# ── accept / reject ──────────────────────────────────────────────────


@transaction.atomic
def accept_resource_offer(
    *,
    quote: SupplierQuote,
    accepted_by: Member,
    decision_reason: str = "",
) -> SupplierQuote:
    """Accept a submitted offer.

    Only offers with ``decision_status='submitted'`` can be accepted.
    Acceptance does NOT mean all approvals are complete — tiered
    approvals (finance / governance confirmation) may still be needed
    before receipt.
    """
    quote = SupplierQuote.objects.select_for_update().get(pk=quote.pk)

    if quote.decision_status != SupplierQuote.DecisionStatus.SUBMITTED:
        raise DomainError("只能采纳状态为'已提交'的报价。")

    quote.decision_status = SupplierQuote.DecisionStatus.ACCEPTED
    quote.accepted_by = accepted_by
    quote.accepted_at = timezone.now()
    quote.decision_reason = decision_reason or ""
    quote.updated_at = timezone.now()
    quote.save(
        update_fields=[
            "decision_status", "accepted_by", "accepted_at",
            "decision_reason", "updated_at",
        ]
    )

    append_event(
        event_type=SystemEvent.EventType.SUPPLIER_OFFER_ACCEPTED,
        aggregate_type="SupplierQuote",
        aggregate_id=quote.quote_id,
        actor_member=accepted_by,
        payload_json=supplier_offer_payload(quote, action="accepted", actor=accepted_by),
        occurred_at=quote.accepted_at,
    )

    return quote


@transaction.atomic
def reject_resource_offer(
    *,
    quote: SupplierQuote,
    rejected_by: Member,
    decision_reason: str = "",
) -> SupplierQuote:
    """Reject a submitted offer."""
    quote = SupplierQuote.objects.select_for_update().get(pk=quote.pk)

    if quote.decision_status != SupplierQuote.DecisionStatus.SUBMITTED:
        raise DomainError("只能拒绝状态为'已提交'的报价。")

    quote.decision_status = SupplierQuote.DecisionStatus.REJECTED
    quote.rejected_by = rejected_by
    quote.rejected_at = timezone.now()
    quote.decision_reason = decision_reason or ""
    quote.updated_at = timezone.now()
    quote.save(
        update_fields=[
            "decision_status", "rejected_by", "rejected_at",
            "decision_reason", "updated_at",
        ]
    )

    append_event(
        event_type=SystemEvent.EventType.SUPPLIER_OFFER_REJECTED,
        aggregate_type="SupplierQuote",
        aggregate_id=quote.quote_id,
        actor_member=rejected_by,
        payload_json=supplier_offer_payload(quote, action="rejected", actor=rejected_by),
        occurred_at=quote.rejected_at,
    )

    return quote


# ── receipt ──────────────────────────────────────────────────────────


@transaction.atomic
def record_offer_receipt(
    *,
    quote: SupplierQuote,
    received_by: Member,
    receipt_status: str,
    receipt_notes: str = "",
    simulation_day: int = 1,
) -> tuple[SupplierQuote, ResourceTransaction | None]:
    """Record receipt / inspection of an accepted offer.

    Requires all tiered approvals to be satisfied before receipt
    (accepted → finance approved if needed → governance confirmed if needed).
    """
    from .resource_services import record_resource_adjustment

    quote = SupplierQuote.objects.select_for_update().get(pk=quote.pk)

    if quote.decision_status != SupplierQuote.DecisionStatus.ACCEPTED:
        raise DomainError("只能对已采纳的报价进行验收。")

    if not quote_is_ready_for_receipt(quote):
        raise DomainError("审批未完成，请确认提案已全部通过并执行。")

    if quote.receipt_status != SupplierQuote.ReceiptStatus.PENDING:
        raise DomainError("该报价已验收过，不能重复验收。")

    if quote.delivered_at is not None:
        raise DomainError("该报价已交付过，不能重复验收。")

    valid_receipt = {v for v, _ in SupplierQuote.ReceiptStatus.choices}
    if receipt_status not in valid_receipt:
        raise DomainError("验收状态无效。")

    if receipt_status == SupplierQuote.ReceiptStatus.PENDING:
        raise DomainError("待验收不能作为验收结果提交。")

    if receipt_status == SupplierQuote.ReceiptStatus.PARTIAL:
        raise DomainError("暂不支持部分验收。")

    now = timezone.now()
    txn = None
    event_type = None

    if receipt_status == SupplierQuote.ReceiptStatus.ACCEPTED:
        operator = {
            "actor_id": received_by.member_no,
            "display_name": received_by.display_name or received_by.member_no,
            "role": "governance_principal",
        }
        reason = (
            f"报价 {quote.quote_id} 验收"
            + (f"：{receipt_notes}" if receipt_notes else "")
        )

        _resource, _event, txn = record_resource_adjustment(
            resource=quote.resource,
            delta=quote.available_quantity,
            operator=operator,
            reason=reason,
            replenishment_method=Resource.ReplenishmentMethod.PURCHASE,
            simulation_day=simulation_day,
        )

        txn.related_supplier_quote = quote
        txn.save(update_fields=["related_supplier_quote"])
        event_type = SystemEvent.EventType.SUPPLIER_OFFER_RECEIPT_ACCEPTED
    else:
        event_type = SystemEvent.EventType.SUPPLIER_OFFER_RECEIPT_REJECTED

    quote.receipt_status = receipt_status
    quote.received_by = received_by
    quote.delivered_at = now
    quote.receipt_notes = receipt_notes or ""
    quote.updated_at = now
    quote.save(
        update_fields=[
            "receipt_status", "received_by", "delivered_at",
            "receipt_notes", "updated_at",
        ]
    )

    append_event(
        event_type=event_type,
        aggregate_type="SupplierQuote",
        aggregate_id=quote.quote_id,
        actor_member=received_by,
        payload_json=supplier_offer_payload(quote, action=receipt_status, actor=received_by),
        occurred_at=quote.delivered_at,
    )

    return quote, txn


# ── payment / completion + credential ────────────────────────────────


@transaction.atomic
def mark_offer_paid_or_donated(
    *,
    quote: SupplierQuote,
    actor: Member,
) -> SupplierQuote:
    """Mark an accepted offer as paid (quote) or donation-completed (donation).

    After marking paid / fulfilled, a ``provider_delivery_completed``
    credential is issued and ``decision_status`` is set to ``fulfilled``.
    """
    quote = SupplierQuote.objects.select_for_update().get(pk=quote.pk)

    if quote.decision_status != SupplierQuote.DecisionStatus.ACCEPTED:
        raise DomainError("只能对已采纳的报价标记付款/捐赠完成。")

    if quote.decision_status == SupplierQuote.DecisionStatus.FULFILLED:
        raise DomainError("该报价已完成履约。")

    if quote.receipt_status != SupplierQuote.ReceiptStatus.ACCEPTED:
        raise DomainError("未验收通过前不能标记付款/捐赠完成。")

    if quote.offer_type == SupplierQuote.OfferType.QUOTE:
        if quote.payment_status == SupplierQuote.PaymentStatus.PAID:
            raise DomainError("该报价已标记为已付款。")
        quote.payment_status = SupplierQuote.PaymentStatus.PAID
        quote.paid_at = timezone.now()
    else:
        quote.payment_status = SupplierQuote.PaymentStatus.NOT_REQUIRED
        quote.paid_at = timezone.now()

    quote.updated_at = timezone.now()

    # ── issue delivery-completed credential (idempotent) ──
    if quote.performance_credential_id is None:
        if quote.submitted_by is None:
            raise DomainError("无法向缺失提交人的报价发放履约凭证。")

        ensure_builtin_credential_templates()
        template = CredentialTemplate.objects.get(code="provider_delivery_completed")
        credential = issue_credential(
            template=template,
            member=quote.submitted_by,
            dedupe_key=f"supplier_quote:{quote.quote_id}",
            source_type=CredentialGrant.SourceType.EARNED,
            issued_by=actor,
            metadata={
                "quote_id": quote.quote_id,
                "resource_id": quote.resource_id,
                "quantity": str(quote.available_quantity),
                "unit_price": str(quote.unit_price),
                "offer_type": quote.offer_type,
                "receipt_status": quote.receipt_status,
                "payment_status": quote.payment_status,
            },
        )
        quote.performance_credential = credential

    quote.decision_status = SupplierQuote.DecisionStatus.FULFILLED

    quote.save(
        update_fields=[
            "payment_status", "paid_at", "updated_at",
            "performance_credential", "decision_status",
        ]
    )

    append_event(
        event_type=SystemEvent.EventType.SUPPLIER_OFFER_COMPLETED,
        aggregate_type="SupplierQuote",
        aggregate_id=quote.quote_id,
        actor_member=actor,
        payload_json=supplier_offer_payload(quote, action="completed", actor=actor),
        occurred_at=quote.paid_at,
    )

    return quote
