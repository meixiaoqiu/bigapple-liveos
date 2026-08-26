"""Authoritative credit-system services.

All credit mutations pass through services in this module.  Views
and management commands MUST NOT directly create or modify
``CreditTransaction`` rows; they must call the service functions below.

Flow
----

::

    governance approves issuance
      → issue_credits_to_pool()      [issuance_pool += amount]
      → lock_task_credit_budget()    [issuance_pool -= amount,
                                       task_locked  += amount]
      → review_task() accepted
        → post_task_reward_credit_transaction()
                                      [task_locked -= amount,
                                       member       += amount]
      → unlock_unused_task_credit_budget()
                                      [task_locked -= remainder,
                                       issuance_pool+= remainder]
"""

from __future__ import annotations

from uuid import uuid4

from django.db import IntegrityError, router, transaction
from django.db.models import Sum
from django.utils import timezone

from .db import atomic_for_model
from .event_ledger import append_event
from .event_payloads import _public_event_payload
from .exceptions import DomainError
from .models import (
    CreditAccount,
    CreditTransaction,
    LedgerEntry,
    Member,
    MerchantProfile,
    MerchantSettlementRecord,
    RedemptionOrder,
    SystemEvent,
    Task,
)


# ── helpers ──────────────────────────────────────────────────────────


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def _credit_balance_for_qs(qs) -> int:
    return qs.filter(status=CreditTransaction.Status.POSTED).aggregate(
        total=Sum("amount")
    )["total"] or 0


def _normalise_idem_key(raw: str | None) -> str | None:
    if raw is None:
        return None
    stripped = raw.strip()
    return stripped if stripped else None


def _account_id(acct: CreditAccount | None) -> str | None:
    """Return the string PK of *acct*, or None."""
    return acct.account_id if acct is not None else None


def _task_id(task: Task | None) -> str | None:
    return task.task_id if task is not None else None


def _ledger_entry_id(entry: LedgerEntry | None) -> str | None:
    return entry.ledger_entry_id if entry is not None else None


def _assert_idempotent_match(existing: CreditTransaction, **expected):
    mismatches: list[str] = []
    for field, expected_val in expected.items():
        actual_val = getattr(existing, field, None)
        if actual_val != expected_val:
            mismatches.append(f"{field} mismatch")
    if mismatches:
        raise DomainError(
            f"幂等键已被不同积分交易使用: {'; '.join(mismatches)}。"
        )


# ── account management ───────────────────────────────────────────────


def ensure_system_accounts() -> dict[str, CreditAccount]:
    """Idempotently create the five system-level credit accounts."""
    accounts: dict[str, CreditAccount] = {}
    for acct_type, _label in CreditAccount.Type.choices:
        if acct_type == CreditAccount.Type.MEMBER:
            continue
        account, _ = CreditAccount.objects.get_or_create(
            account_type=acct_type,
            member=None,
            defaults={
                "account_id": f"acct-sys-{acct_type}",
                "status": CreditAccount.Status.ACTIVE,
                "metadata": {"label": dict(CreditAccount.Type.choices)[acct_type]},
                "created_at": timezone.now(),
                "updated_at": timezone.now(),
            },
        )
        accounts[acct_type] = account
    return accounts


def get_or_create_member_credit_account(member: Member) -> CreditAccount:
    """Return the 1:1 member credit account, creating it if necessary.

    Uses ``get_or_create`` with exact filter to avoid the TOCTOU
    window between ``.first()`` + ``.create()``.  ``IntegrityError``
    from a concurrent create is caught and retried.
    """
    account, _created = CreditAccount.objects.get_or_create(
        account_type=CreditAccount.Type.MEMBER,
        member=member,
        defaults={
            "account_id": f"acct-member-{member.member_no}",
            "status": CreditAccount.Status.ACTIVE,
            "created_at": timezone.now(),
            "updated_at": timezone.now(),
        },
    )
    return account


# ── balance queries (read-only) ─────────────────────────────────────


def credit_balance(account: CreditAccount) -> int:
    """Non-locking snapshot of *account*'s posted balance.

    Authoritative write paths (transfer, redemption) MUST lock the
    account with ``select_for_update()`` before calling this function
    to prevent stale-read races.
    """
    inbound = _credit_balance_for_qs(
        CreditTransaction.objects.filter(target_account=account))
    outbound = _credit_balance_for_qs(
        CreditTransaction.objects.filter(source_account=account))
    return inbound - outbound


def member_credit_balance(member: Member) -> int:
    """Current balance of *member* — derived from posted transactions."""
    account = CreditAccount.objects.filter(
        account_type=CreditAccount.Type.MEMBER, member=member,
    ).first()
    if account is None:
        return 0
    return credit_balance(account)


