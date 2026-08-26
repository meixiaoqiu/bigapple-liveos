"""Task reward budgeting and funded-publication orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.db import router, transaction

from core.credit_services import (
    credit_balance,
    lock_task_credit_budget,
    task_locked_credit_balance,
)
from core.exceptions import DomainError
from core.models import CreditAccount, Member, Task


@dataclass(frozen=True)
class TaskBudgetStatus:
    """Structured snapshot of the credits required to publish one task."""

    expected_reward: int
    locked_budget: int
    pool_balance: int
    shortfall: int
    pool_deficit: int

    @property
    def can_fund(self) -> bool:
        return self.pool_deficit == 0


@dataclass(frozen=True)
class TaskFundingResult:
    """Outcome of an explicit attempt to fund and publish a task."""

    task: Task
    budget: TaskBudgetStatus
    published: bool


def task_expected_reward(task: Task) -> int:
    """Return the integer reward that must be budgeted for *task*."""

    if task.base_points <= 0:
        return 0
    return int(
        (Decimal(task.base_points) * task.role_coefficient).to_integral_value()
    )


def task_budget_status(
    task: Task,
    *,
    locked_budget: int | None = None,
    pool_balance: int | None = None,
) -> TaskBudgetStatus:
    """Return reward, current budget, pool balance, and non-negative shortfall."""

    if locked_budget is None:
        locked_budget = task_locked_credit_balance(task)
    if pool_balance is None:
        pool = CreditAccount.objects.filter(
            account_type=CreditAccount.Type.ISSUANCE_POOL
        ).first()
        pool_balance = credit_balance(pool) if pool is not None else 0
    expected_reward = task_expected_reward(task)
    shortfall = max(expected_reward - locked_budget, 0)
    return TaskBudgetStatus(
        expected_reward=expected_reward,
        locked_budget=locked_budget,
        pool_balance=pool_balance,
        shortfall=shortfall,
        pool_deficit=max(shortfall - pool_balance, 0),
    )


def fund_and_publish_task(
    *,
    task: Task,
    publisher: dict,
    initiated_by: Member,
    lock_reason: str = "任务发布自动锁定预算",
) -> TaskFundingResult:
    """Lock only the missing reward budget and publish a draft atomically.

    Insufficient issuance-pool balance is a structured, non-mutating outcome:
    the task remains a draft and no partial ``LOCK`` transaction is posted.
    All other domain failures roll back this operation.
    """

    database = router.db_for_write(Task)
    with transaction.atomic(using=database):
        locked_task = Task.objects.select_for_update().get(pk=task.pk)
        if locked_task.status != Task.Status.DRAFT:
            raise DomainError("只有草稿任务可以发布。")
        if locked_task.assignee_member_id:
            raise DomainError("已分配成员的任务不能发布为开放领取。")

        pool = CreditAccount.objects.select_for_update().filter(
            account_type=CreditAccount.Type.ISSUANCE_POOL
        ).first()
        if pool is None:
            raise DomainError("系统账户 issuance_pool 不存在，请先初始化系统账户。")

        locked_budget = task_locked_credit_balance(locked_task)
        current_pool_balance = credit_balance(pool)
        budget = task_budget_status(
            locked_task,
            locked_budget=locked_budget,
            pool_balance=current_pool_balance,
        )
        if not budget.can_fund:
            return TaskFundingResult(
                task=locked_task,
                budget=budget,
                published=False,
            )

        if budget.shortfall > 0:
            lock_task_credit_budget(
                task=locked_task,
                amount=budget.shortfall,
                reason=lock_reason,
                initiated_by=initiated_by,
            )

        from core.tasks.authoring import publish_task

        published_task = publish_task(task=locked_task, publisher=publisher)
        return TaskFundingResult(
            task=published_task,
            budget=budget,
            published=True,
        )


def create_task_with_funding(
    *,
    publisher: dict,
    initiated_by: Member,
    task_fields: dict,
) -> TaskFundingResult:
    """Create a task and attempt funded publication in one authority transaction.

    When the issuance pool is insufficient, the new task is intentionally
    committed as a draft and the returned result describes the exact deficit.
    Other failures roll back both task creation and funding/publication writes.
    """

    database = router.db_for_write(Task)
    with transaction.atomic(using=database):
        from core.tasks.authoring import create_task_draft

        task = create_task_draft(**task_fields)
        return fund_and_publish_task(
            task=task,
            publisher=publisher,
            initiated_by=initiated_by,
        )
