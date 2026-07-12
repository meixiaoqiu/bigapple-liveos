"""Dispute and capacity assessment models."""

from django.db import models

from .identity import Member
from .operations import LedgerEntry, Task


class Dispute(models.Model):
    """Real-name dispute or appeal record."""

    class DisputeType(models.TextChoices):
        TASK_REVIEW = "task_review", "任务验收"
        POINTS_DEDUCTION = "points_deduction", "积分扣除"
        RESOURCE_USAGE = "resource_usage", "资源使用"
        PUBLIC_HYGIENE = "public_hygiene", "公共卫生"
        NOISE = "noise", "噪音"
        WAREHOUSE_LOSS = "warehouse_loss", "仓库丢失"
        CANTEEN_QUALITY = "canteen_quality", "食堂质量"
        MEMBER_CONFLICT = "member_conflict", "成员冲突"
        GOVERNANCE_ACTION = "governance_action", "治理处置"
        EXIT = "exit", "退出"

    class Status(models.TextChoices):
        SUBMITTED = "submitted", "已提交"
        IN_REVIEW = "in_review", "处理中"
        RESOLVED = "resolved", "已解决"
        REJECTED = "rejected", "已驳回"
        APPEALED = "appealed", "已上诉"
        REVERSED = "reversed", "已撤销"

    dispute_id = models.CharField("申诉ID", max_length=64, primary_key=True)
    dispute_type = models.CharField("申诉类型", max_length=32, choices=DisputeType.choices)
    status = models.CharField("状态", max_length=32, choices=Status.choices)
    claimant_member = models.ForeignKey(
        Member,
        on_delete=models.PROTECT,
        related_name="submitted_disputes",
        verbose_name="申诉人",
    )
    respondent_member = models.ForeignKey(
        Member,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="received_disputes",
        verbose_name="被申诉人",
    )
    related_task = models.ForeignKey(
        Task,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="disputes",
        verbose_name="关联任务",
    )
    related_ledger_entry = models.ForeignKey(
        LedgerEntry,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="disputes",
        verbose_name="关联积分流水",
    )
    facts = models.TextField("事实陈述")
    evidence_refs = models.JSONField("证据引用", default=list, blank=True)
    handler = models.JSONField("处理人", default=dict, blank=True)
    reviewer = models.JSONField("复核人", default=dict, blank=True)
    resolution = models.TextField("处理结果", blank=True)
    appeal_path = models.CharField("申诉路径", max_length=255)
    submitted_at = models.DateTimeField("提交时间")
    resolved_at = models.DateTimeField("解决时间", null=True, blank=True)
    metadata = models.JSONField("扩展数据", default=dict, blank=True)

    class Meta:
        db_table = "core_dispute"
        verbose_name = "申诉"
        verbose_name_plural = "申诉"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["claimant_member"]),
        ]

    def __str__(self) -> str:
        return self.dispute_id


class CapacityAssessment(models.Model):
    """Capacity decision record controlling whether new members can enter."""

    assessment_id = models.CharField("容量评估ID", max_length=64, primary_key=True)
    simulation_day = models.PositiveIntegerField("模拟日期")
    current_formal_members = models.PositiveIntegerField("当前正式成员数")
    current_candidate_members = models.PositiveIntegerField("当前候选成员数")
    maximum_admissible_members = models.PositiveIntegerField("当前最大可接纳人数")
    recommended_new_members = models.PositiveIntegerField("建议新增人数")
    bottlenecks = models.JSONField("容量瓶颈", default=list)
    risk_indicators = models.JSONField("风险指标", default=dict)
    reasons = models.JSONField("评估原因", default=list)
    rule_version = models.CharField("规则版本", max_length=32)
    created_at = models.DateTimeField("创建时间")
    metadata = models.JSONField("扩展数据", default=dict, blank=True)

    class Meta:
        db_table = "core_capacity_assessment"
        verbose_name = "容量评估"
        verbose_name_plural = "容量评估"
        ordering = ["-simulation_day", "-created_at"]
        indexes = [models.Index(fields=["simulation_day"])]

    def __str__(self) -> str:
        return self.assessment_id
