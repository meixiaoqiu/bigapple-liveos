"""Risk-alert service layer: rules, evaluation, lifecycle."""

from uuid import uuid4
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .event_ledger import append_event
from .event_payloads import _public_event_payload, _public_ref
from .exceptions import DomainError
from .models import (
    Member,
    Resource,
    RiskRule,
    RiskAlert,
    SystemEvent,
)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


# ── built-in rules ─────────────────────────────────────────

BUILTIN_RULES = [
    {
        "rule_id": "risk-resource-low-stock",
        "name": "资源低库存",
        "description": "当前库存低于预警线",
        "domain": RiskRule.Domain.RESOURCE,
        "metric_key": "current_stock",
        "severity": RiskRule.Severity.HIGH,
        "visibility": RiskRule.Visibility.PUBLIC,
        "threshold_operator": "lte",
        "responsible_role": "governance",
    },
    {
        "rule_id": "risk-capacity-high",
        "name": "承载力不足",
        "description": "能力指标使用率超过阈值",
        "domain": RiskRule.Domain.CAPACITY,
        "metric_key": "remaining",
        "severity": RiskRule.Severity.MEDIUM,
        "visibility": RiskRule.Visibility.PUBLIC,
        "threshold_operator": "lte",
        "threshold_value": Decimal("15"),
        "responsible_role": "governance",
    },
    {
        "rule_id": "risk-dispute-open-high",
        "name": "公开争议过多",
        "description": "活跃争议数量超过阈值",
        "domain": RiskRule.Domain.DISPUTE,
        "metric_key": "open_count",
        "severity": RiskRule.Severity.HIGH,
        "visibility": RiskRule.Visibility.PUBLIC,
        "threshold_operator": "gte",
        "threshold_value": Decimal("5"),
        "responsible_role": "finance",
    },
    {
        "rule_id": "risk-simulation-failure",
        "name": "模拟故障",
        "description": "存在未处理的模拟运行时故障",
        "domain": RiskRule.Domain.SIMULATION,
        "metric_key": "failures",
        "severity": RiskRule.Severity.CRITICAL,
        "visibility": RiskRule.Visibility.PUBLIC,
        "responsible_role": "governance",
    },
]


@transaction.atomic
def ensure_builtin_risk_rules() -> int:
    created = 0
    for spec in BUILTIN_RULES:
        _, is_new = RiskRule.objects.update_or_create(
            rule_id=spec["rule_id"], defaults=spec,
        )
        if is_new:
            created += 1
    return created


# ── alert lifecycle ────────────────────────────────────────

def _dedupe_key(domain: str, source_type: str, source_id: str, metric_key: str = "") -> str:
    return f"{domain}:{source_type}:{source_id}:{metric_key}"


def trigger_risk_alert(
    *,
    rule: RiskRule | None,
    domain: str,
    title: str,
    summary: str,
    severity: str = "",
    visibility: str = "",
    source_type: str,
    source_id: str,
    source_url: str = "",
    metric_key: str = "",
    metric_value: Decimal | None = None,
    threshold_value: Decimal | None = None,
) -> RiskAlert:
    dedupe = _dedupe_key(domain, source_type, source_id, metric_key)
    now = timezone.now()

    alert = RiskAlert.objects.filter(dedupe_key=dedupe).first()
    if alert is None:
        alert = RiskAlert.objects.create(
            alert_id=_new_id("risk"),
            rule=rule,
            domain=domain,
            severity=severity or "medium",
            visibility=visibility or "public",
            title=title,
            summary=summary,
            dedupe_key=dedupe,
            source_type=source_type,
            source_id=source_id,
            source_url=source_url or "",
            metric_key=metric_key,
            metric_value=metric_value,
            threshold_value=threshold_value,
            responsible_role=rule.responsible_role if rule else "",
            first_seen_at=now,
            last_seen_at=now,
        )
        append_event(
            event_type=SystemEvent.EventType.RISK_ALERT_TRIGGERED,
            aggregate_type="RiskAlert",
            aggregate_id=alert.alert_id,
            payload_json=_public_event_payload(
                subject_type="risk_alert",
                subject_ref=_public_ref("risk-alert", alert.alert_id),
                subject_label=title,
                action="triggered",
                stage=alert.status,
                summary=summary,
                public_facts={
                    "alert_id": alert.alert_id, "domain": domain,
                    "severity": alert.severity, "title": title,
                },
            ),
            occurred_at=now,
        )
    else:
        alert.last_seen_at = now
        alert.metric_value = metric_value
        alert.save(update_fields=["last_seen_at", "metric_value"])
    return alert


def acknowledge_risk_alert(alert: RiskAlert, actor: Member, note: str = "") -> RiskAlert:
    alert = RiskAlert.objects.select_for_update().get(pk=alert.pk)
    alert.status = RiskAlert.Status.ACKNOWLEDGED
    alert.acknowledged_by = actor
    alert.acknowledged_at = timezone.now()
    if note:
        alert.resolution_note = note
    alert.save(update_fields=["status", "acknowledged_by", "acknowledged_at", "resolution_note"])
    append_event(
        event_type=SystemEvent.EventType.RISK_ALERT_ACKNOWLEDGED,
        aggregate_type="RiskAlert", aggregate_id=alert.alert_id,
        actor_member=actor,
        payload_json=_public_event_payload(subject_type="risk_alert",
            subject_ref=_public_ref("risk-alert", alert.alert_id),
            subject_label=alert.title, action="acknowledged", stage=alert.status,
            summary=f"风险 {alert.alert_id} 已确认。", public_facts={}),
        occurred_at=alert.acknowledged_at,
    )
    return alert


