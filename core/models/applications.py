"""Public application records for members and project partners."""

from django.conf import settings
from django.db import models

from .identity import Member


class MemberApplication(models.Model):
    """A public member application submitted through the real world-scoped entry."""

    class Status(models.TextChoices):
        SUBMITTED = "submitted", "已提交"
        UNDER_REVIEW = "under_review", "审核中"
        CANDIDATE = "candidate", "进入候选池"
        STANDBY = "standby", "备用"
        REJECTED = "rejected", "已拒绝"
        WITHDREW = "withdrew", "已退出"

    application_id = models.CharField("成员报名ID", max_length=96, primary_key=True)
    applicant_name = models.CharField("报名人名称", max_length=255)
    contact = models.CharField("联系方式", max_length=255)
    motivation = models.TextField("报名动机")
    availability_hours_per_week = models.PositiveIntegerField(
        "每周可投入小时",
        help_text="报名人自述的稳定可投入时间。",
    )
    capability_scores = models.JSONField(
        "能力自评",
        default=dict,
        blank=True,
        help_text="报名人自述能力，第一版用 key/value 结构保存。",
    )
    can_issue_responsibility_documents = models.BooleanField(
        "可出具责任文件",
        default=False,
        help_text="成员报名中通常为否；如果个人具备签字、盖章或合同责任能力，可标记为是。",
    )
    document_authority_domains = models.JSONField(
        "责任文件领域",
        default=list,
        blank=True,
        help_text="可出具或承担责任的文件领域，例如结构安全、电气并网。",
    )
    status = models.CharField("状态", max_length=32, choices=Status.choices, default=Status.SUBMITTED)
    requested_member_no = models.CharField("期望成员编号", max_length=64, blank=True)
    account_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="member_applications",
        verbose_name="报名账号",
        help_text="成员报名时创建的登录账号；审核通过后绑定到成员身份。",
    )
    linked_member = models.ForeignKey(
        Member,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="member_applications",
        verbose_name="关联成员",
    )
    reviewed_by = models.ForeignKey(
        Member,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reviewed_member_applications",
        verbose_name="审核人",
    )
    submitted_at = models.DateTimeField("提交时间")
    reviewed_at = models.DateTimeField("审核时间", null=True, blank=True)
    metadata = models.JSONField("扩展数据", default=dict, blank=True)

    class Meta:
        db_table = "core_member_application"
        verbose_name = "成员报名"
        verbose_name_plural = "成员报名"
        ordering = ["-submitted_at", "application_id"]
        indexes = [
            models.Index(fields=["status", "submitted_at"]),
            models.Index(fields=["requested_member_no"]),
        ]

    def __str__(self) -> str:
        return f"{self.application_id}:{self.applicant_name}"


class PartnerApplication(models.Model):
    """A public partner application for services, qualifications, and responsibility documents."""

    class Status(models.TextChoices):
        SUBMITTED = "submitted", "已提交"
        UNDER_REVIEW = "under_review", "审核中"
        QUALIFIED = "qualified", "可合作"
        STANDBY = "standby", "备用"
        REJECTED = "rejected", "已拒绝"
        WITHDREW = "withdrew", "已退出"

    application_id = models.CharField("合作方报名ID", max_length=96, primary_key=True)
    organization_name = models.CharField("合作方名称", max_length=255)
    contact_name = models.CharField("联系人", max_length=255)
    contact = models.CharField("联系方式", max_length=255)
    service_domains = models.JSONField(
        "服务能力",
        default=list,
        blank=True,
        help_text="合作方可提供的服务、能力或资质领域。",
    )
    can_issue_responsibility_documents = models.BooleanField(
        "可出具责任文件",
        default=False,
        help_text="是否能出具可归档、可追责、可作为决策依据的书面文件。",
    )
    responsibility_document_domains = models.JSONField(
        "责任文件领域",
        default=list,
        blank=True,
        help_text="可签署或盖章承担责任的文件领域。",
    )
    qualification_summary = models.TextField("资质说明", blank=True)
    quote_summary = models.TextField("报价说明", blank=True)
    service_area = models.CharField("服务地区", max_length=255, blank=True)
    delivery_cycle_days = models.PositiveIntegerField("交付周期天数", null=True, blank=True)
    constraints = models.TextField("限制条件", blank=True)
    status = models.CharField("状态", max_length=32, choices=Status.choices, default=Status.SUBMITTED)
    reviewed_by = models.ForeignKey(
        Member,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reviewed_partner_applications",
        verbose_name="审核人",
    )
    submitted_at = models.DateTimeField("提交时间")
    reviewed_at = models.DateTimeField("审核时间", null=True, blank=True)
    metadata = models.JSONField("扩展数据", default=dict, blank=True)

    class Meta:
        db_table = "core_partner_application"
        verbose_name = "合作方报名"
        verbose_name_plural = "合作方报名"
        ordering = ["-submitted_at", "application_id"]
        indexes = [
            models.Index(fields=["status", "submitted_at"]),
            models.Index(fields=["can_issue_responsibility_documents"]),
        ]

    def __str__(self) -> str:
        return f"{self.application_id}:{self.organization_name}"
