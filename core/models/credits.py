"""Authoritative double-entry credit ledger models.

``CreditAccount`` holds system and member credit balances that are
**always** derived from posted ``CreditTransaction`` rows — balances
are never directly editable.

``CreditTransaction`` is the authoritative source of truth for every
credit movement.  ``LedgerEntry`` (in ``operations.py``) remains a
member-facing projection maintained alongside these transactions.

``idempotency_key`` is a plain ``unique=True`` nullable column.  When
non-null, the database guarantees at most one row per key.  Empty /
null keys ignore the constraint (MySQL treats NULLs as distinct).
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .identity import Member
from .operations import Task, LedgerEntry


class CreditAccount(models.Model):
    """A position that holds credits — system pool, task lock, member, frozen, or burn.

    Member accounts are 1:1 with ``Member``.  System accounts have
    ``member=None``.  Uniqueness of (account_type, member) for member
    accounts is enforced by ``credit_services.get_or_create_member_credit_account``.
    """

    class Type(models.TextChoices):
        ISSUANCE_POOL = "issuance_pool", "发行池"
        TASK_LOCKED = "task_locked", "任务锁定"
        MEMBER = "member", "成员"
        FROZEN = "frozen", "冻结"
        BURN = "burn", "销毁"

    class Status(models.TextChoices):
        ACTIVE = "active", "正常"
        FROZEN = "frozen", "已冻结"
        CLOSED = "closed", "已关闭"

    account_id = models.CharField("账户ID", max_length=64, primary_key=True)
    account_type = models.CharField("账户类型", max_length=24, choices=Type.choices)
    member = models.OneToOneField(
        Member,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="credit_account",
        verbose_name="成员",
        help_text="仅 member 类型账户使用；系统账户(issuance_pool/task_locked/frozen/burn)此项必须为 None。",
    )
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.ACTIVE)
    metadata = models.JSONField("扩展数据", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", default=timezone.now)
    updated_at = models.DateTimeField("更新时间", null=True, blank=True)

    class Meta:
        db_table = "core_credit_account"
        verbose_name = "积分账户"
        verbose_name_plural = "积分账户"
        indexes = [
            models.Index(fields=["account_type"]),
            models.Index(fields=["member"]),
        ]

    def clean(self):
        super().clean()
        if self.account_type == self.Type.MEMBER and self.member_id is None:
            raise ValidationError({"member": "member 类型账户必须关联一个成员。"})
        if self.account_type != self.Type.MEMBER and self.member_id is not None:
            raise ValidationError(
                {"member": f"{self.account_type} 类型账户不能关联成员。"}
            )

    def __str__(self) -> str:
        return self.account_id


class CreditTransaction(models.Model):
    """Authoritative double-entry credit movement between two accounts.

    Every credit change is recorded here.  Balances are derived by
    summing posted transactions, never by editing ``CreditAccount``
    fields directly.

    ``idempotency_key`` is a plain unique nullable column (no
    conditional constraint → no MySQL W036).  Null keys allow
    multiple transactions; non-null keys are guaranteed unique at
    the DB level.
    """

    class Type(models.TextChoices):
        ISSUANCE = "issuance", "发行"
        LOCK = "lock", "预算锁定"
        UNLOCK = "unlock", "预算退回"
        TASK_REWARD = "task_reward", "任务奖励"
        TRANSFER = "transfer", "自由转账"
        CONSUME = "consume", "消费冻结"
        BURN = "burn", "销毁"
        FREEZE = "freeze", "冻结"
        UNFREEZE = "unfreeze", "解冻"
        CORRECTION = "correction", "更正"
        REVERSAL = "reversal", "冲正"

    class Status(models.TextChoices):
        POSTED = "posted", "已入账"
        # VOID is deprecated — use reversal instead.  Kept only for
        # migration backward-compatibility; no service function may
        # set or read VOID as a business path.
        VOID = "void", "已作废"

    transaction_id = models.CharField("交易ID", max_length=64, primary_key=True)
    transaction_type = models.CharField("交易类型", max_length=24, choices=Type.choices)
    source_account = models.ForeignKey(
        CreditAccount,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="outgoing_transactions",
        verbose_name="来源账户",
        help_text="积分从此账户转出。",
    )
    target_account = models.ForeignKey(
        CreditAccount,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="incoming_transactions",
        verbose_name="目标账户",
        help_text="积分转入此账户。",
    )
    amount = models.IntegerField("积分数量", help_text="正数，实际转移的积分数量。")
    related_task = models.ForeignKey(
        Task,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="credit_transactions",
        verbose_name="关联任务",
    )
    related_ledger_entry = models.ForeignKey(
        LedgerEntry,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="credit_transactions",
        verbose_name="关联流水投影",
        help_text="成员视角 LedgerEntry 投影。",
    )
    related_event_id = models.CharField(
        "关联事件ID", max_length=64, blank=True,
        help_text="关联 SystemEvent.event_id，构成审计哈希链。",
    )
    initiated_by = models.ForeignKey(
        Member,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="initiated_credit_txns",
        verbose_name="发起人",
        help_text="业务发起人（不一定是系统操作员）。",
    )
    reviewed_by = models.ForeignKey(
        Member,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reviewed_credit_txns",
        verbose_name="审核人",
        help_text="治理/财务审核人。",
    )
    reason = models.TextField("原因", blank=True)
    metadata = models.JSONField(
        "扩展数据", default=dict, blank=True,
        help_text="扩展结构化数据。不在公开页展示。",
    )
    idempotency_key = models.CharField(
        "幂等键",
        max_length=191,
        null=True,
        blank=True,
        unique=True,
        default=None,
        help_text="数据库级唯一（plain unique，无 conditional）。NULL 允许多笔；非空重复即冲突。",
    )
    reverses_transaction = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reversed_by",
        verbose_name="冲正原交易",
    )
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.POSTED)
    prev_hash = models.CharField("前一交易哈希", max_length=128, default="", blank=True)
    transaction_hash = models.CharField("交易哈希", max_length=128, default="", blank=True)
    created_at = models.DateTimeField("创建时间", default=timezone.now)

    class Meta:
        db_table = "core_credit_transaction"
        verbose_name = "积分交易"
        verbose_name_plural = "积分交易"
        indexes = [
            models.Index(fields=["source_account"]),
            models.Index(fields=["target_account"]),
            models.Index(fields=["transaction_type"]),
            models.Index(fields=["status"]),
            models.Index(fields=["related_task"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self) -> str:
        return self.transaction_id


class RedemptionOrder(models.Model):
    """A member-initiated redemption order that freezes credits on creation
    and burns them on fulfillment.  Cancelled orders unfreeze credits
    back to the member.

    All credit movements are recorded as ``CreditTransaction`` rows —
    this model tracks only the order lifecycle.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "待履约"
        FULFILLED = "fulfilled", "已履约"
        CANCELLED = "cancelled", "已取消"
        DISPUTED = "disputed", "争议中"
        REVERSED = "reversed", "已冲正"

    class ItemType(models.TextChoices):
        MEAL = "meal", "餐食"
        GOODS = "goods", "物资"
        RESOURCE_USE = "resource_use", "资源使用"
        ROOM_UPGRADE = "room_upgrade", "房间升级"
        STORAGE = "storage", "仓储"
        PARKING = "parking", "泊车"
        TRAINING = "training", "培训"
        SERVICE = "service", "服务"
        FEE_REDUCTION = "fee_reduction", "费用减免"
        OTHER = "other", "其他"

    order_id = models.CharField("订单ID", max_length=64, primary_key=True)
    member = models.ForeignKey(
        Member,
        on_delete=models.PROTECT,
        related_name="redemption_orders",
        verbose_name="成员",
    )
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.PENDING)
    item_type = models.CharField("项目类型", max_length=24, choices=ItemType.choices, default=ItemType.OTHER)
    title = models.CharField("标题", max_length=256)
    original_amount_rmb = models.DecimalField(
        "原价(元)", max_digits=10, decimal_places=2, null=True, blank=True,
    )
    credit_amount = models.IntegerField("积分数量")
    cash_amount_rmb = models.DecimalField(
        "现金(元)", max_digits=10, decimal_places=2, null=True, blank=True,
    )
    merchant = models.ForeignKey(
        "MerchantProfile", null=True, blank=True, on_delete=models.PROTECT,
        related_name="redemption_orders", verbose_name="商户",
        help_text="现金结算商户。空表示普通成员兑换。",
    )
    related_task = models.ForeignKey(
        Task, null=True, blank=True, on_delete=models.PROTECT,
        related_name="redemption_orders", verbose_name="关联任务",
    )
    related_event_id = models.CharField(
        "关联事件ID", max_length=64, blank=True,
        help_text="关联 SystemEvent.event_id，用于审计链。",
    )
    reason = models.TextField("原因", blank=True)
    metadata = models.JSONField(
        "扩展数据", default=dict, blank=True,
        help_text="扩展结构化数据。不在公开页展示。",
    )
    # ── Step 3 additional reference fields ──
    resource_id = models.CharField(
        "关联资源ID", max_length=96, blank=True,
        help_text="关联 Resource.resource_id。",
    )
    item_snapshot = models.JSONField(
        "商品/服务快照", default=dict, blank=True,
        help_text="兑换项目结构化快照。",
    )
    finance_treatment_ref = models.CharField(
        "财务处理引用", max_length=128, blank=True,
        help_text="后续财务处理的外部引用标识。",
    )
    created_by = models.ForeignKey(
        Member, null=True, blank=True, on_delete=models.PROTECT,
        related_name="created_redemption_orders", verbose_name="创建人",
    )
    reviewed_by = models.ForeignKey(
        Member, null=True, blank=True, on_delete=models.PROTECT,
        related_name="reviewed_redemption_orders", verbose_name="审核人",
    )
    created_at = models.DateTimeField("创建时间", default=timezone.now)
    updated_at = models.DateTimeField("更新时间", null=True, blank=True)
    fulfilled_at = models.DateTimeField("履约时间", null=True, blank=True)
    cancelled_at = models.DateTimeField("取消时间", null=True, blank=True)

    class Meta:
        db_table = "core_redemption_order"
        verbose_name = "兑换订单"
        verbose_name_plural = "兑换订单"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["member", "status"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return self.order_id