def member_available_credit_balance(member: Member) -> int:
    """Credits available for active use (freeze/transfer/redemption).

    Currently identical to ``member_credit_balance`` because
    ``consume`` (freeze) already moves credits out; when
    ``balance <= 0`` all active actions are rejected.
    """
    return member_credit_balance(member)


def member_lifetime_contribution(member: Member) -> int:
    """Total credits earned from task rewards — never reduced by spend."""
    account = CreditAccount.objects.filter(
        account_type=CreditAccount.Type.MEMBER, member=member,
    ).first()
    if account is None:
        return 0
    return _credit_balance_for_qs(
        CreditTransaction.objects.filter(
            transaction_type=CreditTransaction.Type.TASK_REWARD,
            target_account=account,
        )
    )


def _emit_credit_event(txn: CreditTransaction):
    """Append a SystemEvent for a posted CreditTransaction.

    This MUST succeed — if ``append_event`` fails the calling
    transaction should roll back (this function does NOT catch
    exceptions).

    Privacy: the public payload intentionally omits per-transaction
    ``transaction_id``, ``amount``, ``reason`` and ``idempotency_key``.
    Those are only recorded in ``private_commitments``.
    ``aggregate_id=txn.transaction_id`` is stored on the SystemEvent
    row itself, not in the public payload.
    """
    append_event(
        event_type=SystemEvent.EventType.CREDIT_ADJUSTED,
        aggregate_type="CreditTransaction",
        aggregate_id=txn.transaction_id,
        payload_json=_public_event_payload(
            subject_type="credit_transaction",
            subject_ref="credit-ledger:posted",
            subject_label="积分账本记录",
            action=txn.transaction_type,
            stage="posted",
            summary=f"{txn.get_transaction_type_display()}",
            public_facts={
                "txn_type": txn.transaction_type,
            },
            private_commitments=[
                {"name": "amount", "present": True, "reason": "单笔积分金额不在公开摘要中展示"},
                {"name": "reason", "present": bool(txn.reason), "reason": "交易原因"},
                {"name": "metadata", "present": bool(txn.metadata), "reason": "元数据"},
                {"name": "idempotency_key", "present": bool(txn.idempotency_key), "reason": "幂等键"},
            ],
        ),
        occurred_at=txn.created_at,
    )


# ── posting core ─────────────────────────────────────────────────────


@atomic_for_model(CreditTransaction)
def post_credit_transaction(
    *,
    transaction_type: str,
    amount: int,
    source_account: CreditAccount | None = None,
    target_account: CreditAccount | None = None,
    idempotency_key: str | None = None,
    related_task: Task | None = None,
    related_ledger_entry: LedgerEntry | None = None,
    related_event_id: str = "",
    initiated_by: Member | None = None,
    reviewed_by: Member | None = None,
    reason: str = "",
    metadata: dict | None = None,
    prev_hash: str = "",
    transaction_hash: str = "",
    created_at=None,
) -> CreditTransaction:
    """Create an authoritative ``CreditTransaction``.

    This is the sole write path for the double-entry credit ledger.
    Every call produces exactly one ``posted`` row (or returns an
    existing row for a matching *idempotency_key*).  A ``SystemEvent``
    is appended synchronously; if that fails the entire transaction
    rolls back.

    Idempotency: a non-null *idempotency_key* guarantees at most one
    row per key (DB unique + service-layer fast-path + IntegrityError
    savepoint).  Semantically inconsistent retries raise ``DomainError``.

    Negative balance is NOT validated here — upstream callers enforce
    business rules (e.g. transfers forbid going below zero, passive
    deductions allow it).
    """
    if amount <= 0:
        raise DomainError("积分数量必须为正数。")
    valid_types = {v for v, _ in CreditTransaction.Type.choices}
    if transaction_type not in valid_types:
        raise DomainError(f"无效的交易类型: {transaction_type}。")

    dedupe_key = _normalise_idem_key(idempotency_key)
    if dedupe_key is not None:
        existing = CreditTransaction.objects.filter(
            idempotency_key=dedupe_key, status=CreditTransaction.Status.POSTED,
        ).first()
        if existing is not None:
            _assert_idempotent_match(
                existing,
                transaction_type=transaction_type,
                amount=amount,
                source_account_id=_account_id(source_account),
                target_account_id=_account_id(target_account),
                related_task_id=_task_id(related_task),
                related_ledger_entry_id=_ledger_entry_id(related_ledger_entry),
            )
            return existing

    now = created_at or timezone.now()
    database = router.db_for_write(CreditTransaction)
    try:
        with transaction.atomic(using=database):
            txn = CreditTransaction.objects.using(database).create(
                transaction_id=_new_id("ct"),
                transaction_type=transaction_type,
                source_account=source_account,
                target_account=target_account,
                amount=amount,
                related_task=related_task,
                related_ledger_entry=related_ledger_entry,
                related_event_id=related_event_id,
                initiated_by=initiated_by,
                reviewed_by=reviewed_by,
                reason=reason,
                metadata=metadata or {},
                idempotency_key=dedupe_key,
                reverses_transaction=None,
                status=CreditTransaction.Status.POSTED,
                prev_hash=prev_hash or "",
                transaction_hash=transaction_hash or "",
                created_at=now,
            )
            _emit_credit_event(txn)
        return txn
    except IntegrityError:
        if dedupe_key is not None:
            existing = CreditTransaction.objects.filter(
                idempotency_key=dedupe_key, status=CreditTransaction.Status.POSTED,
            ).first()
            if existing is not None:
                _assert_idempotent_match(
                    existing,
                    transaction_type=transaction_type,
                    amount=amount,
                    source_account_id=_account_id(source_account),
                    target_account_id=_account_id(target_account),
                    related_task_id=_task_id(related_task),
                    related_ledger_entry_id=_ledger_entry_id(related_ledger_entry),
                )
                return existing
        raise DomainError("积分交易并发冲突，请重试。")


