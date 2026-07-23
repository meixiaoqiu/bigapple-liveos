"""Public procurement challenge / counter-offer model."""

from django.db import models
from django.utils import timezone

from .identity import Member
from .operations import SupplierQuote


class ProcurementChallenge(models.Model):
    class ChallengeType(models.TextChoices):
        QUESTION = "question", "质疑/提问"
        LOWER_PRICE = "lower_price", "更低价"
        QUALITY_CONCERN = "quality_concern", "质量疑虑"
        ALTERNATIVE_SUPPLY = "alternative_supply", "替代供应"

    class Status(models.TextChoices):
        SUBMITTED = "submitted", "已提交"
        ACCEPTED = "accepted", "已采纳"
        REJECTED = "rejected", "已拒绝"
        RESOLVED = "resolved", "已解决"

    challenge_id = models.CharField("质疑ID", max_length=64, primary_key=True)
    quote = models.ForeignKey(
        SupplierQuote, on_delete=models.PROTECT, related_name="challenges",
        verbose_name="被质疑报价",
    )
    submitted_by = models.ForeignKey(
        Member, on_delete=models.PROTECT, related_name="submitted_challenges",
        verbose_name="提交人",
    )
    challenge_type = models.CharField(
        "质疑类型", max_length=32, choices=ChallengeType.choices,
    )
    status = models.CharField(
        "状态", max_length=16, choices=Status.choices, default=Status.SUBMITTED,
    )
    public_reason = models.TextField("公开理由")
    proposed_unit_price = models.DecimalField(
        "建议单价", max_digits=14, decimal_places=2, null=True, blank=True,
    )
    proposed_quantity = models.DecimalField(
        "建议数量", max_digits=14, decimal_places=3, null=True, blank=True,
    )
    linked_quote = models.ForeignKey(
        SupplierQuote, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="challenge_sources",
        verbose_name="已转为正式报价",
    )
    reviewed_by = models.ForeignKey(
        Member, on_delete=models.PROTECT, null=True, blank=True,
        related_name="reviewed_challenges", verbose_name="处理人",
    )
    reviewed_at = models.DateTimeField("处理时间", null=True, blank=True)
    review_reason = models.TextField("处理理由", blank=True)
    created_at = models.DateTimeField("创建时间", default=timezone.now)
    updated_at = models.DateTimeField("更新时间", null=True, blank=True)

    class Meta:
        db_table = "core_procurement_challenge"
        verbose_name = "采购质疑"
        verbose_name_plural = "采购质疑"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.challenge_id}:{self.quote_id}:{self.challenge_type}"
