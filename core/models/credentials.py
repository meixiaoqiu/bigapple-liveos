"""Credential models — templates and grants.

Credentials are public facts, honours, certificates, achievements, or
gameplay identities.  They are NOT a permission source; runtime
authorisation MUST go through
``Member → active RoleAssignment → RolePermission → Permission``.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone


def generate_credential_grant_id() -> str:
    from uuid import uuid4

    return f"credential-grant-{uuid4().hex[:12]}"


class CredentialTemplate(models.Model):
    class CredentialType(models.TextChoices):
        FORMAL_NUMBER = "formal_number", "正式成员编号"
        BADGE = "badge", "勋章"
        CERTIFICATE = "certificate", "证书"
        NFT_PLACEHOLDER = "nft_placeholder", "NFT占位"

    class Status(models.TextChoices):
        ACTIVE = "active", "活跃"
        ARCHIVED = "archived", "已归档"

    class Visibility(models.TextChoices):
        PUBLIC = "public", "公开"
        INTERNAL = "internal", "内部"

    template_id = models.CharField(
        "模板 ID",
        max_length=128,
        unique=True,
        help_text="稳定的业务 ID，例如 credential-template-formal-member-number。",
    )
    code = models.CharField(
        "凭证编码",
        max_length=64,
        unique=True,
        help_text="程序内唯一编码，例如 formal_member_number。",
    )
    name = models.CharField("名称", max_length=255)
    description = models.TextField("说明", blank=True)
    credential_type = models.CharField(
        "凭证类型", max_length=32, choices=CredentialType.choices
    )
    status = models.CharField(
        "状态", max_length=32, choices=Status.choices, default=Status.ACTIVE
    )
    visibility = models.CharField(
        "可见性", max_length=32, choices=Visibility.choices, default=Visibility.PUBLIC
    )
    icon_url = models.URLField("图标 URL", blank=True)
    display_order = models.IntegerField("展示顺序", default=100)
    metadata = models.JSONField("扩展数据", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "凭证模板"
        verbose_name_plural = "凭证模板"
        ordering = ("display_order", "code")

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class CredentialGrant(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "活跃"
        REVOKED = "revoked", "已撤销"
        ARCHIVED = "archived", "已归档"

    class SourceType(models.TextChoices):
        SYSTEM = "system", "系统"
        PROPOSAL_EXECUTION = "proposal_execution", "提案执行"
        MANUAL = "manual", "手动"
        EARNED = "earned", "自动获得"

    grant_id = models.CharField(
        "发放 ID",
        max_length=96,
        unique=True,
        default=generate_credential_grant_id,
        help_text="业务 ID，自动生成。",
    )
    template = models.ForeignKey(
        CredentialTemplate,
        on_delete=models.PROTECT,
        related_name="grants",
        verbose_name="凭证模板",
    )
    member = models.ForeignKey(
        "Member",
        on_delete=models.PROTECT,
        related_name="credential_grants",
        verbose_name="成员",
    )
    serial_no = models.PositiveIntegerField(
        "序列号",
        null=True,
        blank=True,
        help_text="递增序列号，同一模板内唯一（如正式成员编号 1,2,3…）。",
    )
    display_no = models.CharField(
        "展示编号",
        max_length=32,
        blank=True,
        help_text="对外展示编号，例如 #1 或 #0001。",
    )
    title = models.CharField(
        "标题",
        max_length=255,
        blank=True,
        help_text="默认为模板名称；可单独覆写。",
    )
    status = models.CharField(
        "状态", max_length=32, choices=Status.choices, default=Status.ACTIVE
    )
    issued_at = models.DateTimeField("发放时间", default=timezone.now)
    issued_by = models.ForeignKey(
        "Member",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="issued_credentials",
        verbose_name="发放人",
    )
    source_type = models.CharField(
        "来源类型",
        max_length=32,
        choices=SourceType.choices,
        default=SourceType.SYSTEM,
        help_text="记录该凭证的授予来源。",
    )
    source_proposal = models.ForeignKey(
        "Proposal",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="credential_grants",
        verbose_name="来源提案",
    )
    source_proposal_execution = models.ForeignKey(
        "ProposalExecution",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="credential_grants",
        verbose_name="来源提案执行",
    )
    metadata = models.JSONField("扩展数据", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "凭证发放"
        verbose_name_plural = "凭证发放"
        ordering = ("template", "serial_no")
        constraints = [
            models.UniqueConstraint(
                fields=("template", "serial_no"),
                condition=models.Q(serial_no__isnull=False),
                name="unique_template_serial_no",
            ),
            models.UniqueConstraint(
                fields=("template", "display_no"),
                condition=~models.Q(display_no=""),
                name="unique_template_display_no",
            ),
        ]

    def __str__(self) -> str:
        label = f"{self.template.name}"
        if self.display_no:
            label += f" {self.display_no}"
        return f"{label} → {self.member.display_name or self.member.member_no}"
