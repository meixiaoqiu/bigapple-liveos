"""Unified event ledger and observer event models."""

from django.db import models

from .identity import Member, RoleAssignment
from .operations import Task


class SystemEvent(models.Model):
    """Append-only system event ledger with a simple tamper-evident hash chain."""

    class EventType(models.TextChoices):
        MEMBER_CREATED = "member_created", "成员已创建"
        MEMBER_APPLICATION_SUBMITTED = "member_application_submitted", "成员报名已提交"
        MEMBER_APPLICATION_REVIEWED = "member_application_reviewed", "成员报名已审核"
        PARTNER_APPLICATION_SUBMITTED = "partner_application_submitted", "合作方报名已提交"
        PARTNER_APPLICATION_REVIEWED = "partner_application_reviewed", "合作方报名已审核"
        ROLE_CREATED = "role_created", "角色已创建"
        ROLE_ASSIGNED = "role_assigned", "任命"
        ROLE_REVOKED = "role_revoked", "卸任"
        PROPOSAL_CREATED = "proposal_created", "提案已创建"
        PROPOSAL_VOTE_CAST = "proposal_vote_cast", "提案已投票"
        PROPOSAL_VOTE_CHANGED = "proposal_vote_changed", "提案已改票"
        PROPOSAL_PASSED = "proposal_passed", "提案已通过"
        PROPOSAL_FAILED = "proposal_failed", "提案未通过"
        PROPOSAL_CANCELLED = "proposal_cancelled", "提案已取消"
        PROPOSAL_EXECUTED = "proposal_executed", "提案已执行"
        CREDENTIAL_GRANTED = "credential_granted", "凭证已发放"
        EXPENSE_CLAIM_SUBMITTED = "expense_claim_submitted", "报销申请已提交"
        EXPENSE_CLAIM_REVIEWED = "expense_claim_reviewed", "报销申请已审核"
        EXPENSE_CLAIM_PAID = "expense_claim_paid", "报销已付款"
        TASK_CREATED = "task_created", "任务已创建"
        TASK_PUBLISHED = "task_published", "任务已发布"
        TASK_ASSIGNED = "task_assigned", "任务已指派"
        TASK_CLAIMED = "task_claimed", "任务已领取"
        TASK_SUBMITTED = "task_submitted", "任务已提交"
        TASK_REVIEWED = "task_reviewed", "任务已验收"
        TASK_CLOSED = "task_closed", "任务已关闭"
        DISPUTE_CREATED = "dispute_created", "申诉已提交"
        DISPUTE_REVIEW_STARTED = "dispute_review_started", "申诉已受理"
        DISPUTE_RESOLVED = "dispute_resolved", "申诉已处理"
        RESOURCE_ADJUSTED = "resource_adjusted", "资源已调整"
        SUPPLIER_OFFER_SUBMITTED = "supplier_offer_submitted", "供给报价已提交"
        SUPPLIER_OFFER_ACCEPTED = "supplier_offer_accepted", "供给报价已采纳"
        SUPPLIER_OFFER_REJECTED = "supplier_offer_rejected", "供给报价已拒绝"
        SUPPLIER_OFFER_RECEIPT_ACCEPTED = "supplier_offer_receipt_accepted", "供给报价验收通过"
        SUPPLIER_OFFER_RECEIPT_REJECTED = "supplier_offer_receipt_rejected", "供给报价验收失败"
        SUPPLIER_OFFER_COMPLETED = "supplier_offer_completed", "供给报价已完成"
        APPROVAL_PROPOSAL_SUBMITTED = "approval_proposal_submitted", "审批提案已提交"
        APPROVAL_PROPOSAL_APPROVED = "approval_proposal_approved", "审批提案已通过"
        APPROVAL_PROPOSAL_REJECTED = "approval_proposal_rejected", "审批提案已拒绝"
        APPROVAL_PROPOSAL_EXECUTED = "approval_proposal_executed", "审批提案已执行"
        APPROVAL_PROPOSAL_CANCELLED = "approval_proposal_cancelled", "审批提案已取消"
        PROCUREMENT_CHALLENGE_SUBMITTED = "procurement_challenge_submitted", "采购质疑已提交"
        PROCUREMENT_CHALLENGE_REVIEWED = "procurement_challenge_reviewed", "采购质疑已处理"
        RISK_ALERT_TRIGGERED = "risk_alert_triggered", "风险告警已触发"
        RISK_ALERT_ACKNOWLEDGED = "risk_alert_acknowledged", "风险告警已确认"
        RISK_ALERT_RESOLVED = "risk_alert_resolved", "风险告警已解除"
        RISK_ALERT_DISMISSED = "risk_alert_dismissed", "风险告警已忽略"
        RISK_RULE_UPDATED = "risk_rule_updated", "风险规则已更新"
        CREDIT_EARNED = "credit_earned", "积分获得"
        CREDIT_DEDUCTED = "credit_deducted", "积分扣减"
        CREDIT_ADJUSTED = "credit_adjusted", "积分调整"
        CREDIT_REVERSED = "credit_reversed", "积分冲正"
        SYSTEM_INITIALIZED = "system_initialized", "系统初始化"

    seq = models.PositiveBigIntegerField("序号", unique=True)
    event_type = models.CharField("事件类型", max_length=64, choices=EventType.choices)
    aggregate_type = models.CharField("聚合类型", max_length=64)
    aggregate_id = models.CharField("聚合ID", max_length=128)
    actor_member = models.ForeignKey(
        Member,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="system_events",
        verbose_name="行为人",
    )
    actor_role_assignment = models.ForeignKey(
        RoleAssignment,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="system_events",
        verbose_name="行为角色任命",
    )
    payload_json = models.JSONField("事件快照", default=dict, blank=True)
    payload_hash = models.CharField("快照哈希", max_length=64)
    prev_hash = models.CharField("上一事件哈希", max_length=64, blank=True)
    event_hash = models.CharField("事件哈希", max_length=64, unique=True)
    occurred_at = models.DateTimeField("发生时间")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        db_table = "core_system_event"
        verbose_name = "统一事件账本"
        verbose_name_plural = "统一事件账本"
        ordering = ["seq"]
        indexes = [
            models.Index(fields=["event_type"]),
            models.Index(fields=["aggregate_type", "aggregate_id"]),
            models.Index(fields=["occurred_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.seq}:{self.event_type}"

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValueError("SystemEvent is append-only and cannot be modified once created.")
        if not getattr(self, "_allow_append", False):
            raise ValueError("Use core.event_ledger.append_event() to append SystemEvent records.")
        return super().save(*args, **kwargs)


class Event(models.Model):
    """Replayable event stream record."""

    class EventType(models.TextChoices):
        SYSTEM = "system", "系统"
        SIMULATION_DAY = "simulation_day", "模拟日期"
        TASK = "task", "任务"
        LEDGER = "ledger", "账本"
        RESOURCE = "resource", "资源"
        DISPUTE = "dispute", "申诉"
        CAPACITY = "capacity", "容量"
        GOVERNANCE = "governance", "治理"
        RANDOM_INCIDENT = "random_incident", "随机事件"

    class Severity(models.TextChoices):
        INFO = "info", "信息"
        WARNING = "warning", "警告"
        CRITICAL = "critical", "严重"

    class GeneratedBy(models.TextChoices):
        LIVE_OS = "live_os", "Live OS"
        SIMULATION_ENGINE = "simulation_engine", "Simulation Engine"
        HUMAN_OPERATOR = "human_operator", "人工操作"

    class Visibility(models.TextChoices):
        PUBLIC = "public", "公开"
        INTERNAL = "internal", "内部"
        PRIVATE = "private", "私密"

    event_id = models.CharField("事件ID", max_length=64, primary_key=True)
    event_type = models.CharField("事件类型", max_length=32, choices=EventType.choices)
    simulation_day = models.PositiveIntegerField("模拟日期")
    simulation_run = models.ForeignKey(
        "SimulationRun",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="events",
        verbose_name="模拟运行",
        help_text="仿真生成的公开观察事件必须归属于明确的 simulation run；真实世界事件为空。",
    )
    severity = models.CharField("严重程度", max_length=16, choices=Severity.choices)
    title = models.CharField("标题", max_length=255)
    summary = models.TextField("摘要")
    involved_member_ids = models.JSONField("涉及成员编号", default=list, blank=True)
    related_task = models.ForeignKey(
        Task,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="events",
        verbose_name="关联任务",
    )
    related_dispute_id = models.CharField("关联申诉ID", max_length=64, blank=True)
    occurred_at = models.DateTimeField("发生时间")
    generated_by = models.CharField("生成来源", max_length=32, choices=GeneratedBy.choices)
    visibility = models.CharField("可见性", max_length=16, choices=Visibility.choices)
    payload = models.JSONField("事件数据", default=dict, blank=True)

    class Meta:
        db_table = "core_event"
        verbose_name = "事件"
        verbose_name_plural = "事件"
        ordering = ["occurred_at", "event_id"]
        indexes = [
            models.Index(fields=["simulation_day"]),
            models.Index(fields=["simulation_run", "visibility"]),
            models.Index(fields=["event_type"]),
            models.Index(fields=["visibility"]),
        ]

    def __str__(self) -> str:
        return self.event_id

    def save(self, *args, **kwargs):
        if self.generated_by == self.GeneratedBy.SIMULATION_ENGINE and not self.simulation_run_id:
            raise ValueError("Simulation-generated Event records must be linked to a SimulationRun.")
        return super().save(*args, **kwargs)
