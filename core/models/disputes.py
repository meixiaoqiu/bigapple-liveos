"""Capacity assessment models."""

from django.db import models

class CapacityAssessment(models.Model):
    """Capacity decision record controlling whether new members can enter."""

    assessment_id = models.CharField("容量评估ID", max_length=64, primary_key=True)
    simulation_day = models.PositiveIntegerField("模拟日期")
    current_covenanters = models.PositiveIntegerField("当前守约者数")
    current_contributors = models.PositiveIntegerField("当前贡献者数")
    maximum_admissible_members = models.PositiveIntegerField("当前最大可接纳人数")
    recommended_new_members = models.PositiveIntegerField("建议新增人数")
    bottlenecks = models.JSONField("容量瓶颈", default=list)
    risk_indicators = models.JSONField("风险指标", default=dict)
    reasons = models.JSONField("评估原因", default=list)
    rule_version = models.CharField("规则版本", max_length=32)
    created_at = models.DateTimeField("创建时间")
    metadata = models.JSONField("扩展数据", default=dict, blank=True)

    class Meta:
        db_table = "core_capacity_assessment"
        verbose_name = "容量评估"
        verbose_name_plural = "容量评估"
        ordering = ["-simulation_day", "-created_at"]
        indexes = [models.Index(fields=["simulation_day"])]

    def __str__(self) -> str:
        return self.assessment_id
