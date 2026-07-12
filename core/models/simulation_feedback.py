"""Simulation plan-feedback models."""

from django.db import models

from .planning import PlanNode, PlanRevision
from .simulation_runs import SimulationFailure, SimulationRun


class PlanRevisionProposal(models.Model):
    """由模拟失败生成、等待人工审核的计划修订建议。"""

    class ProposalType(models.TextChoices):
        ADJUST_BUDGET = "adjust_budget", "调整预算"
        ADJUST_DURATION = "adjust_duration", "调整工期"
        ADD_DEPENDENCY = "add_dependency", "增加依赖"
        ADD_NODE = "add_node", "增加节点"
        REDUCE_ADMISSION = "reduce_admission", "降低接纳规模"
        ADD_REQUIREMENT = "add_requirement", "增加需求"
        CHANGE_CAPACITY = "change_capacity", "调整容量"

    class Status(models.TextChoices):
        DRAFT = "draft", "待审核"
        REVIEWED = "reviewed", "已审阅"
        ACCEPTED = "accepted", "已采纳"
        REJECTED = "rejected", "已拒绝"

    proposal_id = models.CharField("计划修订建议ID", max_length=96, primary_key=True)
    run = models.ForeignKey(SimulationRun, on_delete=models.CASCADE, related_name="proposals", verbose_name="模拟运行")
    source_failure = models.ForeignKey(
        SimulationFailure,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="proposals",
        verbose_name="来源失败",
    )
    plan_revision = models.ForeignKey(
        PlanRevision,
        on_delete=models.PROTECT,
        related_name="simulation_proposals",
        verbose_name="计划版本",
    )
    plan_node = models.ForeignKey(
        PlanNode,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="simulation_proposals",
        verbose_name="关联计划节点",
    )
    proposal_type = models.CharField("建议类型", max_length=32, choices=ProposalType.choices)
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.DRAFT)
    title = models.CharField("标题", max_length=255)
    rationale = models.TextField("依据")
    suggested_changes = models.JSONField("建议变更", default=dict)
    created_at = models.DateTimeField("创建时间")
    metadata = models.JSONField("扩展数据", default=dict, blank=True)

    class Meta:
        db_table = "core_plan_revision_proposal"
        verbose_name = "计划修订建议"
        verbose_name_plural = "计划修订建议"
        ordering = ["-created_at", "proposal_id"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["plan_revision", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.proposal_id}:{self.status}"


class PlanChangeSet(models.Model):
    """由计划修订建议生成的结构化计划数据补丁。

    ChangeSet 是可审核的业务变更集合，不是已经生效的计划。只有被采纳后，
    后续服务才会把它应用到新的 PlanRevision。
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "待审核"
        REVIEWED = "reviewed", "已审阅"
        ACCEPTED = "accepted", "已采纳"
        REJECTED = "rejected", "已拒绝"
        APPLIED = "applied", "已生成新版本"

    change_set_id = models.CharField("计划变更集ID", max_length=96, primary_key=True)
    run = models.ForeignKey(SimulationRun, on_delete=models.CASCADE, related_name="plan_change_sets", verbose_name="模拟运行")
    proposal = models.ForeignKey(
        PlanRevisionProposal,
        on_delete=models.CASCADE,
        related_name="change_sets",
        verbose_name="来源修订建议",
    )
    plan_revision = models.ForeignKey(
        PlanRevision,
        on_delete=models.PROTECT,
        related_name="change_sets",
        verbose_name="源计划版本",
    )
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.DRAFT)
    title = models.CharField("标题", max_length=255)
    summary = models.TextField("摘要")
    created_at = models.DateTimeField("创建时间")
    reviewed_at = models.DateTimeField("审阅时间", null=True, blank=True)
    applied_at = models.DateTimeField("应用时间", null=True, blank=True)
    applied_revision = models.ForeignKey(
        PlanRevision,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="source_change_sets",
        verbose_name="生成的计划版本",
    )
    metadata = models.JSONField("扩展数据", default=dict, blank=True)

    class Meta:
        db_table = "core_plan_change_set"
        verbose_name = "计划变更集"
        verbose_name_plural = "计划变更集"
        ordering = ["-created_at", "change_set_id"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["plan_revision", "status"]),
            models.Index(fields=["run"]),
        ]

    def __str__(self) -> str:
        return f"{self.change_set_id}:{self.status}"


class PlanChangeOperation(models.Model):
    """计划变更集中的单条结构化操作。

    操作描述的是未来如何修改计划数据库对象，例如新增节点、增加依赖、
    增加需求或调整字段。它本身不直接执行数据库写入。
    """

    class OperationType(models.TextChoices):
        ADD_NODE = "add_node", "新增计划节点"
        UPDATE_NODE_FIELD = "update_node_field", "调整节点字段"
        ADD_DEPENDENCY = "add_dependency", "新增计划依赖"
        ADD_REQUIREMENT = "add_requirement", "新增计划需求"
        ADD_CAPACITY_IMPACT = "add_capacity_impact", "新增容量影响"
        REDUCE_ADMISSION = "reduce_admission", "降低接纳规模"
        ADD_PREPARATION = "add_preparation", "新增前置准备"
        NOTE = "note", "说明"

    operation_id = models.CharField("计划变更操作ID", max_length=128, primary_key=True)
    change_set = models.ForeignKey(
        PlanChangeSet,
        on_delete=models.CASCADE,
        related_name="operations",
        verbose_name="计划变更集",
    )
    sequence = models.PositiveIntegerField("排序", default=0)
    operation_type = models.CharField("操作类型", max_length=32, choices=OperationType.choices)
    target_model = models.CharField("目标模型", max_length=64)
    target_id = models.CharField("目标记录ID", max_length=128, blank=True)
    target_field = models.CharField("目标字段", max_length=128, blank=True)
    old_value = models.JSONField("旧值", default=dict, blank=True)
    new_value = models.JSONField("新值", default=dict, blank=True)
    rationale = models.TextField("依据")
    is_required = models.BooleanField("是否必要操作", default=True)
    metadata = models.JSONField("扩展数据", default=dict, blank=True)

    class Meta:
        db_table = "core_plan_change_operation"
        verbose_name = "计划变更操作"
        verbose_name_plural = "计划变更操作"
        ordering = ["change_set", "sequence", "operation_id"]
        indexes = [
            models.Index(fields=["change_set", "sequence"]),
            models.Index(fields=["operation_type"]),
            models.Index(fields=["target_model", "target_id"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["change_set", "sequence"], name="unique_change_set_operation_sequence"),
        ]

    def __str__(self) -> str:
        return f"{self.change_set_id}:{self.sequence}:{self.operation_type}"
