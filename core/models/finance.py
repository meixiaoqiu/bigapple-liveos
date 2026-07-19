"""Finance models — expense claims, reviews, transactions.

All authority changes flow through core/finance_services.py.
Admin is read-only.
"""

from django.db import models

from .identity import Member


def _new_claim_id() -> str:
    from uuid import uuid4
    return f"expense-claim-{uuid4().hex[:12]}"


def _new_review_id() -> str:
    from uuid import uuid4
    return f"finance-review-{uuid4().hex[:12]}"


def _new_transaction_id() -> str:
    from uuid import uuid4
    return f"finance-tx-{uuid4().hex[:12]}"


class ExpenseClaim(models.Model):
    """A reimbursement / expense request submitted by a registered member."""

    class Category(models.TextChoices):
        SERVER = "server", "服务器"
        AI_USAGE = "ai_usage", "AI 使用费"
        SOFTWARE = "software", "软件"
        OPERATIONS = "operations", "运营支出"
        OTHER = "other", "其他"

    class Status(models.TextChoices):
        SUBMITTED = "submitted", "已提交"
        UNDER_REVIEW = "under_review", "审核中"
        APPROVED = "approved", "已批准"
        REJECTED = "rejected", "已拒绝"
        PAID = "paid", "已付款"
        WITHDRAWN = "withdrawn", "已撤回"

    claim_id = models.CharField(
        "报销 ID", max_length=64, unique=True, default=_new_claim_id,
        help_text="稳定的业务 ID。",
    )
    claimant_member = models.ForeignKey(
        Member, on_delete=models.PROTECT, related_name="expense_claims",
        verbose_name="申请人",
    )
    title = models.CharField("标题", max_length=120)
    description = models.TextField("支出说明", blank=True,
                                   help_text="描述这笔支出的用途和背景。")
    amount = models.DecimalField("金额", max_digits=12, decimal_places=2)
    currency = models.CharField("货币", max_length=8, default="CNY")
    expense_date = models.DateField("支出日期")
    vendor = models.CharField("收款方", max_length=255, blank=True,
                               help_text="供应商或收款方名称。")
    category = models.CharField(
        "类别", max_length=32, choices=Category.choices, default=Category.OTHER,
    )
    status = models.CharField(
        "状态", max_length=32, choices=Status.choices, default=Status.SUBMITTED,
    )
    public_note = models.TextField("公开备注", blank=True,
                                    help_text="可在公开页面展示的补充说明。")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "报销申请"
        verbose_name_plural = "报销申请"
        ordering = ("-created_at", "-id")

    def __str__(self):
        return f"{self.title} ({self.claim_id})"


class FinanceReview(models.Model):
    """A single review decision on an ExpenseClaim."""

    class Decision(models.TextChoices):
        APPROVED = "approved", "已批准"
        REJECTED = "rejected", "已拒绝"

    review_id = models.CharField(
        "审核 ID", max_length=64, unique=True, default=_new_review_id,
    )
    claim = models.ForeignKey(
        ExpenseClaim, on_delete=models.PROTECT, related_name="reviews",
        verbose_name="报销申请",
    )
    reviewer_member = models.ForeignKey(
        Member, on_delete=models.PROTECT, related_name="finance_reviews",
        verbose_name="审核人",
    )
    decision = models.CharField(
        "审核决定", max_length=16, choices=Decision.choices,
    )
    reason = models.TextField("审核理由", blank=True,
                               help_text="拒绝时必须填写理由。")
    reviewed_at = models.DateTimeField("审核时间", auto_now_add=True)

    class Meta:
        verbose_name = "财务审核"
        verbose_name_plural = "财务审核"

    def __str__(self):
        return f"{self.get_decision_display()} — {self.claim}"


class FinanceTransaction(models.Model):
    """Append-only public finance transaction record."""

    class TransactionType(models.TextChoices):
        REIMBURSEMENT = "reimbursement", "报销支出"
        INCOME = "income", "收入"
        EXPENSE = "expense", "支出"
        CORRECTION = "correction", "冲正"

    class Direction(models.TextChoices):
        IN = "in", "入账"
        OUT = "out", "出账"

    transaction_id = models.CharField(
        "流水 ID", max_length=64, unique=True, default=_new_transaction_id,
    )
    claim = models.ForeignKey(
        ExpenseClaim, on_delete=models.PROTECT, null=True, blank=True,
        related_name="transactions", verbose_name="关联报销",
    )
    transaction_type = models.CharField(
        "流水类型", max_length=32, choices=TransactionType.choices,
    )
    amount = models.DecimalField("金额", max_digits=12, decimal_places=2)
    currency = models.CharField("货币", max_length=8, default="CNY")
    direction = models.CharField(
        "方向", max_length=8, choices=Direction.choices,
        help_text="入账 or 出账。",
    )
    summary = models.CharField("摘要", max_length=255)
    occurred_at = models.DateTimeField("发生时间")
    recorded_by = models.ForeignKey(
        Member, on_delete=models.PROTECT, null=True, blank=True,
        related_name="recorded_transactions", verbose_name="记录人",
    )
    metadata = models.JSONField("扩展数据", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "财务流水"
        verbose_name_plural = "财务流水"
        ordering = ("-occurred_at", "-id")

    def __str__(self):
        return f"{self.get_transaction_type_display()} {self.amount} {self.currency}"

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValueError("FinanceTransaction is append-only; create a correction transaction instead.")
        return super().save(*args, **kwargs)
