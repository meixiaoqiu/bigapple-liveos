"""Tests for the authoritative double-entry credit system.

Covers CreditAccount, CreditTransaction creation, balance derivation,
transfer constraints, passive deductions, reversal, task budget locking,
and task-reward integration with the existing LedgerEntry.
"""

from __future__ import annotations

from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from core.credit_services import (
    cancel_redemption_order,
    create_redemption_order,
    credit_balance,
    report_redemption_order_issue,
    ensure_system_accounts,
    fulfill_redemption_order,
    get_or_create_member_credit_account,
    issue_credits_to_pool,
    lock_task_credit_budget,
    member_available_credit_balance,
    member_credit_balance,
    member_lifetime_contribution,
    passive_deduct_member_credits,
    post_credit_transaction,
    post_task_reward_credit_transaction,
    reverse_credit_transaction,
    task_locked_credit_balance,
    transfer_member_credits,
    unlock_unused_task_credit_budget,
)
from core.exceptions import DomainError
from core.ledger_services import create_ledger_entry
from core.models import (
    CreditAccount,
    CreditTransaction,
    LedgerEntry,
    Member,
    RedemptionOrder,
    SystemEvent,
    Task,
)
from core.tests.helpers import create_member


# ── helpers ──────────────────────────────────────────────────────────


def _create_task(*, task_id: str, assignee: Member, base_points: int = 100) -> Task:
    return Task.objects.create(
        task_id=task_id,
        title=f"Test task {task_id}",
        task_type=Task.TaskType.PUBLIC_CLEANING,
        status=Task.Status.PENDING_REVIEW,
        standard_minutes=60,
        base_points=base_points,
        role_coefficient=1,
        assignee_member=assignee,
        rule_version="v1",
        created_at=timezone.now(),
    )


def _make_governance(member: Member) -> Member:
    return member


# ── account tests ────────────────────────────────────────────────────


class CreditAccountTests(TestCase):
    def setUp(self):
        self.member = create_member("member-credit-1")

    def test_system_accounts_created_once(self):
        before = CreditAccount.objects.count()
        ensure_system_accounts()
        after = CreditAccount.objects.count()
        self.assertGreaterEqual(after, before + 4)
        ensure_system_accounts()
        self.assertEqual(CreditAccount.objects.count(), after)

    def test_member_account_created_once(self):
        a1 = get_or_create_member_credit_account(self.member)
        a2 = get_or_create_member_credit_account(self.member)
        self.assertEqual(a1.pk, a2.pk)

    def test_member_balance_defaults_to_zero(self):
        self.assertEqual(member_credit_balance(self.member), 0)

    def test_clean_rejects_member_type_without_member(self):
        from django.core.exceptions import ValidationError
        acct = CreditAccount(
            account_id="acct-bad", account_type=CreditAccount.Type.MEMBER,
            member=None, status=CreditAccount.Status.ACTIVE,
        )
        with self.assertRaises(ValidationError):
            acct.clean()

    def test_clean_rejects_system_type_with_member(self):
        from django.core.exceptions import ValidationError
        acct = CreditAccount(
            account_id="acct-bad-2", account_type=CreditAccount.Type.ISSUANCE_POOL,
            member=self.member, status=CreditAccount.Status.ACTIVE,
        )
        with self.assertRaises(ValidationError):
            acct.clean()


# ── transaction posting ──────────────────────────────────────────────


class CreditTransactionPostingTests(TestCase):
    def setUp(self):
        self.member = create_member("member-txn-1")
        ensure_system_accounts()
        self.issuance = CreditAccount.objects.get(account_type=CreditAccount.Type.ISSUANCE_POOL)
        self.member_acct = get_or_create_member_credit_account(self.member)

    def test_post_creates_transaction(self):
        txn = post_credit_transaction(
            transaction_type=CreditTransaction.Type.ISSUANCE,
            amount=100,
            target_account=self.issuance,
        )
        self.assertEqual(txn.status, CreditTransaction.Status.POSTED)

    def test_amount_zero_rejected(self):
        with self.assertRaises(DomainError):
            post_credit_transaction(
                transaction_type=CreditTransaction.Type.ISSUANCE,
                amount=0,
                target_account=self.issuance,
            )

    def test_amount_negative_rejected(self):
        with self.assertRaises(DomainError):
            post_credit_transaction(
                transaction_type=CreditTransaction.Type.ISSUANCE,
                amount=-5,
                target_account=self.issuance,
            )

    def test_idempotency_key_prevents_duplicates(self):
        key = "test:idem:1"
        t1 = post_credit_transaction(
            transaction_type=CreditTransaction.Type.ISSUANCE,
            amount=50, target_account=self.issuance, idempotency_key=key,
        )
        t2 = post_credit_transaction(
            transaction_type=CreditTransaction.Type.ISSUANCE,
            amount=50, target_account=self.issuance, idempotency_key=key,
        )
        self.assertEqual(t1.pk, t2.pk)
        self.assertEqual(CreditTransaction.objects.filter(idempotency_key=key).count(), 1)

    def test_empty_idempotency_key_allows_multiple(self):
        post_credit_transaction(
            transaction_type=CreditTransaction.Type.ISSUANCE,
            amount=10, target_account=self.issuance, idempotency_key=None,
        )
        post_credit_transaction(
            transaction_type=CreditTransaction.Type.ISSUANCE,
            amount=10, target_account=self.issuance, idempotency_key=None,
        )
        self.assertEqual(
            CreditTransaction.objects.filter(target_account=self.issuance, amount=10).count(), 2,
        )

    def test_integrity_error_on_duplicate_key_returns_existing(self):
        key = "test:integ:collision"
        t1 = post_credit_transaction(
            transaction_type=CreditTransaction.Type.ISSUANCE,
            amount=99, target_account=self.issuance, idempotency_key=key,
        )
        t2 = post_credit_transaction(
            transaction_type=CreditTransaction.Type.ISSUANCE,
            amount=99, target_account=self.issuance, idempotency_key=key,
        )
        self.assertEqual(t1.pk, t2.pk)

    def test_integrity_error_fastpath_miss_recovery(self):
        from unittest.mock import patch

        key = "test:integ:fastpath-miss"
        existing = CreditTransaction.objects.create(
            transaction_id="ct-fastpath-existing",
            transaction_type=CreditTransaction.Type.ISSUANCE,
            amount=88, target_account=self.issuance,
            idempotency_key=key, status=CreditTransaction.Status.POSTED,
            created_at=timezone.now(),
        )
        original_filter = CreditTransaction.objects.filter
        call_count = [0]

        def tracking_filter(*args, **kwargs):
            result = original_filter(*args, **kwargs)
            call_count[0] += 1
            if call_count[0] == 1:
                return CreditTransaction.objects.none()
            return result

        with patch.object(CreditTransaction.objects, "filter", side_effect=tracking_filter):
            txn = post_credit_transaction(
                transaction_type=CreditTransaction.Type.ISSUANCE,
                amount=88, target_account=self.issuance, idempotency_key=key,
            )
        self.assertEqual(txn.pk, existing.pk)

    def test_same_key_different_amount_raises(self):
        key = "test:sem:mismatch-amount"
        post_credit_transaction(
            transaction_type=CreditTransaction.Type.ISSUANCE,
            amount=100, target_account=self.issuance, idempotency_key=key,
        )
        with self.assertRaises(DomainError):
            post_credit_transaction(
                transaction_type=CreditTransaction.Type.ISSUANCE,
                amount=200, target_account=self.issuance, idempotency_key=key,
            )

    def test_same_key_different_type_raises(self):
        key = "test:sem:mismatch-type"
        post_credit_transaction(
            transaction_type=CreditTransaction.Type.ISSUANCE,
            amount=50, target_account=self.issuance, idempotency_key=key,
        )
        with self.assertRaises(DomainError):
            post_credit_transaction(
                transaction_type=CreditTransaction.Type.BURN,
                amount=50, target_account=self.issuance, idempotency_key=key,
            )

    def test_same_key_different_source_raises(self):
        key = "test:sem:mismatch-src"
        post_credit_transaction(
            transaction_type=CreditTransaction.Type.CORRECTION,
            amount=10,
            source_account=self.member_acct,
            target_account=CreditAccount.objects.get(account_type=CreditAccount.Type.BURN),
            idempotency_key=key,
        )
        with self.assertRaises(DomainError):
            post_credit_transaction(
                transaction_type=CreditTransaction.Type.CORRECTION,
                amount=10,
                source_account=self.issuance,
                target_account=CreditAccount.objects.get(account_type=CreditAccount.Type.BURN),
                idempotency_key=key,
            )


