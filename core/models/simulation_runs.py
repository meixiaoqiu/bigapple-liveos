"""Simulation run models."""

from django.db import models

from .planning import PlanNode, PlanRevision


class SimulationRun(models.Model):
    """一次基于计划版本的可观察自动模拟。

    SimulationRun 不直接修改 PlanRevision 或 PlanNode。它只记录“如果按当前
    计划执行，模拟会怎样推进”，并把失败经验沉淀为 PlanRevisionProposal。
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        RUNNING = "running", "运行中"
        FAILED = "failed", "已失败"
        COMPLETED = "completed", "已完成"
        PAUSED = "paused", "已暂停"
        ABORTED = "aborted", "已中止"

    run_id = models.CharField("模拟运行ID", max_length=96, primary_key=True)
    plan_revision = models.ForeignKey(
        PlanRevision,
        on_delete=models.PROTECT,
        related_name="simulation_runs",
        verbose_name="计划版本",
        help_text="本次模拟采用的计划基线。模拟结果只能生成建议，不会直接改写该版本。",
    )
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.DRAFT)
    current_day = models.PositiveIntegerField("当前模拟日", default=1)
    max_turns = models.PositiveIntegerField("最大推进步数", default=30)
    started_at = models.DateTimeField("开始时间")
    ended_at = models.DateTimeField("结束时间", null=True, blank=True)
    failure_summary = models.TextField("失败摘要", blank=True)
    metadata = models.JSONField("扩展数据", default=dict, blank=True)

    class Meta:
        db_table = "core_simulation_run"
        verbose_name = "模拟运行"
        verbose_name_plural = "模拟运行"
        ordering = ["-started_at", "run_id"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["plan_revision", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.run_id}:{self.status}"


class PlanNodeRunState(models.Model):
    """某个计划节点在一次模拟运行中的执行状态。

    计划节点本身是主线计划的权威定义；这里记录的是该定义在某次模拟中的
    实际推进、成本、人天和阻塞情况。
    """

    class Status(models.TextChoices):
        PENDING = "pending", "待推进"
        RUNNING = "running", "推进中"
        BLOCKED = "blocked", "受阻"
        FAILED = "failed", "失败"
        COMPLETED = "completed", "已完成"
        SKIPPED = "skipped", "跳过"

    state_id = models.CharField("节点运行状态ID", max_length=128, primary_key=True)
    run = models.ForeignKey(SimulationRun, on_delete=models.CASCADE, related_name="node_states", verbose_name="模拟运行")
    plan_node = models.ForeignKey(
        PlanNode,
        on_delete=models.PROTECT,
        related_name="simulation_states",
        verbose_name="计划节点",
    )
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.PENDING)
    started_day = models.PositiveIntegerField("开始模拟日", null=True, blank=True)
    completed_day = models.PositiveIntegerField("完成模拟日", null=True, blank=True)
    progress_percent = models.DecimalField("进度百分比", max_digits=5, decimal_places=2, default=0)
    actual_cost = models.DecimalField("模拟实际成本", max_digits=14, decimal_places=2, default=0)
    actual_person_days = models.DecimalField("模拟实际人天", max_digits=10, decimal_places=2, default=0)
    blocker_reason = models.TextField("阻塞原因", blank=True)
    metadata = models.JSONField("扩展数据", default=dict, blank=True)

    class Meta:
        db_table = "core_plan_node_run_state"
        verbose_name = "计划节点模拟状态"
        verbose_name_plural = "计划节点模拟状态"
        indexes = [
            models.Index(fields=["run", "status"]),
            models.Index(fields=["plan_node"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["run", "plan_node"], name="unique_run_plan_node_state"),
        ]

    def __str__(self) -> str:
        return f"{self.run_id}:{self.plan_node_id}:{self.status}"


class SimulationTurn(models.Model):
    """一次模拟推进日志，供观察台按文字 MUD 的方式回放。"""

    turn_id = models.CharField("模拟步ID", max_length=96, primary_key=True)
    run = models.ForeignKey(SimulationRun, on_delete=models.CASCADE, related_name="turns", verbose_name="模拟运行")
    turn_number = models.PositiveIntegerField("推进步序号")
    simulation_day = models.PositiveIntegerField("模拟日期")
    summary = models.TextField("摘要")
    occurred_at = models.DateTimeField("发生时间")
    metadata = models.JSONField("扩展数据", default=dict, blank=True)

    class Meta:
        db_table = "core_simulation_turn"
        verbose_name = "模拟推进日志"
        verbose_name_plural = "模拟推进日志"
        ordering = ["run", "turn_number"]
        indexes = [models.Index(fields=["run", "turn_number"])]
        constraints = [
            models.UniqueConstraint(fields=["run", "turn_number"], name="unique_run_turn_number"),
        ]

    def __str__(self) -> str:
        return f"{self.run_id}:{self.turn_number}"


class SimulationFailure(models.Model):
    """模拟失败记录。

    失败记录描述的是“当前计划在某个模拟条件下为什么走不通”，后续可以由
    PlanRevisionProposal 转化为人工审核的计划修订建议。
    """

    class FailureType(models.TextChoices):
        BUDGET_UNREALISTIC = "budget_unrealistic", "预算不合理"
        LABOR_SHORTAGE = "labor_shortage", "人力不足"
        SKILL_SHORTAGE = "skill_shortage", "技能不足"
        RESOURCE_SHORTAGE = "resource_shortage", "资源不足"
        DEPENDENCY_UNMET = "dependency_unmet", "前置条件未满足"
        PERSONNEL_ISSUE = "personnel_issue", "人员状态问题"
        EXECUTION_ISSUE = "execution_issue", "执行过程问题"
        RESPONSIBILITY_CLOSURE_MISSING = "responsibility_closure_missing", "责任闭环缺失"

    class Severity(models.TextChoices):
        WARNING = "warning", "警告"
        CRITICAL = "critical", "严重"

    failure_id = models.CharField("模拟失败ID", max_length=96, primary_key=True)
    run = models.ForeignKey(SimulationRun, on_delete=models.CASCADE, related_name="failures", verbose_name="模拟运行")
    plan_node = models.ForeignKey(
        PlanNode,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="simulation_failures",
        verbose_name="关联计划节点",
    )
    failure_type = models.CharField("失败类型", max_length=32, choices=FailureType.choices)
    severity = models.CharField("严重程度", max_length=16, choices=Severity.choices, default=Severity.CRITICAL)
    title = models.CharField("标题", max_length=255)
    description = models.TextField("说明")
    simulation_day = models.PositiveIntegerField("模拟日期")
    detected_at = models.DateTimeField("发现时间")
    metadata = models.JSONField("扩展数据", default=dict, blank=True)

    class Meta:
        db_table = "core_simulation_failure"
        verbose_name = "模拟失败"
        verbose_name_plural = "模拟失败"
        ordering = ["-detected_at", "failure_id"]
        indexes = [
            models.Index(fields=["run", "plan_node"]),
            models.Index(fields=["failure_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.failure_id}:{self.failure_type}"
