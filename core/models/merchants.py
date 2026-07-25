"""Merchant profile and settlement record models.

member_micro_merchant: revenue flows into member credit account
  via existing transfer.  No settlement record is created.

cash_settlement_merchant: credits are burned on fulfillment;
  a MerchantSettlementRecord tracks the payable RMB amount.
  The merchant does NOT hold a credit account.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from .identity import Member


class MerchantProfile(models.Model):
    """A merchant entity — operator_member is the member who manages it."""

    class Type(models.TextChoices):
        MEMBER_MICRO = "member_micro_merchant", "成员微创业"
        CASH_SETTLEMENT = "cash_settlement_merchant", "现金结算商户"

    class Status(models.TextChoices):
        ACTIVE = "active", "营业中"
        SUSPENDED = "suspended", "已暂停"
        CLOSED = "closed", "已关闭"

    merchant_id = models.CharField(
        "商户ID", max_length=64, primary_key=True,
        help_text="商户唯一标识。现金结算商户不持有积分账户。",
    )
    display_name = models.CharField("商户名称", max_length=128)
    operator_member = models.ForeignKey(
        Member, null=True, blank=True, on_delete=models.PROTECT,
        related_name="operated_merchants", verbose_name="经营成员",
        help_text="经营该商户的成员。商户不拥有独立的积分账户。",
    )
    merchant_type = models.CharField(
        "商户类型", max_length=32, choices=Type.choices,
        help_text="cash_settlement_merchant 积分消费后销毁并生成人民币应付款；"
        "member_micro_merchant 使用自由转账，不生成结算。",
    )
    status = models.CharField(
        "状态", max_length=16, choices=Status.choices, default=Status.ACTIVE,
        help_text="营业状态。非 active 商户不能接受新兑换订单。",
    )
    settlement_rate = models.DecimalField(
        "结算汇率", max_digits=8, decimal_places=4, null=True, blank=True,
        help_text="仅 cash_settlement 商户使用。如 0.5 表示 1 积分 = 0.5 元人民币。"
        "履约时快照写入 settlement record，不受后续修改影响。",
    )
    metadata = models.JSONField("扩展数据", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", default=timezone.now)
    updated_at = models.DateTimeField("更新时间", null=True, blank=True)

    class Meta:
        db_table = "core_merchant_profile"
        verbose_name = "商户资料"
        verbose_name_plural = "商户资料"
        indexes = [
            models.Index(fields=["merchant_type"]),
            models.Index(fields=["operator_member"]),
        ]

    def __str__(self) -> str:
        return self.display_name


class MerchantSettlementRecord(models.Model):
    """Settlement record for cash_settlement_merchant redemptions.

    Records the RMB payable after credits are burned — this is NOT
    a credit balance and NOT a credit withdrawal.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "待结算"
        APPROVED = "approved", "已批准"
        PAID = "paid", "已付款"
        DISPUTED = "disputed", "争议"
        CANCELLED = "cancelled", "已取消"

    settlement_id = models.CharField("结算ID", max_length=64, primary_key=True)
    merchant = models.ForeignKey(
        MerchantProfile, on_delete=models.PROTECT,
        related_name="settlement_records", verbose_name="商户",
    )
    redemption_order = models.OneToOneField(
        "RedemptionOrder", on_delete=models.PROTECT,
        related_name="settlement_record", verbose_name="兑换订单",
        help_text="关联的兑换订单。每笔结算必须对应一笔订单。",
    )
    covered_credit_amount = models.IntegerField(
        "覆盖积分数",
        help_text="本次结算覆盖的消费积分数（不是商户积分余额）。"
        "商户不持有可流通积分。",
    )
    settlement_rate = models.DecimalField(
        "结算汇率", max_digits=8, decimal_places=4,
        help_text="履约时快照写入的结算汇率，不受商户配置后续修改影响。",
    )
    payable_rmb = models.DecimalField(
        "应付人民币", max_digits=12, decimal_places=2,
        help_text="人民币应付结算金额（不是积分提现）。按两位小数量化。",
    )
    status = models.CharField(
        "状态", max_length=16, choices=Status.choices, default=Status.PENDING,
        help_text="pending 表示已生成应付款记录但尚未批准/支付。",
    )
    reason = models.TextField("备注", blank=True)
    metadata = models.JSONField("扩展数据", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", default=timezone.now)
    updated_at = models.DateTimeField("更新时间", null=True, blank=True)

    class Meta:
        db_table = "core_merchant_settlement_record"
        verbose_name = "商户结算记录"
        verbose_name_plural = "商户结算记录"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["merchant", "status"]),
        ]

    def __str__(self) -> str:
        return self.settlement_id