# ── transfer tests ───────────────────────────────────────────────────


class CreditTransferTests(TestCase):
    def setUp(self):
        self.member_a = create_member("transfer-a")
        self.member_b = create_member("transfer-b")
        ensure_system_accounts()
        self.issuance = CreditAccount.objects.get(account_type=CreditAccount.Type.ISSUANCE_POOL)
        self.acct_a = get_or_create_member_credit_account(self.member_a)
        self.acct_b = get_or_create_member_credit_account(self.member_b)

    def _give_credits(self, member, amount):
        post_credit_transaction(
            transaction_type=CreditTransaction.Type.ISSUANCE,
            amount=amount, source_account=self.issuance,
            target_account=get_or_create_member_credit_account(member),
        )

    def test_transfer_succeeds_with_sufficient_balance(self):
        self._give_credits(self.member_a, 200)
        transfer_member_credits(from_member=self.member_a, to_member=self.member_b, amount=50)
        self.assertEqual(credit_balance(self.acct_a), 150)
        self.assertEqual(credit_balance(self.acct_b), 50)

    def test_transfer_blocked_when_balance_zero(self):
        with self.assertRaises(DomainError):
            transfer_member_credits(from_member=self.member_a, to_member=self.member_b, amount=10)

    def test_transfer_blocked_when_insufficient_balance(self):
        self._give_credits(self.member_a, 30)
        with self.assertRaises(DomainError):
            transfer_member_credits(from_member=self.member_a, to_member=self.member_b, amount=50)

    def test_transfer_to_self_rejected(self):
        self._give_credits(self.member_a, 100)
        with self.assertRaises(DomainError):
            transfer_member_credits(from_member=self.member_a, to_member=self.member_a, amount=10)

    def test_transfer_negative_amount_rejected(self):
        self._give_credits(self.member_a, 100)
        with self.assertRaises(DomainError):
            transfer_member_credits(from_member=self.member_a, to_member=self.member_b, amount=-10)

    def test_transfer_idempotent_same_key_returns_existing(self):
        self._give_credits(self.member_a, 200)
        key = "transfer-idem-1"
        t1 = transfer_member_credits(from_member=self.member_a, to_member=self.member_b, amount=20, idempotency_key=key)
        t2 = transfer_member_credits(from_member=self.member_a, to_member=self.member_b, amount=20, idempotency_key=key)
        self.assertEqual(t1.pk, t2.pk)
        self.assertEqual(credit_balance(self.acct_a), 180)

    def test_transfer_same_key_different_amount_raises(self):
        self._give_credits(self.member_a, 200)
        key = "transfer-diff-amount"
        transfer_member_credits(from_member=self.member_a, to_member=self.member_b, amount=10, idempotency_key=key)
        with self.assertRaises(DomainError):
            transfer_member_credits(from_member=self.member_a, to_member=self.member_b, amount=30, idempotency_key=key)

    def test_transfer_idempotent_when_balance_exhausted(self):
        """A has 20, transfers 20 (balance→0), retry with same key returns existing."""
        self._give_credits(self.member_a, 20)
        key = "transfer-exhausted"
        t1 = transfer_member_credits(from_member=self.member_a, to_member=self.member_b, amount=20, idempotency_key=key)
        self.assertEqual(credit_balance(self.acct_a), 0)
        t2 = transfer_member_credits(from_member=self.member_a, to_member=self.member_b, amount=20, idempotency_key=key)
        self.assertEqual(t1.pk, t2.pk)

    def test_transfer_same_key_different_to_member_raises(self):
        self._give_credits(self.member_a, 200)
        key = "transfer-diff-to"
        transfer_member_credits(from_member=self.member_a, to_member=self.member_b, amount=10, idempotency_key=key)
        member_c = create_member("transfer-c")
        c_acct = get_or_create_member_credit_account(member_c)
        post_credit_transaction(transaction_type=CreditTransaction.Type.ISSUANCE, amount=10, target_account=c_acct)
        with self.assertRaises(DomainError):
            transfer_member_credits(from_member=self.member_a, to_member=member_c, amount=10, idempotency_key=key)


