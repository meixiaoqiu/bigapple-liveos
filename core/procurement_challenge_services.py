"""Public procurement challenge / counter-offer services."""

from decimal import Decimal
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from .event_ledger import append_event
from .event_payloads import _public_event_payload, _public_ref
from .exceptions import DomainError
from .models import (
    Member,
    ProcurementChallenge,
    SupplierQuote,
    SystemEvent,
)


def submit_procurement_challenge(
    *,
    quote: SupplierQuote,
    submitted_by: Member,
    challenge_type: str,
    public_reason: str,
    proposed_unit_price: Decimal | None = None,
    proposed_quantity: Decimal | None = None,
) -> ProcurementChallenge:
    """Submit a public challenge against a quote."""
    if not public_reason:
        raise DomainError("质疑理由不能为空。")

    if challenge_type not in {v for v, _ in ProcurementChallenge.ChallengeType.choices}:
        raise DomainError("质疑类型无效。")

    if challenge_type == ProcurementChallenge.ChallengeType.LOWER_PRICE:
        if quote.offer_type == SupplierQuote.OfferType.DONATION:
            raise DomainError("捐赠报价不支持更低价格质疑。")
        if proposed_unit_price is None:
            raise DomainError("更低价格质疑必须提供建议单价。")
        if proposed_unit_price < 0:
            raise DomainError("建议单价不能为负数。")
        if proposed_unit_price >= quote.unit_price:
            raise DomainError("建议单价必须低于原报价。")

    ch = ProcurementChallenge.objects.create(
        challenge_id=f"challenge-{uuid4().hex[:12]}",
        quote=quote,
        submitted_by=submitted_by,
        challenge_type=challenge_type,
        status=ProcurementChallenge.Status.SUBMITTED,
        public_reason=public_reason,
        proposed_unit_price=proposed_unit_price,
        proposed_quantity=proposed_quantity,
        created_at=timezone.now(),
        updated_at=timezone.now(),
    )

    append_event(
        event_type=SystemEvent.EventType.PROCUREMENT_CHALLENGE_SUBMITTED,
        aggregate_type="ProcurementChallenge",
        aggregate_id=ch.challenge_id,
        actor_member=submitted_by,
        payload_json=_public_event_payload(
            subject_type="procurement_challenge",
            subject_ref=_public_ref("challenge", ch.challenge_id),
            subject_label=f"质疑 {ch.challenge_id}",
            action="submitted",
            stage="submitted",
            summary=f"对报价 {quote.quote_id} 提出 {ch.get_challenge_type_display()}。",
            public_facts={
                "challenge_id": ch.challenge_id,
                "quote_id": quote.quote_id,
                "challenge_type": challenge_type,
                "public_reason": public_reason,
            },
        ),
        occurred_at=ch.created_at,
    )
    return ch


@transaction.atomic
def review_procurement_challenge(
    *,
    challenge: ProcurementChallenge,
    reviewed_by: Member,
    new_status: str,
    review_reason: str = "",
) -> ProcurementChallenge:
    """Accept, reject or resolve a challenge (governance/finance only)."""
    if new_status not in {
        ProcurementChallenge.Status.ACCEPTED,
        ProcurementChallenge.Status.REJECTED,
        ProcurementChallenge.Status.RESOLVED,
    }:
        raise DomainError("无效的质疑处理状态。")

    challenge = ProcurementChallenge.objects.select_for_update().get(pk=challenge.pk)
    challenge.status = new_status
    challenge.reviewed_by = reviewed_by
    challenge.reviewed_at = timezone.now()
    challenge.review_reason = review_reason
    challenge.updated_at = timezone.now()
    challenge.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_reason", "updated_at"])

    append_event(
        event_type=SystemEvent.EventType.PROCUREMENT_CHALLENGE_REVIEWED,
        aggregate_type="ProcurementChallenge",
        aggregate_id=challenge.challenge_id,
        actor_member=reviewed_by,
        payload_json=_public_event_payload(
            subject_type="procurement_challenge",
            subject_ref=_public_ref("challenge", challenge.challenge_id),
            subject_label=f"质疑 {challenge.challenge_id}",
            action="reviewed",
            stage=new_status,
            summary=f"质疑 {challenge.challenge_id} 已处理为 {new_status}。",
            public_facts={
                "challenge_id": challenge.challenge_id,
                "quote_id": challenge.quote_id,
                "new_status": new_status,
            },
        ),
        occurred_at=challenge.reviewed_at,
    )
    return challenge
