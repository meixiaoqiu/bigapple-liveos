"""Finance lifecycle services — expense claims, reviews, payments."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.utils.dateparse import parse_date
from django.utils import timezone

from .db import atomic_for_model
from .exceptions import DomainError
from .event_ledger import append_event
from .finance_setup import FINANCE_PAY_PERMISSION, FINANCE_REVIEW_PERMISSION, FINANCE_VIEW_PRIVATE_PERMISSION
from .models import (
    ExpenseClaim, FinanceReview, FinanceTransaction,
    Member, SystemEvent,
)
from .models.events import Event


def _member_has_permission(member: Member, code: str) -> bool:
    from core.permission_services import member_has_permission as _mhp
    return _mhp(member, code)


def _event_suffix(value: str) -> str:
    return value.rsplit("-", 1)[-1]


def _write_public_event(event_id: str, title: str, summary: str, *, payload: dict) -> None:
    Event.objects.create(
        event_id=event_id, event_type=Event.EventType.GOVERNANCE, visibility=Event.Visibility.PUBLIC,
        title=title, summary=summary, simulation_day=1,
        occurred_at=timezone.now(), generated_by=Event.GeneratedBy.LIVE_OS,
        severity=Event.Severity.INFO, payload=payload,
    )


def _append_event(**kwargs):
    return append_event(**kwargs)


def _normalise_amount(amount) -> Decimal:
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise DomainError("报销金额格式无效。") from exc
    if value <= 0:
        raise DomainError("报销金额必须大于 0。")
    return value.quantize(Decimal("0.01"))


def _normalise_expense_date(expense_date):
    if hasattr(expense_date, "year") and hasattr(expense_date, "month") and hasattr(expense_date, "day"):
        return expense_date
    parsed = parse_date(str(expense_date or ""))
    if parsed is None:
        raise DomainError("支出日期格式无效。")
    return parsed


def _normalise_currency(currency: str) -> str:
    value = str(currency or "CNY").strip().upper()
    if not value or len(value) > 8:
        raise DomainError("货币代码无效。")
    return value


@atomic_for_model(ExpenseClaim)
def submit_expense_claim(
    *, claimant_member: Member, title: str, description: str,
    amount, currency: str = "CNY", expense_date, vendor: str = "",
    category: str = "other",
) -> ExpenseClaim:
    """Submit a new reimbursement claim.

    Any non-SUSPENDED/non-EXITED member can submit.
    """
    if claimant_member.status in {Member.Status.SUSPENDED, Member.Status.EXITED}:
        raise DomainError("成员状态已停用，不能提交报销申请。")
    if category not in ExpenseClaim.Category.values:
        raise DomainError("报销类别无效。")
    amount_value = _normalise_amount(amount)
    expense_date_value = _normalise_expense_date(expense_date)
    currency_value = _normalise_currency(currency)
    claim = ExpenseClaim.objects.create(
        claimant_member=claimant_member, title=title, description=description,
        amount=amount_value, currency=currency_value, expense_date=expense_date_value,
        vendor=vendor, category=category,
    )
    from .event_payloads import expense_claim_payload
    payload = expense_claim_payload(claim)
    _write_public_event(
        f"expense-claim-submitted-{claim.claim_id}",
        "收到报销申请",
        f"{claimant_member.display_name or claimant_member.member_no} 提交报销《{title}》{amount_value} {currency_value}。",
        payload=payload["public_facts"],
    )
    _append_event(
        event_type=SystemEvent.EventType.EXPENSE_CLAIM_SUBMITTED, aggregate_type="ExpenseClaim",
        aggregate_id=claim.claim_id, actor_member=claimant_member,
        payload_json=payload,
    )
    return claim


@atomic_for_model(FinanceReview)
def review_expense_claim(
    *, claim: ExpenseClaim, reviewer_member: Member,
    decision: str, reason: str = "",
) -> FinanceReview:
    """Review an expense claim (approve or reject).

    *reviewer_member* must hold finance.review permission.
    Cannot review own claim.
    Rejection requires a reason.
    """
    if not _member_has_permission(reviewer_member, FINANCE_REVIEW_PERMISSION):
        raise DomainError("只有财务审核成员才能审核报销。")
    if reviewer_member.pk == claim.claimant_member_id:
        raise DomainError("申请人不能审核自己的报销。")
    if claim.status not in {ExpenseClaim.Status.SUBMITTED, ExpenseClaim.Status.UNDER_REVIEW}:
        raise DomainError("只有已提交或审核中的报销可以审核。")
    if decision not in FinanceReview.Decision.values:
        raise DomainError("审核决定无效。")
    if decision == FinanceReview.Decision.REJECTED and not reason.strip():
        raise DomainError("拒绝报销必须填写理由。")

    claim.status = (
        ExpenseClaim.Status.APPROVED if decision == FinanceReview.Decision.APPROVED
        else ExpenseClaim.Status.REJECTED
    )
    claim.save(update_fields=["status", "updated_at"])
    review = FinanceReview.objects.create(
        claim=claim, reviewer_member=reviewer_member,
        decision=decision, reason=reason,
    )
    from .event_payloads import finance_review_payload
    payload = finance_review_payload(review)
    _write_public_event(
        f"expense-claim-reviewed-{claim.claim_id}-{_event_suffix(review.review_id)}",
        "报销已审核",
        f"{reviewer_member.display_name or reviewer_member.member_no} {review.get_decision_display()}了《{claim.title}》。",
        payload=payload["public_facts"],
    )
    _append_event(
        event_type=SystemEvent.EventType.EXPENSE_CLAIM_REVIEWED, aggregate_type="FinanceReview",
        aggregate_id=review.review_id, actor_member=reviewer_member,
        payload_json=payload,
    )
    return review


@atomic_for_model(FinanceTransaction)
def mark_expense_claim_paid(
    *, claim: ExpenseClaim, payer_member: Member,
) -> FinanceTransaction:
    """Mark an approved claim as paid and record a transaction.

    *payer_member* must hold finance.pay permission.
    Cannot pay your own claim.
    Only APPROVED claims can be marked paid.
    """
    if not _member_has_permission(payer_member, FINANCE_PAY_PERMISSION):
        raise DomainError("只有财务付款成员才能标记付款。")
    if payer_member.pk == claim.claimant_member_id:
        raise DomainError("申请人不能给自己的报销标记付款。")
    if claim.status != ExpenseClaim.Status.APPROVED:
        raise DomainError("只有已批准的报销才能标记付款。")

    claim.status = ExpenseClaim.Status.PAID
    claim.save(update_fields=["status", "updated_at"])
    txn = FinanceTransaction.objects.create(
        transaction_type=FinanceTransaction.TransactionType.REIMBURSEMENT,
        amount=claim.amount, currency=claim.currency,
        direction=FinanceTransaction.Direction.OUT,
        summary=f"报销：{claim.title}", occurred_at=timezone.now(),
        recorded_by=payer_member, claim=claim,
    )
    from .event_payloads import finance_transaction_payload
    payload = finance_transaction_payload(txn)
    _write_public_event(
        f"expense-claim-paid-{claim.claim_id}-{_event_suffix(txn.transaction_id)}",
        "报销已付款",
        f"《{claim.title}》{claim.amount} {claim.currency} 已支付。",
        payload=payload["public_facts"],
    )
    _append_event(
        event_type=SystemEvent.EventType.EXPENSE_CLAIM_PAID, aggregate_type="FinanceTransaction",
        aggregate_id=txn.transaction_id, actor_member=payer_member,
        payload_json=payload,
    )
    return txn


@atomic_for_model(ExpenseClaim)
def withdraw_expense_claim(
    *, claim: ExpenseClaim, member: Member,
) -> ExpenseClaim:
    """Withdraw own claim. Only SUBMITTED / UNDER_REVIEW can be withdrawn."""
    if member.pk != claim.claimant_member_id:
        raise DomainError("只能撤回自己的报销申请。")
    if claim.status not in {ExpenseClaim.Status.SUBMITTED, ExpenseClaim.Status.UNDER_REVIEW}:
        raise DomainError("只有已提交或审核中的报销可以撤回。")
    claim.status = ExpenseClaim.Status.WITHDRAWN
    claim.save(update_fields=["status", "updated_at"])
    _write_public_event(
        f"expense-claim-withdrawn-{claim.claim_id}",
        "报销已撤回",
        f"{member.display_name or member.member_no} 撤回了《{claim.title}》。",
        payload={
            "source": "finance",
            "claim_id": claim.claim_id,
            "title": claim.title,
            "amount": str(claim.amount),
            "currency": claim.currency,
            "status": claim.status,
            "status_label": claim.get_status_display(),
            "claimant_public_name": member.display_name or member.member_no,
            "action_type": "withdrawn",
        },
    )
    return claim