# ── issuance & budget ────────────────────────────────────────────────


def _pool(name: str) -> CreditAccount:
    acct = CreditAccount.objects.filter(account_type=name).first()
    if acct is None:
        raise DomainError(f"系统账户 {name} 不存在，请先调用 ensure_system_accounts()。")
    return acct


@atomic_for_model(CreditTransaction)
def issue_credits_to_pool(
    *,
    amount: int,
    reason: str,
    initiated_by: Member,
    reviewed_by: Member,
    idempotency_key: str | None = None,
) -> CreditTransaction:
    """Issue credits into the issuance pool (governance-approved)."""
    pool = _pool(CreditAccount.Type.ISSUANCE_POOL)
    return post_credit_transaction(
        transaction_type=CreditTransaction.Type.ISSUANCE,
        amount=amount,
        source_account=None,
        target_account=pool,
        reason=reason,
        initiated_by=initiated_by,
        reviewed_by=reviewed_by,
        idempotency_key=idempotency_key,
    )


def task_locked_credit_balance(task: Task) -> int:
    """Remaining locked budget for *task* — non-locking snapshot.

    locked = inflow to task_locked (LOCK txn with related_task=*task*)
    − outflow from task_locked (TASK_REWARD / UNLOCK with related_task=*task*)

    Callers that use this value for authority decisions (e.g.
    publish_task, unlock) should be inside a transaction that
    protects the underlying rows.
    """
    task_locked = _pool(CreditAccount.Type.TASK_LOCKED)
    locked_in = _credit_balance_for_qs(
        CreditTransaction.objects.filter(
            transaction_type=CreditTransaction.Type.LOCK,
            target_account=task_locked,
            related_task=task,
        )
    )
    rewards_out = _credit_balance_for_qs(
        CreditTransaction.objects.filter(
            transaction_type=CreditTransaction.Type.TASK_REWARD,
            source_account=task_locked,
            related_task=task,
        )
    )
    unlocks_out = _credit_balance_for_qs(
        CreditTransaction.objects.filter(
            transaction_type=CreditTransaction.Type.UNLOCK,
            source_account=task_locked,
            related_task=task,
        )
    )
    return locked_in - rewards_out - unlocks_out


