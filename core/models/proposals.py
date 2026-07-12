"""Generic proposal, vote, and execution models."""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .identity import Member, Organization, Role, RoleAssignment


class Proposal(models.Model):
    """Generic governance proposal.

    Role appointments are represented as ``proposal_type=role_appointment`` and
    are executed through ``ProposalExecution`` after voting passes.
    """

    class ProposalType(models.TextChoices):
        ROLE_APPOINTMENT = "role_appointment", "角色任命"
        ROLE_REVOCATION = "role_revocation", "角色卸任"
        RULE = "rule", "规则"
        POLICY = "policy", "政策"
        BUDGET = "budget", "预算"
        PROJECT = "project", "项目"
        STATEMENT = "statement", "声明"

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        VOTING = "voting", "表决中"
        PASSED = "passed", "已通过"
        FAILED = "failed", "未通过"
        CANCELLED = "cancelled", "已取消"
        EXECUTED = "executed", "已执行"

    class VoterScopeType(models.TextChoices):
        ROLE = "role", "按角色"
        ORGANIZATION = "organization", "按组织"
        ALL_MEMBERS = "all_members", "全体成员"

    proposal_no = models.CharField("提案编号", max_length=32, unique=True, blank=True)
    title = models.CharField("标题", max_length=255)
    body = models.TextField("正文", blank=True)
    proposal_type = models.CharField("提案类型", max_length=32, choices=ProposalType.choices)
    status = models.CharField("状态", max_length=32, choices=Status.choices, default=Status.DRAFT)
    proposer_member = models.ForeignKey(
        Member,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="proposals",
        verbose_name="提案人",
    )
    proposer_role_assignment = models.ForeignKey(
        RoleAssignment,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="proposals",
        verbose_name="提案时角色身份",
    )
    organization = models.ForeignKey(
        Organization,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="proposals",
        verbose_name="组织",
    )
    voter_scope_type = models.CharField(
        "投票范围类型",
        max_length=32,
        choices=VoterScopeType.choices,
        default=VoterScopeType.ROLE,
    )
    voter_scope_role = models.ForeignKey(
        Role,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="voter_scope_proposals",
        verbose_name="投票范围角色",
    )
    voter_scope_organization = models.ForeignKey(
        Organization,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="voter_scope_proposals",
        verbose_name="投票范围组织",
    )
    eligible_voters_snapshot_json = models.JSONField("投票资格快照", default=list, blank=True)
    pass_ratio = models.PositiveSmallIntegerField("通过比例", default=50)
    quorum_count = models.PositiveIntegerField("最低参与人数", default=1)
    allow_vote_change = models.BooleanField("允许改票", default=True)
    start_at = models.DateTimeField("开始时间", default=timezone.now)
    deadline_at = models.DateTimeField("截止时间")
    passed_at = models.DateTimeField("通过时间", null=True, blank=True)
    failed_at = models.DateTimeField("失败时间", null=True, blank=True)
    cancelled_at = models.DateTimeField("取消时间", null=True, blank=True)
    executed_at = models.DateTimeField("执行时间", null=True, blank=True)
    payload_json = models.JSONField("提案内容", default=dict, blank=True)
    result_json = models.JSONField("表决结果", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "core_proposal"
        verbose_name = "提案"
        verbose_name_plural = "提案"
        indexes = [
            models.Index(fields=["proposal_type", "status"]),
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["deadline_at"]),
            models.Index(fields=["proposer_member"]),
        ]

    def __str__(self) -> str:
        return f"{self.proposal_no or self.pk}:{self.title}"

    def clean(self):
        super().clean()
        if self.pass_ratio < 1 or self.pass_ratio > 100:
            raise ValidationError({"pass_ratio": "通过比例必须在 1 到 100 之间。"})
        if self.quorum_count < 0:
            raise ValidationError({"quorum_count": "最低参与人数不能为负数。"})
        if self.start_at and self.deadline_at and self.deadline_at <= self.start_at:
            raise ValidationError({"deadline_at": "截止时间必须晚于开始时间。"})

    def save(self, *args, **kwargs):
        if not self.proposal_no:
            latest_pk = type(self).objects.order_by("-id").values_list("id", flat=True).first() or 0
            self.proposal_no = f"{latest_pk + 1:04d}"
        self.clean()
        return super().save(*args, **kwargs)


class ProposalVote(models.Model):
    """One member's current vote for a proposal."""

    class Choice(models.TextChoices):
        YES = "yes", "赞成"
        NO = "no", "反对"
        ABSTAIN = "abstain", "弃权"

    proposal = models.ForeignKey(
        Proposal,
        on_delete=models.CASCADE,
        related_name="votes",
        verbose_name="提案",
    )
    voter_member = models.ForeignKey(
        Member,
        on_delete=models.PROTECT,
        related_name="proposal_votes",
        verbose_name="投票成员",
    )
    voter_role_assignment = models.ForeignKey(
        RoleAssignment,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="proposal_votes",
        verbose_name="投票角色任命",
    )
    choice = models.CharField("投票选择", max_length=16, choices=Choice.choices)
    reason = models.TextField("理由", blank=True)
    voted_at = models.DateTimeField("投票时间", default=timezone.now)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "core_proposal_vote"
        verbose_name = "提案投票"
        verbose_name_plural = "提案投票"
        indexes = [
            models.Index(fields=["proposal", "choice"]),
            models.Index(fields=["voter_member"]),
            models.Index(fields=["voted_at"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["proposal", "voter_member"], name="unique_vote_per_proposal"),
        ]

    def __str__(self) -> str:
        return f"{self.proposal_id}:{self.voter_member_id}:{self.choice}"


class ProposalExecution(models.Model):
    """Execution record for a passed proposal."""

    class ActionType(models.TextChoices):
        CREATE_ROLE_ASSIGNMENT = "create_role_assignment", "创建角色任命"
        REVOKE_ROLE_ASSIGNMENT = "revoke_role_assignment", "撤销角色任命"
        CREATE_RULE = "create_rule", "创建规则"
        CREATE_POLICY = "create_policy", "创建政策"
        RECORD_STATEMENT = "record_statement", "记录声明"
        MANUAL = "manual", "人工处理"

    class Status(models.TextChoices):
        PENDING = "pending", "待执行"
        SUCCEEDED = "succeeded", "执行成功"
        FAILED = "failed", "执行失败"
        SKIPPED = "skipped", "已跳过"

    proposal = models.ForeignKey(
        Proposal,
        on_delete=models.PROTECT,
        related_name="executions",
        verbose_name="提案",
    )
    executor_member = models.ForeignKey(
        Member,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="proposal_executions",
        verbose_name="执行人",
    )
    executor_role_assignment = models.ForeignKey(
        RoleAssignment,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="proposal_executions",
        verbose_name="执行人角色任命",
    )
    action_type = models.CharField("执行动作", max_length=64, choices=ActionType.choices)
    status = models.CharField("状态", max_length=32, choices=Status.choices, default=Status.PENDING)
    payload_json = models.JSONField("执行内容", default=dict, blank=True)
    result_json = models.JSONField("执行结果", default=dict, blank=True)
    error_message = models.TextField("错误信息", blank=True)
    executed_at = models.DateTimeField("执行时间", null=True, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "core_proposal_execution"
        verbose_name = "提案执行"
        verbose_name_plural = "提案执行"
        indexes = [
            models.Index(fields=["proposal", "action_type"]),
            models.Index(fields=["status"]),
            models.Index(fields=["executed_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.proposal_id}:{self.action_type}:{self.status}"
