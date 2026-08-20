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
        DRAFT = "draft", "草拟"
        AWAITING_POLICY = "awaiting_policy", "等待政策配置"
        SUBMITTED = "submitted", "已提交"
        VOTING = "voting", "表决中"
        APPROVED = "approved", "已通过"
        REJECTED = "rejected", "已拒绝"
        EXPIRED = "expired", "已过期"
        CANCELLED = "cancelled", "已取消"
        EXECUTED = "executed", "已执行"
        EXECUTION_FAILED = "execution_failed", "执行失败"

    class StrategyType(models.TextChoices):
        APPROVAL_SLOTS = "approval_slots", "固定审批槽"
        ELECTORATE = "electorate", "版本化选民规则"

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
    strategy_type = models.CharField(
        "决策策略",
        max_length=24,
        choices=StrategyType.choices,
        default=StrategyType.APPROVAL_SLOTS,
        help_text="固定审批槽用于尚未迁移的既有审批；版本化选民规则用于统一表决。",
    )
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
    voting_started_at = models.DateTimeField("表决开始时间", null=True, blank=True)
    voting_deadline = models.DateTimeField("表决截止时间", null=True, blank=True)
    frozen_approve_threshold = models.PositiveIntegerField(
        "冻结通过阈值", null=True, blank=True, help_text="开始表决时从已发布规则版本冻结的赞成票门槛。",
    )
    frozen_reject_threshold = models.PositiveIntegerField(
        "冻结拒绝阈值", null=True, blank=True, help_text="开始表决时从已发布规则版本冻结的反对票门槛。",
    )
    frozen_minimum_participation = models.PositiveIntegerField(
        "冻结最低参与数", null=True, blank=True, help_text="开始表决时冻结的最低有效投票人数。",
    )
    frozen_unresolved_outcome = models.CharField(
        "冻结未决处理",
        max_length=16,
        blank=True,
        default="",
        help_text="截止时未达到通过或拒绝条件时采用 rejected 或 expired。",
    )
    resolved_at = models.DateTimeField("决议时间", null=True, blank=True)
    executed_at = models.DateTimeField("执行时间", null=True, blank=True)
    metadata = models.JSONField("扩展数据", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", default=timezone.now)
    updated_at = models.DateTimeField("更新时间", null=True, blank=True)
    electorate_rule_version = models.ForeignKey(
        "ElectorateRuleVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="proposals",
        verbose_name="选民规则版本",
        help_text="统一表决开始后不可替换的已发布规则版本。",
    )

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


class ElectorateRuleTemplate(models.Model):
    """可编辑的选民规则模板；权威提案只引用其不可变发布版本。"""

    rule_code = models.CharField("规则代码", max_length=64, primary_key=True)
    proposal_type = models.CharField(
        "适用提案类型",
        max_length=64,
        help_text="稳定提案类型代码；规则不能被其他类型临时复用。",
    )
    name = models.CharField("规则名称", max_length=128)
    description = models.TextField("规则说明", blank=True)
    is_active = models.BooleanField("可继续发布", default=True)
    created_by = models.ForeignKey(
        Member, on_delete=models.PROTECT, related_name="created_electorate_rule_templates", verbose_name="创建人",
    )
    created_at = models.DateTimeField("创建时间", default=timezone.now)
    updated_at = models.DateTimeField("更新时间", default=timezone.now)

    class Meta:
        db_table = "core_electorate_rule_template"
        verbose_name = "选民规则模板"
        verbose_name_plural = "选民规则模板"
        indexes = [models.Index(fields=["proposal_type", "is_active"])]


class ElectorateRuleVersion(models.Model):
    """已发布且不可变的选民规则版本。"""

    class UnresolvedOutcome(models.TextChoices):
        REJECTED = "rejected", "拒绝"
        EXPIRED = "expired", "过期"

    rule_version_id = models.CharField("规则版本ID", max_length=96, primary_key=True)
    template = models.ForeignKey(
        ElectorateRuleTemplate, on_delete=models.PROTECT, related_name="versions", verbose_name="规则模板",
    )
    version = models.PositiveIntegerField("版本号")
    selector_config = models.JSONField(
        "选择器配置",
        help_text="仅保存通过服务端 schema 验证的 ALL、ANY、角色、派生状态、专业资格和排除条件。",
    )
    approve_threshold = models.PositiveIntegerField("通过阈值")
    reject_threshold = models.PositiveIntegerField("拒绝阈值")
    minimum_participation = models.PositiveIntegerField("最低参与数", default=0)
    voting_duration_hours = models.PositiveIntegerField("表决期限小时数")
    unresolved_outcome = models.CharField(
        "未决处理", max_length=16, choices=UnresolvedOutcome.choices,
    )
    published_by = models.ForeignKey(
        Member, on_delete=models.PROTECT, related_name="published_electorate_rule_versions", verbose_name="发布人",
    )
    published_at = models.DateTimeField("发布时间", default=timezone.now)

    class Meta:
        db_table = "core_electorate_rule_version"
        verbose_name = "选民规则版本"
        verbose_name_plural = "选民规则版本"
        ordering = ["template_id", "version"]
        constraints = [
            models.UniqueConstraint(fields=["template", "version"], name="unique_electorate_rule_version"),
        ]


class ProposalElectorSnapshot(models.Model):
    """提案开始表决时冻结的候选选民事实。"""

    proposal = models.ForeignKey(
        ApprovalProposal, on_delete=models.CASCADE, related_name="elector_snapshots", verbose_name="提案",
    )
    member = models.ForeignKey(
        Member, on_delete=models.PROTECT, related_name="proposal_elector_snapshots", verbose_name="成员",
    )
    rule_version = models.ForeignKey(
        ElectorateRuleVersion, on_delete=models.PROTECT, related_name="elector_snapshots", verbose_name="规则版本",
    )
    qualification_evidence = models.JSONField(
        "资格证据", default=dict, blank=True, help_text="生成快照时满足规则的公开安全依据。",
    )
    snapshotted_at = models.DateTimeField("快照时间", default=timezone.now)

    class Meta:
        db_table = "core_proposal_elector_snapshot"
        verbose_name = "提案选民快照"
        verbose_name_plural = "提案选民快照"
        constraints = [
            models.UniqueConstraint(fields=["proposal", "member"], name="unique_proposal_elector_snapshot"),
        ]
        indexes = [models.Index(fields=["proposal", "member"])]


class ProposalBallot(models.Model):
    """只追加的实名票据修订。"""

    class Choice(models.TextChoices):
        APPROVE = "approve", "赞成"
        REJECT = "reject", "反对"
        ABSTAIN = "abstain", "弃权"

    ballot_id = models.CharField("票据ID", max_length=96, primary_key=True)
    proposal = models.ForeignKey(
        ApprovalProposal, on_delete=models.CASCADE, related_name="ballots", verbose_name="提案",
    )
    voter = models.ForeignKey(
        Member, on_delete=models.PROTECT, related_name="proposal_ballots", verbose_name="投票人",
    )
    revision = models.PositiveIntegerField("修订序号")
    choice = models.CharField("选择", max_length=16, choices=Choice.choices)
    reason = models.TextField("理由", blank=True)
    submitted_at = models.DateTimeField("投票时间", default=timezone.now)

    class Meta:
        db_table = "core_proposal_ballot"
        verbose_name = "提案票据"
        verbose_name_plural = "提案票据"
        ordering = ["proposal_id", "voter_id", "revision"]
        constraints = [
            models.UniqueConstraint(fields=["proposal", "voter", "revision"], name="unique_proposal_ballot_revision"),
        ]
        indexes = [models.Index(fields=["proposal", "voter", "-revision"])]


class ProposalResolution(models.Model):
    """按冻结参数计算得到的不可变提案结果证据。"""

    class Outcome(models.TextChoices):
        APPROVED = "approved", "通过"
        REJECTED = "rejected", "拒绝"
        EXPIRED = "expired", "过期"

    proposal = models.OneToOneField(
        ApprovalProposal, on_delete=models.CASCADE, related_name="resolution", verbose_name="提案",
    )
    outcome = models.CharField("结果", max_length=16, choices=Outcome.choices)
    reason_code = models.CharField("判定代码", max_length=64)
    evidence = models.JSONField(
        "判定证据", help_text="保存选民数、有效参与数、各选项票数和采用的冻结阈值。",
    )
    decided_by = models.ForeignKey(
        Member,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="proposal_resolutions",
        verbose_name="判定触发人",
        help_text="实名记录触发本次确定性结果判定的成员；迁移前历史记录可以为空。",
    )
    decided_at = models.DateTimeField("判定时间", default=timezone.now)

    class Meta:
        db_table = "core_proposal_resolution"
        verbose_name = "提案判定证据"
        verbose_name_plural = "提案判定证据"


class ProposalExecutionRecord(models.Model):
    """统一提案执行的幂等记录。"""

    class Status(models.TextChoices):
        RUNNING = "running", "执行中"
        SUCCEEDED = "succeeded", "成功"
        FAILED = "failed", "失败"

    execution_id = models.CharField("执行ID", max_length=96, primary_key=True)
    proposal = models.OneToOneField(
        ApprovalProposal, on_delete=models.CASCADE, related_name="execution_record", verbose_name="提案",
    )
    idempotency_key = models.CharField("幂等键", max_length=191, unique=True)
    executed_by = models.ForeignKey(
        Member, on_delete=models.PROTECT, related_name="proposal_executions", verbose_name="执行人",
    )
    status = models.CharField("状态", max_length=16, choices=Status.choices)
    public_error_code = models.CharField(
        "公开错误代码", max_length=64, blank=True, help_text="可安全展示的稳定错误代码，不保存异常堆栈。",
    )
    result_data = models.JSONField(
        "执行结果", default=dict, blank=True, help_text="适配器返回的公开安全幂等结果。",
    )
    started_at = models.DateTimeField("开始时间", default=timezone.now)
    completed_at = models.DateTimeField("完成时间", null=True, blank=True)

    class Meta:
        db_table = "core_proposal_execution_record"
        verbose_name = "提案执行记录"
        verbose_name_plural = "提案执行记录"