@atomic_for_model(CreditTransaction)
def lock_task_credit_budget(
    *,
    task: Task,
    amount: int,
    reason: str,
    initiated_by: Member | None = None,
    idempotency_key: str | None = None,
) -> CreditTransaction:
    """Lock *amount* credits from the issuance pool for *task*.

    Idempotency: if *idempotency_key* matches an existing posted
    ``LOCK`` transaction, that row is returned immediately — pool
    balance is NOT re-checked.
    """
    dedupe_key = _normalise_idem_key(idempotency_key)
    pool = CreditAccount.objects.select_for_update().filter(
        account_type=CreditAccount.Type.ISSUANCE_POOL
    ).first()
    task_locked_acct = CreditAccount.objects.select_for_update().filter(
        account_type=CreditAccount.Type.TASK_LOCKED
    ).first()
    if pool is None or task_locked_acct is None:
        raise DomainError("任务预算系统账户不存在，请先调用 ensure_system_accounts()。")

    if dedupe_key is not None:
        existing = CreditTransaction.objects.filter(
            idempotency_key=dedupe_key,
            transaction_type=CreditTransaction.Type.LOCK,
            status=CreditTransaction.Status.POSTED,
        ).first()
        if existing is not None:
            _assert_idempotent_match(
                existing,
                transaction_type=CreditTransaction.Type.LOCK,
                amount=amount,
                source_account_id=pool.account_id,
                target_account_id=task_locked_acct.account_id,
                related_task_id=task.task_id,
            )
            return existing

    if credit_balance(pool) < amount:
        raise DomainError(
            f"发行池余额不足（当前 {credit_balance(pool)}，"
            f"需要锁定 {amount}）。"
        )
    return post_credit_transaction(
        transaction_type=CreditTransaction.Type.LOCK,
        amount=amount,
        source_account=pool,
        target_account=task_locked_acct,
        related_task=task,
        reason=reason,
        initiated_by=initiated_by,
        idempotency_key=dedupe_key,
    )


@atomic_for_model(CreditTransaction)
def unlock_unused_task_credit_budget(
    *,
    task: Task,
    amount: int,
    reason: str,
    initiated_by: Member | None = None,
    idempotency_key: str | None = None,
) -> CreditTransaction:
    """Return unused locked budget back to the issuance pool.

    Idempotency: if *idempotency_key* matches an existing posted
    ``UNLOCK`` transaction, that row is returned immediately.
    """
    dedupe_key = _normalise_idem_key(idempotency_key)
    task_locked_acct = _pool(CreditAccount.Type.TASK_LOCKED)
    pool = _pool(CreditAccount.Type.ISSUANCE_POOL)

    if dedupe_key is not None:
        existing = CreditTransaction.objects.filter(
            idempotency_key=dedupe_key,
            transaction_type=CreditTransaction.Type.UNLOCK,
            status=CreditTransaction.Status.POSTED,
        ).first()
        if existing is not None:
            _assert_idempotent_match(
                existing,
                transaction_type=CreditTransaction.Type.UNLOCK,
                amount=amount,
                source_account_id=task_locked_acct.account_id,
                target_account_id=pool.account_id,
                related_task_id=task.task_id,
            )
            return existing

    remaining = task_locked_credit_balance(task)
    if amount <= 0 or amount > remaining:
        raise DomainError(
            f"退回金额 {amount} 超过该任务剩余锁定预算 {remaining}。"
        )
    return post_credit_transaction(
        transaction_type=CreditTransaction.Type.UNLOCK,
        amount=amount,
        source_account=task_locked_acct,
        target_account=pool,
        related_task=task,
        reason=reason,
        initiated_by=initiated_by,
        idempotency_key=dedupe_key,
    )


# ── transfer ─────────────────────────────────────────────────────────


@atomic_for_model(CreditTransaction)
def transfer_member_credits(
    *,
    from_member: Member,
    to_member: Member,
    amount: int,
    reason: str = "",
    initiated_by: Member | None = None,
    idempotency_key: str | None = None,
) -> CreditTransaction:
    """Transfer credits from one member to another.

    Creates an authoritative ``CreditTransaction(transfer)``.  The
    caller's account is locked with ``select_for_update()`` so
    concurrent transfers cannot overdraw.

    * ``from_member`` must have ``balance > 0`` and
      ``balance - amount >= 0`` — active transfers are NOT allowed to
      push the sender into negative.
    * ``to_member`` balance may become positive from zero or negative.
    * Idempotency: a matching posted transfer returns the existing row;
      a key-reuse with different semantics raises ``DomainError``.
    * A ``SystemEvent`` is appended; on failure the transaction rolls
      back.
    """
    if amount <= 0:
        raise DomainError("转账积分数量必须为正数。")
    if from_member.pk == to_member.pk:
        raise DomainError("不能向自己转账。")

    from_account = get_or_create_member_credit_account(from_member)
    to_account = get_or_create_member_credit_account(to_member)

    # Idempotency check BEFORE balance validation
    dedupe_key = _normalise_idem_key(idempotency_key)
    if dedupe_key is not None:
        existing = CreditTransaction.objects.filter(
            idempotency_key=dedupe_key,
            transaction_type=CreditTransaction.Type.TRANSFER,
            status=CreditTransaction.Status.POSTED,
        ).first()
        if existing is not None:
            _assert_idempotent_match(
                existing,
                transaction_type=CreditTransaction.Type.TRANSFER,
                amount=amount,
                source_account_id=_account_id(from_account),
                target_account_id=_account_id(to_account),
            )
            return existing

    # Lock account to prevent concurrent overdraw
    from_account = CreditAccount.objects.select_for_update().get(pk=from_account.pk)
    current = credit_balance(from_account)
    if current <= 0:
        raise DomainError("当前余额小于等于 0，不能主动转出积分。")
    if current - amount < 0:
        raise DomainError("余额不足以完成该主动转账。")
    return post_credit_transaction(
        transaction_type=CreditTransaction.Type.TRANSFER,
        source_account=from_account,
        target_account=to_account,
        amount=amount,
        reason=reason or "自由转账",
        initiated_by=initiated_by or from_member,
        idempotency_key=idempotency_key,
    )


