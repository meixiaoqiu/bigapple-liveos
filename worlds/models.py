from django.db import models
from django.utils import timezone


class WorldRegistry(models.Model):
    """Control-DB registry for world databases.

    World business data lives in the database named by this registry row. The
    registry itself stays in the control database so worlds can be created,
    archived, routed, and deleted without mixing their business rows.
    """

    class WorldType(models.TextChoices):
        REAL = "real", "真实世界"
        SIMULATION = "simulation", "仿真世界"

    class Status(models.TextChoices):
        ACTIVE = "active", "启用"
        ARCHIVED = "archived", "已归档"
        DELETED = "deleted", "已删除"

    world_id = models.CharField(
        "世界ID",
        max_length=64,
        primary_key=True,
        help_text="稳定世界 ID，例如 realworld 或 simulation0001。",
    )
    name = models.CharField("名称", max_length=120)
    world_type = models.CharField("世界类型", max_length=24, choices=WorldType.choices)
    database_alias = models.CharField(
        "数据库别名",
        max_length=64,
        default="default",
        help_text="Django DATABASES 中配置的别名，例如 realworld 或 simulation0001。",
    )
    database_name = models.CharField("数据库名称", max_length=128, blank=True)
    status = models.CharField("状态", max_length=24, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField("创建时间", default=timezone.now)
    updated_at = models.DateTimeField("更新时间", auto_now=True)
    archived_at = models.DateTimeField("归档时间", null=True, blank=True)

    class Meta:
        verbose_name = "世界注册表"
        verbose_name_plural = "世界注册表"
        ordering = ["world_id"]
        indexes = [
            models.Index(fields=["world_type", "status"]),
            models.Index(fields=["database_alias"]),
        ]

    def __str__(self) -> str:
        return self.world_id

    @property
    def is_realworld(self) -> bool:
        return self.world_type == self.WorldType.REAL


class WorldMaintenanceLog(models.Model):
    """Control-DB audit log for high-risk world maintenance operations.

    This model stays in the control database and records destructive actions
    like world resets. It is not written into the target world database so the
    audit trail survives even when the world database is flushed.
    """

    class Action(models.TextChoices):
        RESET_ZERO_START = "reset_zero_start", "重置到零起点基线"

    class StatusChoices(models.TextChoices):
        SUCCEEDED = "succeeded", "成功"
        FAILED = "failed", "失败"

    world = models.ForeignKey(
        WorldRegistry,
        on_delete=models.PROTECT,
        related_name="maintenance_logs",
        verbose_name="目标世界",
        help_text="被维护操作作用的目标世界注册表记录。",
    )
    action = models.CharField(
        "操作类型",
        max_length=64,
        choices=Action.choices,
        help_text="维护操作标识，例如 reset_zero_start。",
    )
    actor_username = models.CharField(
        "操作人",
        max_length=150,
        help_text="执行维护操作的 Django 用户名。",
    )
    status = models.CharField(
        "执行状态",
        max_length=32,
        choices=StatusChoices.choices,
        help_text="操作最终状态：成功或失败。",
    )
    force = models.BooleanField(
        "强制模式",
        default=False,
        help_text="是否绕过未处置运行的保护机制强制执行。",
    )
    counts_before_json = models.JSONField(
        "清空前记录数",
        default=dict,
        blank=True,
        help_text="操作前目标世界各核心表的记录数量。",
    )
    counts_after_json = models.JSONField(
        "清空后记录数",
        default=dict,
        blank=True,
        help_text="操作后（重新 seed 后）目标世界各核心表的记录数量。",
    )
    message = models.TextField(
        "结果消息",
        blank=True,
        help_text="操作结果或失败原因的补充说明。",
    )
    created_at = models.DateTimeField("记录时间", default=timezone.now)

    class Meta:
        verbose_name = "世界维护日志"
        verbose_name_plural = "世界维护日志"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["world", "action"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"{self.world_id} / {self.action} / {self.status} at {self.created_at}"