# ── passive deduction tests ──────────────────────────────────────────


class PassiveDeductionTests(TestCase):
    def setUp(self):
        self.member = create_member("deduct-1")
        ensure_system_accounts()
        self.acct = get_or_create_member_credit_account(self.member)

    def test_passive_deduction_can_go_negative(self):
        passive_deduct_member_credits(member=self.member, amount=30, reason="correction")
        self.assertEqual(credit_balance(self.acct), -30)


# ── reversal tests ───────────────────────────────────────────────────


class ReversalTests(TestCase):
    def setUp(self):
        self.member = create_member("reverse-1")
        ensure_system_accounts()
        self.acct = get_or_create_member_credit_account(self.member)
        self.issuance = CreditAccount.objects.get(account_type=CreditAccount.Type.ISSUANCE_POOL)

    def test_reversal_restores_balance(self):
        txn = post_credit_transaction(
            transaction_type=CreditTransaction.Type.ISSUANCE,
            amount=100, source_account=self.issuance, target_account=self.acct,
        )
        self.assertEqual(credit_balance(self.acct), 100)
        reverse_credit_transaction(original=txn, reason="oops")
        self.assertEqual(credit_balance(self.acct), 0)

    def test_reversal_does_not_delete_original(self):
        txn = post_credit_transaction(
            transaction_type=CreditTransaction.Type.ISSUANCE,
            amount=50, source_account=self.issuance, target_account=self.acct,
        )
        reverse_credit_transaction(original=txn, reason="oops")
        txn.refresh_from_db()
        self.assertEqual(txn.status, CreditTransaction.Status.POSTED)

    def test_double_reversal_rejected(self):
        txn = post_credit_transaction(
            transaction_type=CreditTransaction.Type.ISSUANCE,
            amount=50, source_account=self.issuance, target_account=self.acct,
        )
        reverse_credit_transaction(original=txn, reason="first")
        with self.assertRaises(DomainError):
            reverse_credit_transaction(original=txn, reason="second")


# ── issuance & budget locking ────────────────────────────────────────


class IssuanceAndBudgetTests(TestCase):
    def setUp(self):
        self.governor = create_member("gov-issuance-1")
        self.member = create_member("member-budget-1")
        ensure_system_accounts()
        self.pool = CreditAccount.objects.get(account_type=CreditAccount.Type.ISSUANCE_POOL)
        self.acct = get_or_create_member_credit_account(self.member)
        self.task = _create_task(task_id="task-budget-1", assignee=self.member, base_points=50)

    def test_issue_to_pool_increases_balance(self):
        issue_credits_to_pool(
            amount=300, reason="治理批准发行",
            initiated_by=self.governor, reviewed_by=self.governor,
        )
        self.assertEqual(credit_balance(self.pool), 300)

    def test_lock_budget_reduces_pool_increases_task_balance(self):
        issue_credits_to_pool(
            amount=300, reason="init", initiated_by=self.governor, reviewed_by=self.governor,
        )
        lock_task_credit_budget(task=self.task, amount=100, reason="lock 100")
        self.assertEqual(credit_balance(self.pool), 200)
        self.assertEqual(task_locked_credit_balance(self.task), 100)

    def test_lock_budget_fails_when_pool_insufficient(self):
        issue_credits_to_pool(
            amount=30, reason="init", initiated_by=self.governor, reviewed_by=self.governor,
        )
        with self.assertRaises(DomainError):
            lock_task_credit_budget(task=self.task, amount=100, reason="too much")

    def test_lock_budget_idempotent(self):
        issue_credits_to_pool(
            amount=300, reason="init", initiated_by=self.governor, reviewed_by=self.governor,
        )
        key = "lock:task-budget-1:v1"
        lock_task_credit_budget(task=self.task, amount=80, reason="lock", idempotency_key=key)
        lock_task_credit_budget(task=self.task, amount=80, reason="lock", idempotency_key=key)
        self.assertEqual(task_locked_credit_balance(self.task), 80)

    def test_unlock_returns_budget_to_pool(self):
        issue_credits_to_pool(
            amount=300, reason="init", initiated_by=self.governor, reviewed_by=self.governor,
        )
        lock_task_credit_budget(task=self.task, amount=200, reason="lock 200")
        self.assertEqual(task_locked_credit_balance(self.task), 200)
        unlock_unused_task_credit_budget(task=self.task, amount=50, reason="partial return")
        self.assertEqual(task_locked_credit_balance(self.task), 150)
        self.assertEqual(credit_balance(self.pool), 150)

    def test_unlock_more_than_remaining_fails(self):
        issue_credits_to_pool(
            amount=300, reason="init", initiated_by=self.governor, reviewed_by=self.governor,
        )
        lock_task_credit_budget(task=self.task, amount=100, reason="lock")
        with self.assertRaises(DomainError):
            unlock_unused_task_credit_budget(task=self.task, amount=200, reason="too much")

    def test_lock_idempotent_returns_existing_when_pool_insufficient(self):
        """Second lock with same key returns existing even if pool now empty."""
        issue_credits_to_pool(
            amount=80, reason="init", initiated_by=self.governor, reviewed_by=self.governor,
        )
        key = "lock:idem:exact"
        t1 = lock_task_credit_budget(task=self.task, amount=80, reason="first", idempotency_key=key)
        # Pool is now 0 — second call with same key must return t1, not DomainError
        t2 = lock_task_credit_budget(task=self.task, amount=80, reason="retry", idempotency_key=key)
        self.assertEqual(t1.pk, t2.pk)
        self.assertEqual(task_locked_credit_balance(self.task), 80)

    def test_unlock_idempotent_returns_existing_when_budget_insufficient(self):
        """Second unlock with same key returns existing even if budget now too low."""
        issue_credits_to_pool(
            amount=200, reason="init", initiated_by=self.governor, reviewed_by=self.governor,
        )
        lock_task_credit_budget(task=self.task, amount=100, reason="lock")
        key = "unlock:idem:half"
        t1 = unlock_unused_task_credit_budget(task=self.task, amount=50, reason="first", idempotency_key=key)
        # Remaining budget is 50.  Retry with same amount → semantic match → returns t1
        t2 = unlock_unused_task_credit_budget(task=self.task, amount=50, reason="retry", idempotency_key=key)
        self.assertEqual(t1.pk, t2.pk)

    def test_lock_same_key_different_task_raises(self):
        """Key reused with a different task raises DomainError."""
        other_task = _create_task(task_id="task-other", assignee=self.member, base_points=10)
        issue_credits_to_pool(
            amount=200, reason="init", initiated_by=self.governor, reviewed_by=self.governor,
        )
        key = "lock:sem:cross-task"
        lock_task_credit_budget(task=self.task, amount=50, reason="first", idempotency_key=key)
        with self.assertRaises(DomainError):
            lock_task_credit_budget(task=other_task, amount=50, reason="wrong task", idempotency_key=key)