# ── passive deduction ────────────────────────────────────────────────


@atomic_for_model(CreditTransaction)
def passive_deduct_member_credits(
    *,
    member: Member,
    amount: int,
    reason: str,
    initiated_by: Member | None = None,
    idempotency_key: str | None = None,
) -> CreditTransaction:
    """Passively deduct credits (correction → burn).

    Unlike active transfers, **negative balance is permitted**: this
    models governance-imposed penalties or mandatory charges.

    Creates an authoritative ``CreditTransaction(correction)``.
    Idempotency is enforced by key.  A ``SystemEvent`` is appended;
    on failure the transaction rolls back.
    """
    if amount <= 0:
        raise DomainError("扣减积分数量必须为正数。")
    member_account = get_or_create_member_credit_account(member)
    burn_account = _pool(CreditAccount.Type.BURN)
    return post_credit_transaction(
        transaction_type=CreditTransaction.Type.CORRECTION,
        source_account=member_account,
        target_account=burn_account,
        amount=amount,
        reason=reason,
        initiated_by=initiated_by,
        idempotency_key=idempotency_key,
    )


# ── reversal ─────────────────────────────────────────────────────────


@atomic_for_model(CreditTransaction)
def reverse_credit_transaction(
    *,
    original: CreditTransaction,
    reason: str,
    initiated_by: Member | None = None,
    idempotency_key: str | None = None,
) -> CreditTransaction:
    """Create an authoritative reversal — mirror the original with
    swapped source/target.

    The original transaction is NOT deleted or modified (only
    referenced via ``reverses_transaction``).  A reversal is itself a
    posted ``CreditTransaction(reversal)`` and can be reversed again.

    Only one posted reversal may exist for a given *original*.
    Idempotency + ``SystemEvent`` semantics match
    ``post_credit_transaction``.
    """
    original = CreditTransaction.objects.select_for_update().get(pk=original.pk)
    if CreditTransaction.objects.filter(
        reverses_transaction=original, status=CreditTransaction.Status.POSTED,
    ).exists():
        raise DomainError("该交易已被冲正。")
    reversal = post_credit_transaction(
        transaction_type=CreditTransaction.Type.REVERSAL,
        source_account=original.target_account,
        target_account=original.source_account,
        amount=original.amount,
        reason=reason,
        initiated_by=initiated_by,
        idempotency_key=idempotency_key,
    )
    reversal.reverses_transaction = original
    reversal.save(update_fields=["reverses_transaction"])
    return reversal


# ── task reward (from locked budget) ─────────────────────────────────


