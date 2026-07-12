"""Simulation archive models."""

from django.db import models


class SimulationSnapshot(models.Model):
    """Permanent archive index for one simulation run.

    Raw simulation data is stored outside the database as an immutable archive
    package. This model is the stable searchable index in the control database.
    """

    class Status(models.TextChoices):
        ARCHIVED = "archived", "已归档"

    class PublicationStatus(models.TextChoices):
        PUBLIC = "public", "公开展示"
        INTERNAL = "internal", "内部复盘"
        HIDDEN = "hidden", "隐藏"

    snapshot_id = models.CharField("仿真快照ID", max_length=96, primary_key=True)
    title = models.CharField("标题", max_length=255)
    simulation_round = models.PositiveIntegerField("仿真轮次", null=True, blank=True)
    scenario = models.CharField("仿真场景", max_length=64, blank=True)
    purpose = models.TextField("仿真目的", blank=True)
    hypothesis = models.TextField("仿真假设", blank=True)
    parameter_summary = models.JSONField("参数摘要", default=dict, blank=True)
    public_title = models.CharField("公开标题", max_length=255, blank=True)
    public_summary = models.TextField("公开摘要", blank=True)
    review_conclusion = models.TextField("复盘结论", blank=True)
    next_run_basis = models.TextField("下一轮依据", blank=True)
    publication_status = models.CharField(
        "发布状态",
        max_length=16,
        choices=PublicationStatus.choices,
        default=PublicationStatus.PUBLIC,
    )
    source_world_id = models.CharField("来源世界ID", max_length=64)
    source_world_type = models.CharField("来源世界类型", max_length=24)
    source_database_alias = models.CharField("来源数据库别名", max_length=64)
    source_database_name = models.CharField("来源数据库名称", max_length=128, blank=True)
    source_run_id = models.CharField("来源仿真运行ID", max_length=96)
    plan_revision_id = models.CharField("计划版本ID", max_length=64, blank=True)
    run_status = models.CharField("运行状态", max_length=16)
    failure_type = models.CharField("失败类型", max_length=64, blank=True)
    failure_title = models.CharField("失败标题", max_length=255, blank=True)
    snapshot_schema_version = models.PositiveIntegerField("快照结构版本", default=1)
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.ARCHIVED)
    raw_archive_path = models.CharField("原始归档路径", max_length=512)
    raw_archive_hash = models.CharField("原始归档哈希", max_length=64)
    report_path = models.CharField("报告路径", max_length=512, blank=True)
    raw_table_counts = models.JSONField("原始表计数", default=dict, blank=True)
    normalized_summary = models.JSONField("标准化摘要", default=dict, blank=True)
    code_version = models.CharField("代码版本", max_length=64, blank=True)
    archived_at = models.DateTimeField("归档时间")
    metadata = models.JSONField("扩展数据", default=dict, blank=True)

    class Meta:
        db_table = "core_simulation_snapshot"
        verbose_name = "仿真快照"
        verbose_name_plural = "仿真快照"
        ordering = ["-archived_at", "snapshot_id"]
        indexes = [
            models.Index(fields=["source_world_id", "archived_at"]),
            models.Index(fields=["source_world_id", "simulation_round"]),
            models.Index(fields=["scenario"]),
            models.Index(fields=["publication_status"]),
            models.Index(fields=["run_status"]),
            models.Index(fields=["failure_type"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["source_world_id", "source_run_id"], name="unique_snapshot_source_run"),
        ]

    def __str__(self) -> str:
        return f"{self.snapshot_id}:{self.source_world_id}:{self.source_run_id}"

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValueError("SimulationSnapshot is immutable once archived.")
        return super().save(*args, **kwargs)


class SimulationRunDisposition(models.Model):
    """Final human disposition for one simulation run before another run starts."""

    class Disposition(models.TextChoices):
        ARCHIVED = "archived", "已归档"
        DISCARDED = "discarded", "放弃归档"

    disposition_id = models.CharField("处置ID", max_length=128, primary_key=True)
    source_world_id = models.CharField("来源世界ID", max_length=64)
    source_world_type = models.CharField("来源世界类型", max_length=24)
    source_database_alias = models.CharField("来源数据库别名", max_length=64)
    source_database_name = models.CharField("来源数据库名称", max_length=128, blank=True)
    source_run_id = models.CharField("来源仿真运行ID", max_length=96)
    run_status = models.CharField("运行状态", max_length=16)
    run_started_at = models.DateTimeField("运行开始时间", null=True, blank=True)
    run_ended_at = models.DateTimeField("运行结束时间", null=True, blank=True)
    simulation_round = models.PositiveIntegerField("仿真轮次")
    scenario = models.CharField("仿真场景", max_length=64, blank=True)
    disposition = models.CharField("处置结果", max_length=16, choices=Disposition.choices)
    reason = models.TextField("处置原因")
    decided_by = models.CharField("处置人", max_length=128, blank=True)
    decided_at = models.DateTimeField("处置时间")
    snapshot = models.ForeignKey(
        SimulationSnapshot,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="dispositions",
        verbose_name="关联快照",
    )
    metadata = models.JSONField("扩展数据", default=dict, blank=True)

    class Meta:
        db_table = "core_simulation_run_disposition"
        verbose_name = "仿真运行处置记录"
        verbose_name_plural = "仿真运行处置记录"
        ordering = ["-decided_at", "source_world_id", "simulation_round"]
        indexes = [
            models.Index(fields=["source_world_id", "simulation_round"]),
            models.Index(fields=["source_world_id", "source_run_id"]),
            models.Index(fields=["disposition"]),
            models.Index(fields=["scenario"]),
            models.Index(fields=["decided_at"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["source_world_id", "source_run_id"], name="unique_simulation_run_disposition"),
        ]

    def __str__(self) -> str:
        return f"{self.source_world_id}:{self.source_run_id}:{self.disposition}"

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValueError("SimulationRunDisposition is immutable once recorded.")
        return super().save(*args, **kwargs)


class SimulationSnapshotItem(models.Model):
    """Searchable normalized item extracted from one simulation snapshot."""

    class ItemType(models.TextChoices):
        SUMMARY = "summary", "摘要"
        RUN = "run", "仿真运行"
        NODE_STATE = "node_state", "节点状态"
        TURN = "turn", "推演日志"
        FAILURE = "failure", "失败记录"
        EVENT = "event", "观察事件"
        PROPOSAL = "proposal", "修订建议"
        CHANGE_SET = "change_set", "变更集"
        CHANGE_OPERATION = "change_operation", "变更操作"

    item_id = models.CharField("快照明细ID", max_length=128, primary_key=True)
    snapshot = models.ForeignKey(
        SimulationSnapshot,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="仿真快照",
    )
    item_type = models.CharField("明细类型", max_length=32, choices=ItemType.choices)
    source_model = models.CharField("来源模型", max_length=96)
    source_pk = models.CharField("来源主键", max_length=128, blank=True)
    title = models.CharField("标题", max_length=255, blank=True)
    summary = models.TextField("摘要", blank=True)
    sort_order = models.PositiveIntegerField("排序", default=0)
    payload_json = models.JSONField("标准化内容", default=dict, blank=True)

    class Meta:
        db_table = "core_simulation_snapshot_item"
        verbose_name = "仿真快照明细"
        verbose_name_plural = "仿真快照明细"
        ordering = ["snapshot", "sort_order", "item_id"]
        indexes = [
            models.Index(fields=["snapshot", "item_type"]),
            models.Index(fields=["source_model", "source_pk"]),
            models.Index(fields=["item_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.snapshot_id}:{self.item_type}:{self.source_pk}"

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValueError("SimulationSnapshotItem is immutable once archived.")
        return super().save(*args, **kwargs)
