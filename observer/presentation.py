"""Presentation helpers for observer dashboard data."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.utils import timezone

from core.models import Event, Task


BOTTLENECK_LABELS = {
    "beds": "床位",
    "canteen": "食堂",
    "water": "水",
    "electricity": "电",
    "grain": "粮食",
    "warehouse": "仓库",
    "hygiene": "公共卫生",
    "tasks": "任务缺口",
    "training": "培训",
    "governance": "治理",
    "high_load_roles": "高负担岗位",
    "disputes": "争议",
    "satisfaction": "满意度",
    "fatigue": "疲劳",
    "exit_risk": "退出风险",
}

RISK_LABELS = {
    "beds_available": "可用床位",
    "canteen_load": "食堂负载",
    "task_gap": "任务缺口",
    "average_satisfaction": "平均满意度",
    "average_fatigue": "平均疲劳值",
    "open_disputes": "未关闭申诉",
    "exit_risk_members": "退出风险人数",
}


def task_completion_rate() -> int:
    total = Task.objects.count()
    if total == 0:
        return 0
    completed = Task.objects.filter(status=Task.Status.ACCEPTED).count()
    return round(completed * 100 / total)


def percent_ratio(current: int, total: int) -> int:
    if total <= 0:
        return 0
    return max(0, min(100, round(current * 100 / total)))


def decimal_sort_value(value: object) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def event_tone(event: Event) -> str:
    if event.severity == Event.Severity.CRITICAL:
        return "critical"
    if event.severity == Event.Severity.WARNING:
        return "medium"
    return "info"


def event_level_label(event: Event) -> str:
    if event.severity == Event.Severity.CRITICAL:
        return "重大"
    if event.severity == Event.Severity.WARNING:
        return "中风险"
    return "信息"


def relative_age(value) -> str:
    delta = timezone.now() - value
    minutes = max(0, int(delta.total_seconds() // 60))
    if minutes < 1:
        return "刚刚"
    if minutes < 60:
        return f"{minutes}分钟前"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}小时前"
    return f"{hours // 24}天前"


def dashboard_tags_for_event(event: Event) -> list[str]:
    tags = [event.get_generated_by_display()]
    if event.related_task_id:
        tags.append(f"任务 {event.related_task_id}")
    if event.related_dispute_id:
        tags.append(f"申诉 {event.related_dispute_id}")
    if event.involved_member_ids:
        tags.append(f"成员 {len(event.involved_member_ids)}")
    return tags