def resolve_risk_alert(alert: RiskAlert, actor: Member, note: str = "", public_note: str = "") -> RiskAlert:
    alert = RiskAlert.objects.select_for_update().get(pk=alert.pk)
    alert.status = RiskAlert.Status.RESOLVED
    alert.resolved_by = actor
    alert.resolved_at = timezone.now()
    if note:
        alert.resolution_note = note
    if public_note:
        alert.public_note = public_note
    alert.save(update_fields=["status", "resolved_by", "resolved_at", "resolution_note", "public_note"])
    append_event(
        event_type=SystemEvent.EventType.RISK_ALERT_RESOLVED,
        aggregate_type="RiskAlert", aggregate_id=alert.alert_id,
        actor_member=actor,
        payload_json=_public_event_payload(subject_type="risk_alert",
            subject_ref=_public_ref("risk-alert", alert.alert_id),
            subject_label=alert.title, action="resolved", stage=alert.status,
            summary=f"风险 {alert.alert_id} 已解除。", public_facts={"public_note": public_note}),
        occurred_at=alert.resolved_at,
    )
    return alert


# ── evaluators ──────────────────────────────────────────────

def evaluate_resource_risks() -> int:
    rule = RiskRule.objects.get(rule_id="risk-resource-low-stock")
    count = 0
    for resource in Resource.objects.filter(warning_threshold__gt=0, current_stock__lte=models.F("warning_threshold")):
        trigger_risk_alert(
            rule=rule, domain=RiskRule.Domain.RESOURCE,
            title=f"低库存：{resource.name or resource.resource_id}",
            summary=f"当前库存 {resource.current_stock} <= 预警线 {resource.warning_threshold} {resource.unit}",
            severity=rule.severity, visibility=rule.visibility,
            source_type="resource", source_id=resource.resource_id,
            source_url=f"/resources/{resource.resource_id}/offers/",
            metric_key="current_stock", metric_value=resource.current_stock,
            threshold_value=resource.warning_threshold,
        )
        count += 1
    # Auto-resolve alerts for resources now above threshold
    from django.db.models import F
    active = RiskAlert.objects.filter(
        rule=rule, status__in=[RiskAlert.Status.ACTIVE, RiskAlert.Status.ACKNOWLEDGED],
    )
    for alert in active:
        resource = Resource.objects.filter(resource_id=alert.source_id).first()
        if resource and resource.current_stock > resource.warning_threshold:
            alert.status = RiskAlert.Status.RESOLVED
            alert.resolved_at = timezone.now()
            alert.resolution_note = "库存已恢复正常。"
            alert.save(update_fields=["status", "resolved_at", "resolution_note"])
    return count


def evaluate_all_risks() -> dict:
    ensure_builtin_risk_rules()
    return {
        "resource": evaluate_resource_risks(),
    }


def build_risk_summary(visibility: str | None = None) -> dict:
    """Return a risk-summary dict usable by observer/workspace dashboards.
    When *visibility* is set, only alerts with that visibility are counted.
    """
    qs = RiskAlert.objects.all()
    if visibility is not None:
        qs = qs.filter(visibility=visibility)
    active_qs = qs.filter(status__in=[
        RiskRule.Status.ACTIVE, "acknowledged", "investigating",
    ])
    high = active_qs.filter(severity__in=[
        "critical", "high",
    ]).count()
    medium = active_qs.filter(severity="medium").count()
    low = active_qs.filter(severity="low").count()
    resolved = qs.filter(status=RiskAlert.Status.RESOLVED).count()
    top = list(active_qs.order_by("-severity", "-first_seen_at")[:3])
    return {
        "high": high,
        "medium": medium,
        "low": low,
        "resolved": resolved,
        "total_active": high + medium + low,
        "top_active": [
            {"title": a.title, "severity": a.severity, "alert_id": a.alert_id}
            for a in top
        ],
    }


@transaction.atomic
def update_risk_rule(rule: RiskRule, actor: Member, **changes) -> RiskRule:
    """Update mutable fields on a RiskRule and write a SystemEvent."""
    allowed = {
        "threshold_value", "threshold_operator", "severity",
        "visibility", "status", "responsible_role",
        "auto_create_public_event", "description",
    }
    invalid = set(changes.keys()) - allowed
    if invalid:
        raise DomainError(f"不可修改的字段: {', '.join(sorted(invalid))}")
    for field, value in changes.items():
        setattr(rule, field, value)
    rule.save(update_fields=list(changes.keys()))
    append_event(
        event_type=SystemEvent.EventType.RISK_RULE_UPDATED,
        aggregate_type="RiskRule", aggregate_id=rule.rule_id,
        actor_member=actor,
        payload_json=_public_event_payload(
            subject_type="risk_rule", subject_ref=_public_ref("risk-rule", rule.rule_id),
            subject_label=rule.name, action="updated", stage=rule.status,
            summary=f"规则 {rule.rule_id} 已更新。",
            public_facts={"changes": list(changes.keys())},
        ),
        occurred_at=timezone.now(),
    )
    return rule
