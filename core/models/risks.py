"""Formal risk-alert system: rules, alerts, and lifecycle events."""

from django.db import models
from django.utils import timezone

from .identity import Member


class RiskRule(models.Model):
    class Domain(models.TextChoices):
        RESOURCE = "resource", "资源库存"
        CAPACITY = "capacity", "承载力"
        DISPUTE = "dispute", "争议"
        SIMULATION = "simulation", "模拟"
        PROCUREMENT = "procurement", "采购"
        PROVIDER = "provider", "供应者"
        SYSTEM = "system", "系统"

    class Severity(models.TextChoices):
        LOW = "low", "低"
        MEDIUM = "medium", "中"
        HIGH = "high", "高"
        CRITICAL = "critical", "严重"

    class Visibility(models.TextChoices):
        PUBLIC = "public", "公开"
        INTERNAL = "internal", "内部"
        PRIVATE = "private", "私密"

    class Status(models.TextChoices):
        ACTIVE = "active", "启用"
        INACTIVE = "inactive", "停用"

    rule_id = models.CharField("规则ID", max_length=64, primary_key=True)
    name = models.CharField("名称", max_length=128)
    description = models.TextField("描述", blank=True)
    domain = models.CharField("领域", max_length=16, choices=Domain.choices)
    metric_key = models.CharField("指标键", max_length=64, blank=True)
    severity = models.CharField("严重程度", max_length=16, choices=Severity.choices, default=Severity.MEDIUM)
    visibility = models.CharField("可见性", max_length=16, choices=Visibility.choices, default=Visibility.PUBLIC)
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.ACTIVE)
    threshold_value = models.DecimalField("阈值", max_digits=14, decimal_places=2, null=True, blank=True)
    threshold_operator = models.CharField("阈值运算符", max_length=8, default="lte")
    window_minutes = models.PositiveIntegerField("窗口分钟", default=0)
    responsible_role = models.CharField("责任角色", max_length=32, blank=True)
    auto_create_public_event = models.BooleanField("自动创建公开事件", default=True)
    metadata = models.JSONField("扩展", default=dict, blank=True)
    created_at = models.DateTimeField("创建", default=timezone.now)
    updated_at = models.DateTimeField("更新", auto_now=True)

    class Meta:
        db_table = "core_risk_rule"
        verbose_name = "风险规则"
        verbose_name_plural = "风险规则"


class RiskAlert(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "活跃"
        ACKNOWLEDGED = "acknowledged", "已确认"
        INVESTIGATING = "investigating", "调查中"
        RESOLVED = "resolved", "已解除"
        DISMISSED = "dismissed", "已忽略"

    alert_id = models.CharField("告警ID", max_length=64, primary_key=True)
    rule = models.ForeignKey(RiskRule, on_delete=models.PROTECT, null=True, blank=True, related_name="alerts")
    domain = models.CharField("领域", max_length=16, choices=RiskRule.Domain.choices)
    severity = models.CharField("严重程度", max_length=16, choices=RiskRule.Severity.choices, default=RiskRule.Severity.MEDIUM)
    visibility = models.CharField("可见性", max_length=16, choices=RiskRule.Visibility.choices, default=RiskRule.Visibility.PUBLIC)
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.ACTIVE)
    title = models.CharField("标题", max_length=256)
    summary = models.TextField("摘要")
    dedupe_key = models.CharField("去重键", max_length=191, unique=True, blank=False,
                                  help_text="唯一键：domain:source_type:source_id:metric_key")
    source_type = models.CharField("来源类型", max_length=64)
    source_id = models.CharField("来源ID", max_length=128)
    source_url = models.CharField("来源链接", max_length=256, blank=True)
    metric_key = models.CharField("指标键", max_length=64, blank=True)
    metric_value = models.DecimalField("指标值", max_digits=14, decimal_places=2, null=True, blank=True)
    threshold_value = models.DecimalField("阈值", max_digits=14, decimal_places=2, null=True, blank=True)
    responsible_role = models.CharField("责任角色", max_length=32, blank=True)
    first_seen_at = models.DateTimeField("首次发现", default=timezone.now)
    last_seen_at = models.DateTimeField("最后发现", default=timezone.now)
    acknowledged_by = models.ForeignKey(Member, on_delete=models.PROTECT, null=True, blank=True, related_name="acknowledged_risks")
    acknowledged_at = models.DateTimeField("确认时间", null=True, blank=True)
    resolved_by = models.ForeignKey(Member, on_delete=models.PROTECT, null=True, blank=True, related_name="resolved_risks")
    resolved_at = models.DateTimeField("解除时间", null=True, blank=True)
    resolution_note = models.TextField("处理记录", blank=True)
    public_note = models.TextField("公开说明", blank=True)
    metadata = models.JSONField("扩展", default=dict, blank=True)
    created_at = models.DateTimeField("创建", default=timezone.now)
    updated_at = models.DateTimeField("更新", auto_now=True)

    class Meta:
        db_table = "core_risk_alert"
        verbose_name = "风险告警"
        verbose_name_plural = "风险告警"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["severity"]),
            models.Index(fields=["domain"]),
            models.Index(fields=["source_type", "source_id"]),
        ]