@atomic_for_model(CreditTransaction)
def post_task_reward_credit_transaction(
    *,
    task: Task,
    member: Member,
    amount: int,
    ledger_entry: LedgerEntry,
    reviewed_by: Member | None = None,
    reason: str = "",
    allow_unbudgeted_genesis: bool = False,
) -> CreditTransaction:
    """Reward *member* from this task's locked budget.

    The **default path** draws from the ``TASK_LOCKED`` account and
    requires ``task_locked_credit_balance(task) >= amount``.

    When *allow_unbudgeted_genesis* is ``True`` (internal bootstrap
    only), the reward is drawn directly from the issuance pool and
    tagged with ``genesis_unbudgeted=true`` in metadata.
    """
    member_account = get_or_create_member_credit_account(member)

    # Idempotency: return existing reward before checking budget.
    idem_key = f"task-reward:{ledger_entry.ledger_entry_id}"
    task_locked_acct = None if allow_unbudgeted_genesis else _pool(CreditAccount.Type.TASK_LOCKED)
    issuance_pool = _pool(CreditAccount.Type.ISSUANCE_POOL)

    existing = CreditTransaction.objects.filter(
        idempotency_key=idem_key,
        transaction_type=CreditTransaction.Type.TASK_REWARD,
        status=CreditTransaction.Status.POSTED,
    ).first()
    if existing is not None:
        # Determine expected source
        if allow_unbudgeted_genesis:
            expected_source = issuance_pool.account_id
        else:
            expected_source = task_locked_acct.account_id
        _assert_idempotent_match(
            existing,
            transaction_type=CreditTransaction.Type.TASK_REWARD,
            amount=amount,
            source_account_id=expected_source,
            target_account_id=member_account.account_id,
            related_task_id=task.task_id,
            related_ledger_entry_id=ledger_entry.ledger_entry_id,
        )
        if allow_unbudgeted_genesis:
            if (existing.metadata or {}).get("genesis_unbudgeted") is not True:
                raise DomainError(
                    "幂等键已被不同积分交易使用: "
                    "genesis_unbudgeted metadata mismatch。"
                )
        return existing

    if allow_unbudgeted_genesis:
        # ── genesis exception: draw from issuance pool ─────────
        meta: dict = {
            "genesis_unbudgeted": True,
            "genesis_governance": True,
            "self_review": reviewed_by.pk == member.pk if reviewed_by else None,
            "public_audit_required": True,
            "genesis_reason": reason or "创世期无预算发放",
            "pool_balance_at_reward": credit_balance(issuance_pool),
        }
        source = issuance_pool
    else:
        # ── normal path: locked budget ──
        locked = task_locked_credit_balance(task)
        if locked < amount:
            raise DomainError(
                f"任务锁定预算不足（当前剩余 {locked}，需要 {amount}）；"
                "请先从发行池锁定预算。"
            )
        meta = {}
        source = task_locked_acct

    return post_credit_transaction(
        transaction_type=CreditTransaction.Type.TASK_REWARD,
        source_account=source,
        target_account=member_account,
        amount=amount,
        related_task=task,
        related_ledger_entry=ledger_entry,
        related_event_id=ledger_entry.related_event_id or "",
        reason=reason or "任务验收奖励",
        reviewed_by=reviewed_by,
        initiated_by=reviewed_by,
        idempotency_key=idem_key,
        metadata=meta,
    )


# ── redemption orders ────────────────────────────────────────────────


