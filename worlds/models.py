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
