"""Shared abstract model primitives."""

from django.db import models


class TimestampedModel(models.Model):
    """Shared creation/update timestamps for mutable authority records."""

    created_at = models.DateTimeField("创建时间", help_text="记录创建时的 UTC 时间。")
    updated_at = models.DateTimeField(
        "更新时间",
        null=True,
        blank=True,
        help_text="权威系统最后一次更新记录时的 UTC 时间。",
    )

    class Meta:
        abstract = True
