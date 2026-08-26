from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch
from unittest import skipUnless

from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase

from core.credit_services import (
    ensure_system_accounts,
    issue_credits_to_pool,
    lock_task_credit_budget,
    task_locked_credit_balance,
)
from core.exceptions import DomainError
from core.models import CreditTransaction, Member, SystemEvent, Task
from core.service_utils import actor_ref
from core.tasks.authoring import create_task_draft
from core.tasks.funding import (
    create_task_with_funding,
    fund_and_publish_task,
    task_budget_status,
    task_expected_reward,
)
from core.tests.helpers import create_administrator_member


class TaskFundingTests(TestCase):
    def setUp(self) -> None:
        ensure_system_accounts()
        self.administrator = create_administrator_member("task-funding-admin")
        self.actor = actor_ref(self.administrator)

    def create_task(self, *, base_points: int = 30, coefficient: str = "1.200") -> Task:
        return create_task_draft(
            title="自动预算测试任务",
            task_type=Task.TaskType.PUBLIC_CLEANING,
            standard_minutes=60,
            base_points=base_points,
            role_coefficient=Decimal(coefficient),
            failure_consequence="",
            can_be_delayed=True,
            requires_review=True,
            rule_version="ruleset-v0.1.0",
            created_by=self.actor,
        )

    def issue(self, amount: int) -> None:
        issue_credits_to_pool(
            amount=amount,
            reason="测试发行",
            initiated_by=self.administrator,
            reviewed_by=self.administrator,
        )

    def test_budget_status_covers_zero_partial_full_and_excess_budget(self) -> None:
        task = self.create_task()

        self.assertEqual(task_expected_reward(task), 36)
        self.assertEqual(
            task_budget_status(task, locked_budget=0, pool_balance=100).shortfall,
            36,
        )
        self.assertEqual(
            task_budget_status(task, locked_budget=10, pool_balance=100).shortfall,
            26,
        )
        self.assertEqual(
            task_budget_status(task, locked_budget=36, pool_balance=0).shortfall,
            0,
        )
        self.assertEqual(
            task_budget_status(task, locked_budget=50, pool_balance=0).shortfall,
            0,
        )
        zero_task = self.create_task(base_points=0)
        self.assertEqual(task_expected_reward(zero_task), 0)

    def test_fund_and_publish_locks_only_missing_budget(self) -> None:
        self.issue(100)
        task = self.create_task()
        lock_task_credit_budget(
            task=task,
            amount=10,
            reason="已有预算",
            initiated_by=self.administrator,
        )

        result = fund_and_publish_task(
            task=task,
            publisher=self.actor,
            initiated_by=self.administrator,
        )

        self.assertTrue(result.published)
        self.assertEqual(result.budget.shortfall, 26)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.OPEN)
        self.assertEqual(task_locked_credit_balance(task), 36)
        self.assertEqual(
            list(
                CreditTransaction.objects.filter(
                    transaction_type=CreditTransaction.Type.LOCK,
                    related_task=task,
                ).values_list("amount", flat=True)
            ),
            [10, 26],
        )
        automatic_lock = CreditTransaction.objects.filter(
            transaction_type=CreditTransaction.Type.LOCK,
            related_task=task,
        ).latest("created_at")
        self.assertEqual(automatic_lock.initiated_by, self.administrator)
        self.assertTrue(
            SystemEvent.objects.filter(
                event_type=SystemEvent.EventType.TASK_PUBLISHED,
                aggregate_id=task.task_id,
            ).exists()
        )

    def test_insufficient_pool_returns_structured_non_mutating_result(self) -> None:
        self.issue(20)
        task = self.create_task()

        result = fund_and_publish_task(
            task=task,
            publisher=self.actor,
            initiated_by=self.administrator,
        )

        self.assertFalse(result.published)
        self.assertEqual(result.budget.expected_reward, 36)
        self.assertEqual(result.budget.locked_budget, 0)
        self.assertEqual(result.budget.pool_balance, 20)
        self.assertEqual(result.budget.shortfall, 36)
        self.assertEqual(result.budget.pool_deficit, 16)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.DRAFT)
        self.assertFalse(
            CreditTransaction.objects.filter(
                transaction_type=CreditTransaction.Type.LOCK,
                related_task=task,
            ).exists()
        )
        self.assertFalse(
            SystemEvent.objects.filter(
                event_type=SystemEvent.EventType.TASK_PUBLISHED,
                aggregate_id=task.task_id,
            ).exists()
        )

    def test_publication_failure_rolls_back_automatic_lock(self) -> None:
        self.issue(100)
        task = self.create_task()

        with patch(
            "core.tasks.authoring.publish_task",
            side_effect=DomainError("模拟发布失败"),
        ):
            with self.assertRaisesRegex(DomainError, "模拟发布失败"):
                fund_and_publish_task(
                    task=task,
                    publisher=self.actor,
                    initiated_by=self.administrator,
                )

        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.DRAFT)
        self.assertEqual(task_locked_credit_balance(task), 0)
        self.assertFalse(
            CreditTransaction.objects.filter(
                transaction_type=CreditTransaction.Type.LOCK,
                related_task=task,
            ).exists()
        )

    def test_create_with_insufficient_pool_commits_only_draft(self) -> None:
        self.issue(20)

        result = create_task_with_funding(
            publisher=self.actor,
            initiated_by=self.administrator,
            task_fields={
                "title": "余额不足时保留草稿",
                "task_type": Task.TaskType.PUBLIC_CLEANING,
                "standard_minutes": 60,
                "base_points": 36,
                "role_coefficient": Decimal("1.0"),
                "failure_consequence": "",
                "can_be_delayed": True,
                "requires_review": True,
                "rule_version": "ruleset-v0.1.0",
                "created_by": self.actor,
            },
        )

        self.assertFalse(result.published)
        self.assertEqual(result.task.status, Task.Status.DRAFT)
        self.assertEqual(result.budget.pool_deficit, 16)
        self.assertEqual(
            list(
                SystemEvent.objects.filter(
                    event_type__in=[
                        SystemEvent.EventType.CREDIT_ADJUSTED,
                        SystemEvent.EventType.TASK_CREATED,
                        SystemEvent.EventType.TASK_PUBLISHED,
                    ]
                ).order_by("seq").values_list("event_type", flat=True)
            ),
            [SystemEvent.EventType.CREDIT_ADJUSTED, SystemEvent.EventType.TASK_CREATED],
        )
        self.assertEqual(
            CreditTransaction.objects.filter(
                transaction_type=CreditTransaction.Type.ISSUANCE
            ).count(),
            1,
        )
        self.assertFalse(
            CreditTransaction.objects.filter(
                transaction_type=CreditTransaction.Type.LOCK
            ).exists()
        )


