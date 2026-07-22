"""Unified cross-subsystem approval proposal models."""

from django.db import models
from django.utils import timezone

from .identity import Member


class ApprovalProposal(models.Model):
    class ProposalType(models.TextChoices):
        PROCUREMENT_ACCEPTANCE = "procurement_acceptance", "采购采纳"
        PROCUREMENT_PAYMENT = "procurement_payment", "采购付款"
        MEMBER_APPLICATION = "member_application", "成员申请"
        INVENTORY_ADJUSTMENT = "inventory_adjustment", "库存调整"
        DISPUTE_RESOLUTION = "dispute_resolution", "争议处理"

    class Status(models.TextChoices):
        SUBMITTED = "submitted", "已提交"
        APPROVED = "approved", "已通过"
        REJECTED = "rejected", "已拒绝"
        CANCELLED = "cancelled", "已取消"
        EXECUTED = "executed", "已执行"

    class Tier(models.TextChoices):
        SINGLE = "single", "单人"
        STANDARD = "standard", "标准"
        MAJOR = "major", "大额"

    proposal_id = models.CharField("提案ID", max_length=64, primary_key=True)
    proposal_type = models.CharField("提案类型", max_length=32, choices=ProposalType.choices)
    title = models.CharField("标题", max_length=256)
    summary = models.TextField("摘要", blank=True)
    public_reason = models.TextField("公开理由", blank=True)
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.SUBMITTED)
    approval_tier = models.CharField("审批层级", max_length=16, choices=Tier.choices, default=Tier.SINGLE)
    target_type = models.CharField("目标类型", max_length=64, blank=True)
    target_id = models.CharField("目标ID", max_length=128, blank=True)
    dedupe_key = models.CharField(
        "去重键", max_length=191, default="", blank=False,
        help_text="业务幂等键。同 proposal_type 下唯一。",
    )
    submitted_by = models.ForeignKey(
        Member, on_delete=models.PROTECT, related_name="submitted_approval_proposals", verbose_name="提交人",
    )
    submitted_at = models.DateTimeField("提交时间", default=timezone.now)
    resolved_at = models.DateTimeField("决议时间", null=True, blank=True)
    executed_at = models.DateTimeField("执行时间", null=True, blank=True)
    metadata = models.JSONField("扩展数据", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", default=timezone.now)
    updated_at = models.DateTimeField("更新时间", null=True, blank=True)

    class Meta:
        db_table = "core_approval_proposal"
        verbose_name = "审批提案"
        verbose_name_plural = "审批提案"
        ordering = ["-submitted_at"]
        indexes = [models.Index(fields=["status"]), models.Index(fields=["target_type", "target_id"])]
        constraints = [
            models.UniqueConstraint(
                fields=["proposal_type", "dedupe_key"],
                name="unique_approval_proposal_type_dedupe_key",
            ),
        ]

    def __str__(self):
        return f"{self.proposal_id}:{self.title}"


class ApprovalDecision(models.Model):
    class Decision(models.TextChoices):
        APPROVED = "approved", "同意"
        REJECTED = "rejected", "拒绝"

    approval_id = models.CharField("审批ID", max_length=64, primary_key=True)
    proposal = models.ForeignKey(
        ApprovalProposal, on_delete=models.CASCADE, related_name="approvals", verbose_name="提案",
    )
    approver = models.ForeignKey(
        Member, on_delete=models.PROTECT, related_name="approval_decisions", verbose_name="审批人",
    )
    role = models.CharField("审批角色", max_length=32)
    decision = models.CharField("决策", max_length=16, choices=Decision.choices)
    reason = models.TextField("理由", blank=True)
    created_at = models.DateTimeField("审批时间", default=timezone.now)

    class Meta:
        db_table = "core_approval_decision"
        verbose_name = "审批记录"
        verbose_name_plural = "审批记录"
        constraints = [
            models.UniqueConstraint(
                fields=["proposal", "approver", "role"], name="unique_approval_proposer_role",
            ),
        ]

    def __str__(self):
        return f"{self.approval_id}:{self.proposal_id}:{self.role}"