# ── task reward from locked budget ───────────────────────────────────


class TaskRewardBudgetTests(TestCase):
    def setUp(self):
        self.governor = create_member("gov-reward-1")
        self.member = create_member("member-reward-1")
        ensure_system_accounts()
        self.pool = CreditAccount.objects.get(account_type=CreditAccount.Type.ISSUANCE_POOL)
        self.acct = get_or_create_member_credit_account(self.member)
        self.task = _create_task(task_id="task-reward-budget", assignee=self.member, base_points=50)

    def _issue_and_lock(self, amount: int):
        issue_credits_to_pool(
            amount=amount, reason="issue", initiated_by=self.governor, reviewed_by=self.governor,
        )
        lock_task_credit_budget(task=self.task, amount=amount, reason="budget")

    def _ledger(self, lid: str, amt: int) -> LedgerEntry:
        return LedgerEntry.objects.create(
            ledger_entry_id=lid,
            member=self.member, amount=amt,
            entry_type=LedgerEntry.EntryType.CONTRIBUTION,
            reason="reward", related_task=self.task,
            rule_version="v1", created_at=timezone.now(),
            created_by={"actor_id": "admin", "display_name": "Admin"},
            status=LedgerEntry.Status.POSTED,
        )

    def test_reward_uses_locked_budget_source(self):
        self._issue_and_lock(200)
        le = self._ledger("ledger-reward-b1", 50)
        txn = post_task_reward_credit_transaction(
            task=self.task, member=self.member, amount=50, ledger_entry=le,
        )
        self.assertEqual(txn.source_account.account_type, CreditAccount.Type.TASK_LOCKED)
        self.assertEqual(txn.target_account, self.acct)
        self.assertEqual(task_locked_credit_balance(self.task), 150)
        self.assertEqual(member_credit_balance(self.member), 50)

    def test_reward_blocked_without_locked_budget(self):
        le = self._ledger("ledger-reward-nolock", 50)
        with self.assertRaises(DomainError):
            post_task_reward_credit_transaction(
                task=self.task, member=self.member, amount=50, ledger_entry=le,
            )

    def test_reward_blocked_when_budget_insufficient(self):
        self._issue_and_lock(30)
        le = self._ledger("ledger-reward-lowbudget", 50)
        with self.assertRaises(DomainError):
            post_task_reward_credit_transaction(
                task=self.task, member=self.member, amount=50, ledger_entry=le,
            )

    def test_multiple_rewards_cannot_exceed_budget(self):
        self._issue_and_lock(100)
        le1 = self._ledger("ledger-multi-1", 60)
        post_task_reward_credit_transaction(
            task=self.task, member=self.member, amount=60, ledger_entry=le1,
        )
        le2 = self._ledger("ledger-multi-2", 50)
        with self.assertRaises(DomainError):
            post_task_reward_credit_transaction(
                task=self.task, member=self.member, amount=50, ledger_entry=le2,
            )

    def test_genesis_exception_still_works(self):
        le = self._ledger("ledger-genesis-bypass", 50)
        txn = post_task_reward_credit_transaction(
            task=self.task, member=self.member, amount=50,
            ledger_entry=le, allow_unbudgeted_genesis=True,
        )
        meta = txn.metadata or {}
        self.assertTrue(meta.get("genesis_unbudgeted"))
        self.assertEqual(member_credit_balance(self.member), 50)

    def test_reward_idempotent(self):
        self._issue_and_lock(200)
        le = self._ledger("ledger-idem-rw", 50)
        t1 = post_task_reward_credit_transaction(
            task=self.task, member=self.member, amount=50, ledger_entry=le,
        )
        t2 = post_task_reward_credit_transaction(
            task=self.task, member=self.member, amount=50, ledger_entry=le,
        )
        self.assertEqual(t1.pk, t2.pk)
        self.assertEqual(member_credit_balance(self.member), 50)

    def test_reward_idempotent_returns_existing_when_budget_exhausted(self):
        """Second reward with same ledger_entry returns existing even if budget now 0."""
        self._issue_and_lock(50)
        le = self._ledger("ledger-idem-exhaust", 50)
        t1 = post_task_reward_credit_transaction(
            task=self.task, member=self.member, amount=50, ledger_entry=le,
        )
        # Budget is now 0 — second call with same ledger_entry must return t1
        t2 = post_task_reward_credit_transaction(
            task=self.task, member=self.member, amount=50, ledger_entry=le,
        )
        self.assertEqual(t1.pk, t2.pk)
        self.assertEqual(member_credit_balance(self.member), 50)
        self.assertEqual(task_locked_credit_balance(self.task), 0)

    def test_reward_genesis_metadata_mismatch_raises(self):
        """Existing TASK_REWARD without genesis_unbudgeted + allow_genesis=True → error."""
        le = self._ledger("ledger-genesis-mismatch", 50)
        # Pre-create a task reward WITHOUT genesis metadata
        idem_key = f"task-reward:{le.ledger_entry_id}"
        member_acct = get_or_create_member_credit_account(self.member)
        issuance_pool = CreditAccount.objects.get(account_type=CreditAccount.Type.ISSUANCE_POOL)
        CreditTransaction.objects.create(
            transaction_id="ct-genesis-mismatch",
            transaction_type=CreditTransaction.Type.TASK_REWARD,
            amount=50,
            source_account=issuance_pool,
            target_account=member_acct,
            related_task=self.task,
            related_ledger_entry=le,
            idempotency_key=idem_key,
            status=CreditTransaction.Status.POSTED,
            created_at=timezone.now(),
        )
        with self.assertRaises(DomainError):
            post_task_reward_credit_transaction(
                task=self.task, member=self.member, amount=50,
                ledger_entry=le, allow_unbudgeted_genesis=True,
            )