@skipUnless(connection.vendor == "mysql", "发行池行锁竞争仅在 MySQL 测试数据库执行。")
class TaskFundingConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self) -> None:
        ensure_system_accounts()
        administrator = create_administrator_member("task-funding-race-admin")
        self.administrator_id = administrator.pk
        issue_credits_to_pool(
            amount=50,
            reason="并发发布测试发行",
            initiated_by=administrator,
            reviewed_by=administrator,
        )
        self.task_ids = [self._create_task("a").pk, self._create_task("b").pk]

    def _create_task(self, suffix: str) -> Task:
        administrator = Member.objects.get(pk=self.administrator_id)
        return create_task_draft(
            title=f"并发预算任务 {suffix}",
            task_type=Task.TaskType.PUBLIC_CLEANING,
            standard_minutes=60,
            base_points=40,
            role_coefficient=Decimal("1.0"),
            failure_consequence="",
            can_be_delayed=True,
            requires_review=True,
            rule_version="ruleset-v0.1.0",
            created_by=actor_ref(administrator),
        )

    def test_concurrent_publications_cannot_overspend_issuance_pool(self) -> None:
        barrier = Barrier(2)

        def publish(task_id: str) -> tuple[str, bool]:
            close_old_connections()
            try:
                administrator = Member.objects.get(pk=self.administrator_id)
                task = Task.objects.get(pk=task_id)
                barrier.wait(timeout=5)
                result = fund_and_publish_task(
                    task=task,
                    publisher=actor_ref(administrator),
                    initiated_by=administrator,
                )
                return task_id, result.published
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [
                future.result(timeout=20)
                for future in (
                    executor.submit(publish, self.task_ids[0]),
                    executor.submit(publish, self.task_ids[1]),
                )
            ]

        published_ids = {task_id for task_id, published in results if published}
        failed_ids = set(self.task_ids) - published_ids
        self.assertEqual(len(published_ids), 1)
        self.assertEqual(len(failed_ids), 1)
        self.assertEqual(
            sum(
                CreditTransaction.objects.filter(
                    transaction_type=CreditTransaction.Type.LOCK,
                ).values_list("amount", flat=True)
            ),
            40,
        )
        self.assertLessEqual(
            sum(
                CreditTransaction.objects.filter(
                    transaction_type=CreditTransaction.Type.LOCK,
                ).values_list("amount", flat=True)
            ),
            50,
        )
        self.assertEqual(
            Task.objects.get(pk=next(iter(published_ids))).status,
            Task.Status.OPEN,
        )
        failed_id = next(iter(failed_ids))
        self.assertEqual(Task.objects.get(pk=failed_id).status, Task.Status.DRAFT)
        self.assertFalse(
            CreditTransaction.objects.filter(
                transaction_type=CreditTransaction.Type.LOCK,
                related_task_id=failed_id,
            ).exists()
        )
        self.assertFalse(
            SystemEvent.objects.filter(
                event_type=SystemEvent.EventType.TASK_PUBLISHED,
                aggregate_id=failed_id,
            ).exists()
        )