@atomic_for_model(RedemptionOrder)
def create_redemption_order(
    *,
    member: Member,
    credit_amount: int,
    item_type: str = RedemptionOrder.ItemType.OTHER,
    title: str = "",
    reason: str = "",
    original_amount_rmb=None,
    cash_amount_rmb=None,
    related_task: Task | None = None,
    resource_id: str = "",
    item_snapshot: dict | None = None,
    finance_treatment_ref: str = "",
    merchant: MerchantProfile | None = None,
    idempotency_key: str | None = None,
    created_by: Member | None = None,
) -> tuple[RedemptionOrder, CreditTransaction]:
    """Create a redemption order and freeze *credit_amount* credits.

    If *merchant* is provided it must be an active cash_settlement_merchant.
    member_micro_merchant settlements use transfer, not RedemptionOrder.
    """
    if credit_amount <= 0:
        raise DomainError("兑换积分数量必须为正数。")

    valid_types = {v for v, _ in RedemptionOrder.ItemType.choices}
    if item_type not in valid_types:
        raise DomainError(f"无效的兑换项目类型: {item_type}。")

    if merchant is not None:
        if merchant.merchant_type == MerchantProfile.Type.MEMBER_MICRO:
            raise DomainError(
                "成员微创业商户收款应使用自由转账 (POST /members/.../credit-transfers)，"
                "不走兑换订单。"
            )
        if merchant.status != MerchantProfile.Status.ACTIVE:
            raise DomainError("指定商户当前非营业中状态，无法创建兑换订单。")
        if merchant.merchant_type != MerchantProfile.Type.CASH_SETTLEMENT:
            raise DomainError("仅现金结算商户支持兑换订单。")

    dedupe_key = _normalise_idem_key(idempotency_key)
    if dedupe_key is not None:
        existing_txn = CreditTransaction.objects.filter(
            idempotency_key=dedupe_key,
            transaction_type=CreditTransaction.Type.CONSUME,
            status=CreditTransaction.Status.POSTED,
        ).first()
        if existing_txn is not None:
            order_id = (existing_txn.metadata or {}).get("order_id", "")
            if order_id:
                order = RedemptionOrder.objects.filter(order_id=order_id).first()
                if order is not None:
                    _assert_idempotent_match(
                        existing_txn,
                        transaction_type=CreditTransaction.Type.CONSUME,
                        amount=credit_amount,
                        source_account_id=_account_id(
                            get_or_create_member_credit_account(member)),
                        target_account_id=_pool(CreditAccount.Type.FROZEN).account_id,
                    )
                    if order.member_id != member.pk:
                        raise DomainError("幂等键已被不同兑换订单使用: member mismatch。")
                    if order.credit_amount != credit_amount:
                        raise DomainError("幂等键已被不同兑换订单使用: credit_amount mismatch。")
                    if order.item_type != item_type:
                        raise DomainError("幂等键已被不同兑换订单使用: item_type mismatch。")
                    if order.related_task_id != (related_task.pk if related_task else None):
                        raise DomainError("幂等键已被不同兑换订单使用: related_task mismatch。")
                    if order.resource_id != (resource_id or ""):
                        raise DomainError("幂等键已被不同兑换订单使用: resource_id mismatch。")
                    if order.item_snapshot != (item_snapshot or {}):
                        raise DomainError("幂等键已被不同兑换订单使用: item_snapshot mismatch。")
                    if order.finance_treatment_ref != (finance_treatment_ref or ""):
                        raise DomainError("幂等键已被不同兑换订单使用: finance_treatment_ref mismatch。")
                    expected_merchant = merchant.merchant_id if merchant else None
                    actual_merchant = order.merchant.merchant_id if order.merchant else None
                    if expected_merchant != actual_merchant:
                        raise DomainError("幂等键已被不同兑换订单使用: merchant mismatch。")
                    return order, existing_txn

    # Require settlement_rate for cash_settlement merchants
    if merchant is not None and merchant.merchant_type == MerchantProfile.Type.CASH_SETTLEMENT:
        if merchant.settlement_rate is None:
            raise DomainError("现金结算商户未设置 settlement_rate，无法创建兑换订单。")

    member_account = get_or_create_member_credit_account(member)
    # Lock account to prevent concurrent over-freeze
    member_account = CreditAccount.objects.select_for_update().get(pk=member_account.pk)
    current = credit_balance(member_account)
    if current <= 0:
        raise DomainError("当前余额小于等于 0，不能发起兑换。")
    if current < credit_amount:
        raise DomainError(f"余额不足（当前 {current}，需要 {credit_amount}）。")

    # Deterministic order_id from idempotency_key hash (≤ 64 chars)
    import hashlib

    if dedupe_key:
        short_hash = hashlib.sha256(dedupe_key.encode()).hexdigest()[:32]
        order_id = f"ro-{short_hash}"
    else:
        order_id = _new_id("ro")
    frozen = _pool(CreditAccount.Type.FROZEN)

    order, _created = RedemptionOrder.objects.get_or_create(
        order_id=order_id,
        defaults=dict(
            member=member,
            status=RedemptionOrder.Status.PENDING,
            item_type=item_type,
            title=title or f"兑换 {credit_amount} 积分",
            credit_amount=credit_amount,
            original_amount_rmb=original_amount_rmb,
            cash_amount_rmb=cash_amount_rmb,
            related_task=related_task,
            resource_id=resource_id or "",
            item_snapshot=item_snapshot or {},
            finance_treatment_ref=finance_treatment_ref or "",
            reason=reason,
            created_by=created_by or member,
            merchant=merchant,
            created_at=timezone.now(),
            updated_at=timezone.now(),
        ),
    )
    if not _created and order.member_id != member.pk:
        raise DomainError("幂等键已被不同成员的订单使用。")

    txn = post_credit_transaction(
        transaction_type=CreditTransaction.Type.CONSUME,
        amount=credit_amount,
        source_account=member_account,
        target_account=frozen,
        reason=reason or f"兑换订单 {order_id}",
        initiated_by=created_by or member,
        idempotency_key=dedupe_key or f"redemption-freeze:{order_id}",
        metadata={"order_id": order_id, "item_type": item_type},
    )
    return order, txn


