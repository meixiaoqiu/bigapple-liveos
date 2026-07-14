"""Public application records for members and project partners."""

from django.conf import settings
from django.db import models

from .identity import Member


# Centralized Chinese display labels for role_gap values.
# Used by workspace templates and applicant-facing pages to avoid
# hard-coding English keys in multiple templates.
ROLE_GAP_LABELS: dict[str, str] = {
    "settled_resident": "安居成员",
    "service_resident": "生活服务成员",
    "developer_ai_engineer": "系统开发与 AI 工程",
    "community_contributor": "社区贡献者",
}


class MemberApplication(models.Model):
    """A public member application submitted through the real world-scoped entry.

    Statuses reflect the proposal-driven admission lifecycle, not a standalone
    review state machine.  Former ``candidate`` / ``standby`` have been removed;
    simulation screening decisions live in ``metadata.screening_status`` only.
    """

    class Status(models.TextChoices):
        SUBMITTED = "submitted", "已提交"
        ADMISSION_VOTING = "admission_voting", "准入表决中"
        ADMITTED = "admitted", "已接纳"
        REJECTED = "rejected", "已拒绝"
        WITHDREW = "withdrew", "已退出"

    application_id = models.CharField("成员报名ID", max_length=96, primary_key=True)
    applicant_name = models.CharField("报名人名称", max_length=255)
    contact = models.CharField("联系方式", max_length=255)
    motivation = models.TextField("报名动机")
    availability_hours_per_week = models.PositiveIntegerField(
        "每周可投入小时",
        default=0,
        help_text="历史兼容字段；当前报名表以 availability_slots 表达可参与时段。",
    )
    role_gap = models.CharField(
        "意向角色缺口",
        max_length=64,
        blank=True,
        default="",
        help_text="报名人选择的当前社区角色缺口，例如 settled_resident 或 developer_ai_engineer。",
    )
    availability_slots = models.JSONField(
        "可参与时段",
        default=list,
        blank=True,
        help_text="当前报名表的多选时段，例如 any_time、off_hours、weekend。",
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
        help_text="成员报名时创建或复用的登录账号；提交后立即绑定到最小权限成员身份。",
    )
    linked_member = models.ForeignKey(
        Member,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="member_applications",
        verbose_name="关联成员",
    )
    dynamic_answers = models.JSONField(
        "动态问答",
        default=list,
        blank=True,
        help_text="报名表中会随业务调整的 textarea 问答数组，元素包含 key、label、type、answer。",
    )
    frozen_at = models.DateTimeField(
        "提交确认时间",
        null=True,
        blank=True,
        help_text="报名提交并二次确认的时间；业务入口不提供提交后的撤回或修改。",
    )
    admission_proposal = models.ForeignKey(
        "Proposal",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="member_admission_applications",
        verbose_name="准入提案",
        help_text="用于接纳该报名成员的治理提案；通过后仍需显式执行。",
    )
    decided_by = models.ForeignKey(
        Member,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="decided_member_applications",
        verbose_name="决议人",
        help_text="执行准入提案或拒绝的治理成员；不再表示单人审核。",
    )
    submitted_at = models.DateTimeField("提交时间")
    decided_at = models.DateTimeField("决议时间", null=True, blank=True, help_text="准入执行或拒绝的时间。")
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