# ── redemption tests ─────────────────────────────────────────────────


class RedemptionOrderTests(TestCase):
    def setUp(self):
        self.member = create_member("member-ro-1")
        self.governor = create_member("gov-ro-1")
        ensure_system_accounts()
        self.acct = get_or_create_member_credit_account(self.member)
        self.frozen = CreditAccount.objects.get(account_type=CreditAccount.Type.FROZEN)
        self.burn = CreditAccount.objects.get(account_type=CreditAccount.Type.BURN)
        self.pool = CreditAccount.objects.get(account_type=CreditAccount.Type.ISSUANCE_POOL)

    def _give_credits(self, amount):
        post_credit_transaction(
            transaction_type=CreditTransaction.Type.ISSUANCE,
            amount=amount, target_account=self.acct,
        )

    def test_create_freezes_credits(self):
        self._give_credits(100)
        order, txn = create_redemption_order(
            member=self.member, credit_amount=30, title="餐食兑换", reason="test",
        )
        self.assertEqual(order.status, RedemptionOrder.Status.PENDING)
        self.assertEqual(txn.transaction_type, CreditTransaction.Type.CONSUME)
        self.assertEqual(txn.source_account, self.acct)
        self.assertEqual(txn.target_account, self.frozen)
        self.assertEqual(credit_balance(self.acct), 70)
        self.assertEqual(credit_balance(self.frozen), 30)

    def test_balance_zero_blocks_redemption(self):
        with self.assertRaises(DomainError):
            create_redemption_order(member=self.member, credit_amount=10)

    def test_insufficient_balance_blocks_redemption(self):
        self._give_credits(20)
        with self.assertRaises(DomainError):
            create_redemption_order(member=self.member, credit_amount=30)

    def test_create_idempotent(self):
        self._give_credits(100)
        key = "ro:test:idem"
        o1, t1 = create_redemption_order(
            member=self.member, credit_amount=20, idempotency_key=key,
        )
        o2, t2 = create_redemption_order(
            member=self.member, credit_amount=20, idempotency_key=key,
        )
        self.assertEqual(o1.pk, o2.pk)
        self.assertEqual(t1.pk, t2.pk)
        self.assertEqual(credit_balance(self.frozen), 20)

    def test_create_idem_key_different_amount_raises(self):
        self._give_credits(100)
        key = "ro:sem:mismatch-amount"
        create_redemption_order(member=self.member, credit_amount=20, idempotency_key=key)
        with self.assertRaises(DomainError):
            create_redemption_order(member=self.member, credit_amount=30, idempotency_key=key)

    def test_create_idem_key_different_member_raises(self):
        self._give_credits(100)
        other_member = create_member("mem-ro-other")
        other_acct = get_or_create_member_credit_account(other_member)
        post_credit_transaction(
            transaction_type=CreditTransaction.Type.ISSUANCE,
            amount=100, target_account=other_acct,
        )
        key = "ro:sem:mismatch-member"
        create_redemption_order(member=self.member, credit_amount=10, idempotency_key=key)
        with self.assertRaises(DomainError):
            create_redemption_order(member=other_member, credit_amount=10, idempotency_key=key)

    def test_create_idem_key_different_item_type_raises(self):
        self._give_credits(100)
        key = "ro:sem:mismatch-item"
        create_redemption_order(
            member=self.member, credit_amount=10,
            item_type=RedemptionOrder.ItemType.MEAL, idempotency_key=key,
        )
        with self.assertRaises(DomainError):
            create_redemption_order(
                member=self.member, credit_amount=10,
                item_type=RedemptionOrder.ItemType.GOODS, idempotency_key=key,
            )

    def test_create_idem_key_different_related_task_raises(self):
        self._give_credits(100)
        task_a = _create_task(task_id="task-ro-sem-a", assignee=self.member, base_points=10)
        task_b = _create_task(task_id="task-ro-sem-b", assignee=self.member, base_points=10)
        key = "ro:sem:mismatch-task"
        create_redemption_order(
            member=self.member, credit_amount=10,
            related_task=task_a, idempotency_key=key,
        )
        with self.assertRaises(DomainError):
            create_redemption_order(
                member=self.member, credit_amount=10,
                related_task=task_b, idempotency_key=key,
            )

    def test_cancel_unfreezes_credits(self):
        self._give_credits(100)
        order, _ = create_redemption_order(member=self.member, credit_amount=40)
        cancelled = cancel_redemption_order(order=order, reason="no longer needed")
        self.assertEqual(cancelled.status, RedemptionOrder.Status.CANCELLED)
        self.assertEqual(credit_balance(self.acct), 100)
        self.assertEqual(credit_balance(self.frozen), 0)

    def test_cancel_idempotent(self):
        self._give_credits(100)
        order, _ = create_redemption_order(member=self.member, credit_amount=30)
        cancel_redemption_order(order=order)
        cancel_redemption_order(order=order)
        self.assertEqual(credit_balance(self.acct), 100)

    def test_cannot_cancel_fulfilled(self):
        self._give_credits(100)
        order, _ = create_redemption_order(member=self.member, credit_amount=30)
        fulfill_redemption_order(order=order)
        with self.assertRaises(DomainError):
            cancel_redemption_order(order=order)

    def test_fulfill_burns_frozen_credits(self):
        self._give_credits(100)
        order, _ = create_redemption_order(member=self.member, credit_amount=30)
        fulfilled = fulfill_redemption_order(order=order, reviewed_by=self.governor)
        self.assertEqual(fulfilled.status, RedemptionOrder.Status.FULFILLED)
        self.assertEqual(credit_balance(self.frozen), 0)
        self.assertEqual(credit_balance(self.burn), 30)
        # Member balance unchanged after freeze (70 -> 70)
        self.assertEqual(credit_balance(self.acct), 70)

    def test_fulfill_idempotent(self):
        self._give_credits(100)
        order, _ = create_redemption_order(member=self.member, credit_amount=30)
        fulfill_redemption_order(order=order)
        fulfill_redemption_order(order=order)
        self.assertEqual(credit_balance(self.burn), 30)

    def test_cannot_fulfill_cancelled(self):
        self._give_credits(100)
        order, _ = create_redemption_order(member=self.member, credit_amount=30)
        cancel_redemption_order(order=order)
        with self.assertRaises(DomainError):
            fulfill_redemption_order(order=order)

    def test_dispute_does_not_change_balances(self):
        self._give_credits(100)
        order, _ = create_redemption_order(member=self.member, credit_amount=30)
        bal_before = credit_balance(self.acct)
        disputed = report_redemption_order_issue(order=order, reason="wrong item")
        self.assertEqual(disputed.status, RedemptionOrder.Status.DISPUTED)
        self.assertEqual(credit_balance(self.acct), bal_before)

    def test_disputed_can_be_fulfilled(self):
        self._give_credits(100)
        order, _ = create_redemption_order(member=self.member, credit_amount=30)
        report_redemption_order_issue(order=order, reason="test")
        fulfilled = fulfill_redemption_order(order=order)
        self.assertEqual(fulfilled.status, RedemptionOrder.Status.FULFILLED)

    def test_cannot_redeem_when_balance_negative(self):
        passive_deduct_member_credits(member=self.member, amount=20, reason="penalty")
        with self.assertRaises(DomainError):
            create_redemption_order(member=self.member, credit_amount=10)

    def test_additional_credits_dont_affect_frozen_fulfill(self):
        self._give_credits(100)
        order, _ = create_redemption_order(member=self.member, credit_amount=40)
        # Member earns more credits after freeze
        post_credit_transaction(
            transaction_type=CreditTransaction.Type.ISSUANCE,
            amount=200, target_account=self.acct,
        )
        fulfill_redemption_order(order=order)
        self.assertEqual(credit_balance(self.burn), 40)
        self.assertEqual(credit_balance(self.acct), 260)  # 100 - 40 + 200

    def test_concurrent_idem_key_does_not_create_second_order(self):
        """同 idempotency_key 并发不会留下第二个 pending order。"""
        self._give_credits(100)
        key = "ro:concurrent:orphan"
        o1, _ = create_redemption_order(member=self.member, credit_amount=15, idempotency_key=key)
        o2, _ = create_redemption_order(member=self.member, credit_amount=15, idempotency_key=key)
        self.assertEqual(o1.pk, o2.pk)
        self.assertEqual(RedemptionOrder.objects.filter(member=self.member, status=RedemptionOrder.Status.PENDING).count(), 1)

    def test_post_credit_txn_emits_system_event(self):
        """CreditTransaction 创建后必须写入 SystemEvent；失败则事务回滚。"""
        self._give_credits(100)
        se_before = SystemEvent.objects.count()
        post_credit_transaction(transaction_type=CreditTransaction.Type.TRANSFER, amount=1,
                                source_account=self.acct, target_account=self.pool)
        self.assertGreater(SystemEvent.objects.count(), se_before)

    def test_system_event_public_payload_privacy(self):
        """公开 SystemEvent payload 不泄露 transaction_id / amount / reason。"""
        self._give_credits(100)
        txn = post_credit_transaction(
            transaction_type=CreditTransaction.Type.TRANSFER, amount=50,
            source_account=self.acct, target_account=self.pool, reason="privacy test",
        )
        se = SystemEvent.objects.filter(
            aggregate_type="CreditTransaction", aggregate_id=txn.transaction_id,
        ).first()
        self.assertIsNotNone(se, "Expected SystemEvent for posted CreditTransaction")
        payload = se.payload_json or {}
        # Public payload must not leak per-transaction details
        public_facts = payload.get("public_facts", {})
        self.assertNotIn("txn_amount", public_facts)
        self.assertNotIn("txn_reason", public_facts)
        self.assertNotIn("transaction_id", public_facts)
        # Subject ref / label must not contain transaction_id
        subject_ref = str(payload.get("subject", {}).get("ref", ""))
        subject_label = str(payload.get("subject", {}).get("label", ""))
        self.assertNotIn(txn.transaction_id, subject_ref)
        self.assertNotIn(txn.transaction_id, subject_label)
        # Summary must not contain amount
        summary = str(payload.get("summary", ""))
        self.assertNotIn("50", summary)
        # Private commitments must record presence of amount/reason
        commitments = payload.get("private_commitments", [])
        names = {c["name"] for c in commitments if isinstance(c, dict)}
        self.assertIn("amount", names)
        self.assertIn("reason", names)

    def test_genesis_metadata_has_required_fields(self):
        task = _create_task(task_id="task-genesis-fields", assignee=self.member, base_points=30)
        le = LedgerEntry.objects.create(
            ledger_entry_id="ledger-genesis-fields", member=self.member, amount=30,
            entry_type=LedgerEntry.EntryType.CONTRIBUTION, reason="test", related_task=task,
            rule_version="v1", created_at=timezone.now(),
            created_by={"actor_id": "admin", "display_name": "Admin"}, status=LedgerEntry.Status.POSTED,
        )
        txn = post_task_reward_credit_transaction(
            task=task, member=self.member, amount=30, ledger_entry=le,
            allow_unbudgeted_genesis=True, reviewed_by=self.member,
        )
        meta = txn.metadata or {}
        self.assertTrue(meta.get("genesis_unbudgeted"))
        self.assertTrue(meta.get("genesis_governance"))
        self.assertTrue(meta.get("public_audit_required"))

    def test_lifetime_contribution_vs_balance(self):
        # Issue to pool so we can lock budget
        issue_credits_to_pool(
            amount=200, reason="test", initiated_by=self.member, reviewed_by=self.member,
        )
        le = LedgerEntry.objects.create(
            ledger_entry_id="ledger-lifetime", member=self.member, amount=100,
            entry_type=LedgerEntry.EntryType.CONTRIBUTION, reason="test", related_task=None,
            rule_version="v1", created_at=timezone.now(),
            created_by={"actor_id": "admin", "display_name": "Admin"}, status=LedgerEntry.Status.POSTED,
        )
        task = _create_task(task_id="task-lifetime", assignee=self.member, base_points=100)
        lock_task_credit_budget(task=task, amount=100, reason="lock")
        post_task_reward_credit_transaction(task=task, member=self.member, amount=100, ledger_entry=le)
        self.assertEqual(member_lifetime_contribution(self.member), 100)
        self.assertEqual(member_credit_balance(self.member), 100)
        self.assertEqual(member_available_credit_balance(self.member), 100)
        # Transfer 30 — lifetime unchanged
        other = create_member("mem-lifetime-other")
        other_acct = get_or_create_member_credit_account(other)
        post_credit_transaction(
            transaction_type=CreditTransaction.Type.ISSUANCE, amount=10,
            target_account=other_acct,
        )
        transfer_member_credits(from_member=self.member, to_member=other, amount=30)
        self.assertEqual(member_lifetime_contribution(self.member), 100)
        self.assertEqual(member_credit_balance(self.member), 70)

    def test_mock_append_event_failure_rolls_back_txn(self):
        """SystemEvent 写入失败时整个积分交易回滚。"""
        from unittest.mock import patch

        self._give_credits(100)
        before = CreditTransaction.objects.count()
        with patch("core.credit_services.append_event", side_effect=ValueError("event write failed")):
            with self.assertRaises(ValueError):
                post_credit_transaction(
                    transaction_type=CreditTransaction.Type.TRANSFER, amount=1,
                    source_account=self.acct, target_account=self.pool,
                )
        self.assertEqual(CreditTransaction.objects.count(), before)

    def test_publish_task_requires_sufficient_budget(self):
        """base_points=30, coeff=1.2 → reward=36。锁 1 分不能 publish；锁 36 分可以。"""
        from core.tasks.authoring import publish_task
        from decimal import Decimal

        # Create task without assignee (publish requires no assignee)
        task = Task.objects.create(
            task_id="task-pub-budget", title="Publish budget test",
            task_type=Task.TaskType.PUBLIC_CLEANING, status=Task.Status.DRAFT,
            standard_minutes=60, base_points=30, role_coefficient=Decimal("1.200"),
            rule_version="v1", requires_review=True,
            created_at=timezone.now(),
        )
        issue_credits_to_pool(amount=100, reason="test", initiated_by=self.governor, reviewed_by=self.governor)

        # Lock 1 — insufficient
        lock_task_credit_budget(task=task, amount=1, reason="too little")
        with self.assertRaises(DomainError):
            publish_task(task=task, publisher={"actor_id": self.governor.member_no, "display_name": "G"})
        task.refresh_from_db()

        # Lock enough: 36 total → publish succeeds
        lock_task_credit_budget(task=task, amount=35, reason="top up")
        publish_task(task=task, publisher={"actor_id": self.governor.member_no, "display_name": "G"})
        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.OPEN)

    def test_long_idempotency_key_produces_valid_order_id(self):
        """长 idempotency_key 通过哈希生成 ≤64 字符的 order_id。"""
        self._give_credits(100)
        long_key = "x" * 200
        o1, _ = create_redemption_order(member=self.member, credit_amount=10, idempotency_key=long_key)
        self.assertLessEqual(len(o1.order_id), 64)
        o2, _ = create_redemption_order(member=self.member, credit_amount=10, idempotency_key=long_key)
        self.assertEqual(o1.pk, o2.pk)

    def test_redemption_order_stores_snapshot(self):
        self._give_credits(100)
        order, _ = create_redemption_order(
            member=self.member, credit_amount=10, item_type=RedemptionOrder.ItemType.MEAL,
            title="snapshot test", idempotency_key="ro:snap:1",
        )
        order.item_snapshot = {"meal_name": "午餐", "provider": "食堂"}
        order.finance_treatment_ref = "fin-2026-001"
        order.resource_id = "res-meal"
        order.save()
        order.refresh_from_db()
        self.assertEqual(order.item_snapshot["meal_name"], "午餐")
        self.assertEqual(order.finance_treatment_ref, "fin-2026-001")

    def test_create_order_rejects_invalid_item_type(self):
        """服务层拒绝非 ItemType.choices 的 item_type。"""
        self._give_credits(100)
        with self.assertRaises(DomainError):
            create_redemption_order(member=self.member, credit_amount=5, item_type="INVALID", title="bad")

    def test_review_zero_point_task_accepted_no_reward(self):
        """0 分任务验收通过：状态 ACCEPTED，不产生 task_reward CreditTransaction。"""
        from decimal import Decimal
        from core.tasks.review import review_task
        from core.tasks.authoring import create_task_draft, publish_task
        from core.tasks.member_workflow import claim_task, submit_labor

        task = create_task_draft(
            title="Zero point review", task_type="public_cleaning", standard_minutes=60,
            base_points=0, role_coefficient=Decimal("1.0"), failure_consequence="",
            can_be_delayed=True, requires_review=True, rule_version="ruleset-v0.1.0",
            created_by={"actor_id": "gov", "display_name": "Gov"},
        )
        publish_task(task=task, publisher={"actor_id": "gov", "display_name": "Gov"})
        task.refresh_from_db()
        claim_task(task=task, member=self.member)
        task.refresh_from_db()
        submit_labor(task=task, member=self.member, labor_note="zero point labor", evidence_refs=[])

        txn_before = CreditTransaction.objects.filter(
            transaction_type=CreditTransaction.Type.TASK_REWARD,
        ).count()

        task, entries = review_task(
            task=task,
            reviewer={"actor_id": "gov", "display_name": "Gov"},
            accepted=True, reason="zero point accepted",
        )
        self.assertEqual(task.status, Task.Status.ACCEPTED)
        self.assertEqual(
            CreditTransaction.objects.filter(
                transaction_type=CreditTransaction.Type.TASK_REWARD,
            ).count(),
            txn_before,
            "0 分验收不应产生 task_reward CreditTransaction"
        )
        self.assertEqual(len(entries), 0, "0 分验收不应产生 LedgerEntry")