@atomic_for_model(RedemptionOrder)
def cancel_redemption_order(
    *,
    order: RedemptionOrder,
    reason: str = "",
    cancelled_by: Member | None = None,
    idempotency_key: str | None = None,
) -> RedemptionOrder:
    """Cancel a pending or disputed redemption order — unfreezes credits."""
    order = RedemptionOrder.objects.select_for_update().get(pk=order.pk)
    if order.status == RedemptionOrder.Status.CANCELLED:
        return order
    if order.status == RedemptionOrder.Status.FULFILLED:
        raise DomainError("已履约订单不能取消。")
    if order.status == RedemptionOrder.Status.REVERSED:
        raise DomainError("已冲正订单不能取消。")

    dedupe_key = _normalise_idem_key(idempotency_key) or f"redemption-unfreeze:{order.order_id}"

    member_account = get_or_create_member_credit_account(order.member)
    frozen = _pool(CreditAccount.Type.FROZEN)

    post_credit_transaction(
        transaction_type=CreditTransaction.Type.UNFREEZE,
        amount=order.credit_amount,
        source_account=frozen,
        target_account=member_account,
        reason=reason or f"取消订单 {order.order_id}",
        initiated_by=cancelled_by or order.member,
        idempotency_key=dedupe_key,
        metadata={"order_id": order.order_id, "action": "cancel"},
    )

    order.status = RedemptionOrder.Status.CANCELLED
    order.cancelled_at = timezone.now()
    order.updated_at = timezone.now()
    order.metadata = {**(order.metadata or {}), "cancel_reason": reason or ""}
    order.save(update_fields=["status", "cancelled_at", "updated_at", "metadata"])
    return order


@atomic_for_model(RedemptionOrder)
def fulfill_redemption_order(
    *,
    order: RedemptionOrder,
    reason: str = "",
    reviewed_by: Member | None = None,
    idempotency_key: str | None = None,
) -> RedemptionOrder:
    """Fulfill a pending or disputed order — burn frozen credits."""
    order = RedemptionOrder.objects.select_for_update().get(pk=order.pk)
    if order.status == RedemptionOrder.Status.FULFILLED:
        return order
    if order.status == RedemptionOrder.Status.CANCELLED:
        raise DomainError("已取消订单不能履约。")
    if order.status == RedemptionOrder.Status.REVERSED:
        raise DomainError("已冲正订单不能履约。")

    dedupe_key = _normalise_idem_key(idempotency_key) or f"redemption-burn:{order.order_id}"

    frozen = _pool(CreditAccount.Type.FROZEN)
    burn = _pool(CreditAccount.Type.BURN)

    post_credit_transaction(
        transaction_type=CreditTransaction.Type.BURN,
        amount=order.credit_amount,
        source_account=frozen,
        target_account=burn,
        reason=reason or f"履约销毁订单 {order.order_id}",
        initiated_by=reviewed_by or order.member,
        idempotency_key=dedupe_key,
        metadata={"order_id": order.order_id, "action": "fulfill"},
    )

    order.status = RedemptionOrder.Status.FULFILLED
    order.fulfilled_at = timezone.now()
    order.reviewed_by = reviewed_by
    order.updated_at = timezone.now()
    order.save(update_fields=["status", "fulfilled_at", "reviewed_by", "updated_at"])

    _generate_settlement_record(order)
    return order


def _generate_settlement_record(order: RedemptionOrder):
    """Create a MerchantSettlementRecord if order.merchant is a cash_settlement merchant."""
    merchant = order.merchant
    if merchant is None:
        return
    if merchant.merchant_type != MerchantProfile.Type.CASH_SETTLEMENT:
        return

    rate = merchant.settlement_rate
    if rate is None:
        raise DomainError("现金结算商户未设置 settlement_rate，履约失败。")

    from decimal import Decimal, ROUND_HALF_UP
    credit = Decimal(str(order.credit_amount))
    payable = (credit * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    MerchantSettlementRecord.objects.get_or_create(
        redemption_order=order,
        defaults=dict(
            settlement_id=f"ms-{order.order_id}",
            merchant=merchant,
            covered_credit_amount=order.credit_amount,
            settlement_rate=rate,
            payable_rmb=payable,
            status=MerchantSettlementRecord.Status.PENDING,
            reason=f"兑换履约：{order.order_id}",
            created_at=timezone.now(),
        ),
    )


@atomic_for_model(RedemptionOrder)
def report_redemption_order_issue(
    *,
    order: RedemptionOrder,
    reason: str = "",
) -> RedemptionOrder:
    """Report a fulfillment issue on a pending order without moving credits."""
    order = RedemptionOrder.objects.select_for_update().get(pk=order.pk)
    if order.status == RedemptionOrder.Status.FULFILLED:
        raise DomainError("已履约订单不能争议。")
    if order.status == RedemptionOrder.Status.CANCELLED:
        raise DomainError("已取消订单不能争议。")
    if order.status == RedemptionOrder.Status.REVERSED:
        raise DomainError("已冲正订单不能争议。")
    if order.status == RedemptionOrder.Status.DISPUTED:
        return order

    order.status = RedemptionOrder.Status.DISPUTED
    order.updated_at = timezone.now()
    order.metadata = {**(order.metadata or {}), "issue_reason": reason or ""}
    order.save(update_fields=["status", "updated_at", "metadata"])
    return order
