"""专业领域与外部确认的成员专业资格模型。"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .identity import Member


class ProfessionalDomain(models.Model):
    """可用于专业提案投票资格的领域定义。"""

    class Status(models.TextChoices):
        ACTIVE = "active", "启用"
        ARCHIVED = "archived", "已归档"

    code = models.SlugField("领域代码", max_length=64, unique=True)
    name = models.CharField("领域名称", max_length=100)
    description = models.TextField("领域说明", blank=True)
    status = models.CharField("状态", max_length=32, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "core_professional_domain"
        verbose_name = "专业领域"
        verbose_name_plural = "专业领域"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class MemberProfessionalQualification(models.Model):
    """由外部确认结果录入的成员专业资格权威事实。"""

    class Status(models.TextChoices):
        ACTIVE = "active", "有效"
        REVOKED = "revoked", "已撤销"
        EXPIRED = "expired", "已过期"

    member = models.ForeignKey(
        Member,
        on_delete=models.PROTECT,
        related_name="professional_qualifications",
        verbose_name="成员",
    )
    domain = models.ForeignKey(
        ProfessionalDomain,
        on_delete=models.PROTECT,
        related_name="member_qualifications",
        verbose_name="专业领域",
    )
    status = models.CharField("状态", max_length=32, choices=Status.choices, default=Status.ACTIVE)
    external_confirmation_source = models.CharField(
        "外部确认来源",
        max_length=255,
        help_text="记录外部面试、考试、执照核验或其他确认来源；系统不实现其评估流程。",
    )
    confirmed_by = models.ForeignKey(
        Member,
        on_delete=models.PROTECT,
        related_name="confirmed_professional_qualifications",
        verbose_name="确认人",
    )
    confirmed_at = models.DateTimeField("确认时间", default=timezone.now)
    valid_from = models.DateTimeField("生效时间", default=timezone.now)
    valid_until = models.DateTimeField("失效时间", null=True, blank=True)
    revoked_at = models.DateTimeField("撤销时间", null=True, blank=True)
    revoked_by = models.ForeignKey(
        Member,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="revoked_professional_qualifications",
        verbose_name="撤销处理人",
    )
    notes = models.TextField("备注", blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "core_member_professional_qualification"
        verbose_name = "成员专业资格"
        verbose_name_plural = "成员专业资格"
        indexes = [
            models.Index(fields=["member", "domain", "status"]),
            models.Index(fields=["domain", "status", "valid_until"]),
            models.Index(fields=["valid_from", "valid_until"]),
        ]

    def clean(self):
        super().clean()
        if not self.external_confirmation_source.strip():
            raise ValidationError({"external_confirmation_source": "外部确认来源不能为空。"})
        if self.valid_until and self.valid_until <= self.valid_from:
            raise ValidationError({"valid_until": "失效时间必须晚于生效时间。"})

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.member} / {self.domain} / {self.status}"