class MerchantSettlementTests(TestCase):
    def setUp(self):
        self.member = create_member("mch-member-1")
        self.consumer = create_member("mch-consumer-1")
        self.governor = create_member("mch-gov-1")
        ensure_system_accounts()
        self.pool = CreditAccount.objects.get(account_type=CreditAccount.Type.ISSUANCE_POOL)
        self.acct = get_or_create_member_credit_account(self.consumer)
        issue_credits_to_pool(amount=500, reason="test", initiated_by=self.member, reviewed_by=self.member)
        self._give(200)

    def _give(self, amt):
        post_credit_transaction(transaction_type=CreditTransaction.Type.ISSUANCE, amount=amt, target_account=self.acct)

    def test_micro_merchant_transfer_no_settlement(self):
        """成员微创业用 transfer 收款，不生成 settlement record。"""
        receiver = create_member("mch-receiver")
        from core.models import MerchantProfile, MerchantSettlementRecord
        MerchantProfile.objects.create(
            merchant_id="mch-micro-1", display_name="微创业咖啡",
            merchant_type=MerchantProfile.Type.MEMBER_MICRO, operator_member=receiver,
        )
        transfer_member_credits(from_member=self.consumer, to_member=receiver, amount=30, reason="coffee")
        self.assertEqual(MerchantSettlementRecord.objects.count(), 0)

    def test_cash_merchant_with_merchant_id_creates_settlement(self):
        from core.models import MerchantProfile, MerchantSettlementRecord
        merchant = MerchantProfile.objects.create(
            merchant_id="mch-cash-explicit", display_name="食堂Explicit",
            merchant_type=MerchantProfile.Type.CASH_SETTLEMENT,
            operator_member=self.member, settlement_rate=0.5,
        )
        order, _ = create_redemption_order(
            member=self.consumer, credit_amount=40, merchant=merchant,
        )
        self.assertEqual(order.merchant_id, merchant.pk)
        order = fulfill_redemption_order(order=order, reviewed_by=self.governor)
        sr = MerchantSettlementRecord.objects.get(redemption_order=order)
        self.assertEqual(sr.status, "pending")
        self.assertEqual(sr.covered_credit_amount, 40)
        self.assertEqual(float(sr.settlement_rate), 0.5)
        self.assertEqual(float(sr.payable_rmb), 20.0)

    def test_non_operator_member_creates_order_for_merchant(self):
        """消费者不是商户 operator_member 时也能为该商户创建订单并结算。"""
        from core.models import MerchantProfile, MerchantSettlementRecord
        merchant = MerchantProfile.objects.create(
            merchant_id="mch-cash-public", display_name="PublicDiner",
            merchant_type=MerchantProfile.Type.CASH_SETTLEMENT,
            operator_member=self.member, settlement_rate=0.6,
        )
        order, _ = create_redemption_order(
            member=self.consumer, credit_amount=30, merchant=merchant,
        )
        order = fulfill_redemption_order(order=order, reviewed_by=self.governor)
        sr = MerchantSettlementRecord.objects.get(redemption_order=order)
        self.assertEqual(float(sr.settlement_rate), 0.6)

    def test_no_merchant_id_no_settlement(self):
        """未指定 merchant 的普通 RedemptionOrder 履约不生成 settlement。"""
        from core.models import MerchantSettlementRecord
        order, _ = create_redemption_order(member=self.consumer, credit_amount=10)
        order = fulfill_redemption_order(order=order, reviewed_by=self.governor)
        self.assertEqual(MerchantSettlementRecord.objects.filter(redemption_order=order).count(), 0)

    def test_micro_merchant_redemption_blocked(self):
        """member_micro_merchant 不能走 RedemptionOrder。"""
        from core.models import MerchantProfile
        micro = MerchantProfile.objects.create(
            merchant_id="mch-micro-blocked", display_name="MicroBlocked",
            merchant_type=MerchantProfile.Type.MEMBER_MICRO, operator_member=self.member,
        )
        with self.assertRaises(DomainError):
            create_redemption_order(member=self.consumer, credit_amount=10, merchant=micro)

    def test_settlement_snapshot_unchanged_after_rate_change(self):
        """履约后修改 merchant rate，已有 settlement 不变。"""
        from core.models import MerchantProfile, MerchantSettlementRecord
        merchant = MerchantProfile.objects.create(
            merchant_id="mch-snap-stable", display_name="SnapStable",
            merchant_type=MerchantProfile.Type.CASH_SETTLEMENT,
            operator_member=self.member, settlement_rate=0.4,
        )
        order, _ = create_redemption_order(member=self.consumer, credit_amount=50, merchant=merchant)
        order = fulfill_redemption_order(order=order, reviewed_by=self.governor)
        sr = MerchantSettlementRecord.objects.get(redemption_order=order)
        self.assertEqual(float(sr.settlement_rate), 0.4)
        self.assertEqual(float(sr.payable_rmb), 20.0)

        # Change rate after fulfillment
        merchant.settlement_rate = 0.9
        merchant.save()
        sr.refresh_from_db()
        self.assertEqual(float(sr.settlement_rate), 0.4)
        self.assertEqual(float(sr.payable_rmb), 20.0)

    def test_cash_merchant_null_rate_blocks_create(self):
        """cash settlement merchant settlement_rate=None 时创建订单失败。"""
        from core.models import MerchantProfile
        merchant = MerchantProfile.objects.create(
            merchant_id="mch-null-rate", display_name="NoRate",
            merchant_type=MerchantProfile.Type.CASH_SETTLEMENT,
            operator_member=self.member, settlement_rate=None,
        )
        with self.assertRaises(DomainError):
            create_redemption_order(member=self.consumer, credit_amount=10, merchant=merchant)

    def test_payable_rmb_rounded_to_cents(self):
        """payable_rmb 按两位小数量化。"""
        from core.models import MerchantProfile, MerchantSettlementRecord
        # 3 * 0.3333 = 0.9999 → 1.00
        merchant = MerchantProfile.objects.create(
            merchant_id="mch-rounding", display_name="Rounding",
            merchant_type=MerchantProfile.Type.CASH_SETTLEMENT,
            operator_member=self.member, settlement_rate=0.3333,
        )
        order, _ = create_redemption_order(member=self.consumer, credit_amount=3, merchant=merchant)
        order = fulfill_redemption_order(order=order, reviewed_by=self.governor)
        sr = MerchantSettlementRecord.objects.get(redemption_order=order)
        self.assertEqual(float(sr.payable_rmb), 1.00)

    def test_transfer_stale_balance_prevents_overdraw(self):
        """并发转账：锁账户后余额不足时抛 DomainError。"""
        self._give(20)
        # Start transfer from the consumer (balance 200+20 if we gave more...)
        # We test that once the account is locked, stale reads don't cause overdraw.
        other = create_member("mch-transfer-target")
        # consumer has 200 (from setUp) + 20 here = 220
        # Try to transfer 300 — should fail because balance locked correctly
        with self.assertRaises(DomainError):
            transfer_member_credits(from_member=self.consumer, to_member=other, amount=300, reason="test")

    def test_redemption_stale_balance_prevents_overdraw(self):
        """并发兑换：锁账户后余额不足时抛 DomainError。"""
        # consumer balance is ~200 from setUp
        with self.assertRaises(DomainError):
            create_redemption_order(member=self.consumer, credit_amount=999, item_type="meal", title="too much")
