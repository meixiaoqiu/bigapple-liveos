"""Immutable business attachment authority records."""

from uuid import uuid4

from django.db import models

from .identity import Member


def _new_attachment_id() -> str:
    return f"attachment-{uuid4().hex[:16]}"


class Attachment(models.Model):
    """An immutable private original or separately stored public derivative."""

    class Audience(models.TextChoices):
        PRIVATE = "private", "私有"
        PUBLIC = "public", "公开"

    class Lifecycle(models.TextChoices):
        SEALED = "sealed", "已密封"
        SUPERSEDED = "superseded", "已更正"
        WITHDRAWN = "withdrawn", "已撤回"

    attachment_id = models.CharField("附件 ID", max_length=64, unique=True, default=_new_attachment_id)
    object_key = models.CharField("对象 key", max_length=512, unique=True, help_text="私有存储中的不可预测对象标识。")
    detected_media_type = models.CharField("检测媒体类型", max_length=128, help_text="由服务端内容识别得到的媒体类型。")
    display_filename = models.CharField("显示文件名", max_length=255, help_text="去除路径后的用户可见文件名，仅用于私有下载提示。")
    byte_size = models.PositiveBigIntegerField("字节数")
    sha256 = models.CharField("SHA-256", max_length=64, help_text="原始保留字节的十六进制摘要。")
    uploaded_by = models.ForeignKey(Member, on_delete=models.PROTECT, related_name="uploaded_attachments", verbose_name="上传人")
    audience = models.CharField("受众", max_length=16, choices=Audience.choices, default=Audience.PRIVATE)
    lifecycle = models.CharField("生命周期", max_length=16, choices=Lifecycle.choices, default=Lifecycle.SEALED)
    source_attachment = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="public_derivatives", verbose_name="来源原件", help_text="公开脱敏副本必须指向其私有来源原件。")
    supersedes = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="replacement_versions", verbose_name="更正前版本")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "业务附件"
        verbose_name_plural = "业务附件"
        ordering = ("created_at", "id")

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValueError("Attachment is immutable; create a new correction or public derivative.")
        return super().save(*args, **kwargs)


class ExpenseClaimAttachment(models.Model):
    """A real foreign-key association between an expense claim and evidence."""

    class Purpose(models.TextChoices):
        EXPENSE_EVIDENCE = "expense_evidence", "支出凭证"
        PAYMENT_EVIDENCE = "payment_evidence", "付款凭证"
        PUBLIC_MATERIAL = "public_material", "公开材料"

    claim = models.ForeignKey("core.ExpenseClaim", on_delete=models.PROTECT, related_name="attachment_links", verbose_name="报销申请")
    attachment = models.OneToOneField(Attachment, on_delete=models.PROTECT, related_name="expense_claim_link", verbose_name="附件")
    purpose = models.CharField("用途", max_length=32, choices=Purpose.choices)
    payment_execution = models.ForeignKey("core.PaymentExecution", on_delete=models.PROTECT, null=True, blank=True, related_name="attachment_links", verbose_name="付款执行")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        verbose_name = "报销附件关联"
        verbose_name_plural = "报销附件关联"

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValueError("ExpenseClaimAttachment is immutable.")
        return super().save(*args, **kwargs)
