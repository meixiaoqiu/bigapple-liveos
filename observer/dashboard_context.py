"""Observer command-dashboard read model."""

from __future__ import annotations

from typing import Any

from django.db.models import F
from django.utils import timezone

from core.models import CapacityAssessment, Dispute, Event, Member, ProjectPlan, Resource, SimulationRun, Task
from live_os.api.serializers.events import public_event_summary

from .event_context import is_member_application_stage_event, public_member_application_rows
from .presentation import (
    RISK_LABELS,
    dashboard_tags_for_event,
    decimal_sort_value,
    event_level_label,
    event_tone,
    percent_ratio,
    relative_age,
    task_completion_rate,
)


def observer_command_dashboard_context() -> dict[str, Any]:
    """Build observer dashboard rows from Live OS authority tables."""

    latest = CapacityAssessment.objects.order_by("-simulation_day", "-created_at").first()
    active_plan = ProjectPlan.objects.filter(status=ProjectPlan.Status.ACTIVE).order_by("plan_id").first()
    latest_run = SimulationRun.objects.order_by("-started_at", "run_id").first()
    recent_events_all = list(Event.objects.filter(visibility=Event.Visibility.PUBLIC).order_by("-occurred_at", "event_id")[:12])
    recent_events = [e for e in recent_events_all if not is_member_application_stage_event(e)][:8]
    warning_resources = Resource.objects.filter(current_stock__lte=F("warning_threshold")).count()
    open_disputes_queryset = Dispute.objects.exclude(
        status__in=[Dispute.Status.RESOLVED, Dispute.Status.REJECTED, Dispute.Status.REVERSED]
    )
    open_disputes_count = open_disputes_queryset.count()

    capacity_current = latest.current_formal_members if latest else Member.objects.filter(status=Member.Status.ACTIVE).count()
    capacity_total = latest.maximum_admissible_members if latest else max(capacity_current, 0)
    capacity_usage = percent_ratio(capacity_current, capacity_total)
    completion_rate = task_completion_rate()
    total_tasks = Task.objects.count()
    accepted_tasks = Task.objects.filter(status=Task.Status.ACCEPTED).count()
    active_members = Member.objects.filter(status__in=[Member.Status.ACTIVE, Member.Status.ADMITTED]).count()

    if any(event.severity == Event.Severity.CRITICAL for event in recent_events):
        health = {
            "label": "高风险",
            "summary": "近期存在重大公开事件，需要优先处理。",
            "level": "critical",
        }
    elif warning_resources or open_disputes_count or capacity_usage >= 85:
        health = {
            "label": "需要关注",
            "summary": "当前存在资源、容量或申诉压力，需要运营跟进。",
            "level": "warning",
        }
    else:
        health = {
            "label": "稳定",
            "summary": "当前没有公开重大风险。",
            "level": "stable",
        }

    timeline_events = [
        {
            "event_id": event.event_id,
            "time": timezone.localtime(event.occurred_at).strftime("%H:%M"),
            "ago": relative_age(event.occurred_at),
            "level": event_level_label(event),
            "tone": event_tone(event),
            "title": event.title,
            "summary": public_event_summary(event),
            "tags": dashboard_tags_for_event(event),
            "metric_label": "来源",
            "metric_value": event.get_generated_by_display(),
            "_sort_at": event.occurred_at,
        }
        for event in recent_events
    ]

    # Merge aggregated member application cards and sort by occurred_at desc
    for ma in public_member_application_rows():
        timeline_events.append({
            "event_id": f"ma-{ma['application_id']}",
            "time": timezone.localtime(ma["occurred_at"]).strftime("%H:%M"),
            "ago": relative_age(ma["occurred_at"]),
            "level": "notice",
            "tone": "info",
            "title": ma["title"],
            "summary": ma["subtitle"],
            "tags": ["成员报名"],
            "metric_label": "状态",
            "metric_value": ma["status"],
            "_member_application_detail_url": ma["detail_url"],
            "_sort_at": ma["occurred_at"],
        })
    timeline_events.sort(key=lambda e: e.get("_sort_at", timezone.now()), reverse=True)
    timeline_events = timeline_events[:8]
    for ev in timeline_events:
        ev.pop("_sort_at", None)

    critical_events = sum(1 for event in recent_events if event.severity == Event.Severity.CRITICAL)
    warning_events = sum(1 for event in recent_events if event.severity == Event.Severity.WARNING)
    info_events = sum(1 for event in recent_events if event.severity == Event.Severity.INFO)
    risk_overview = [
        {"label": "高风险", "value": critical_events, "tone": "critical"},
        {"label": "中风险", "value": warning_events, "tone": "medium"},
        {"label": "公开事件", "value": info_events, "tone": "low"},
        {"label": "资源预警", "value": warning_resources, "tone": "resolved"},
    ]

    role_pressure = []
    if latest:
        for name, value in sorted(
            latest.risk_indicators.items(),
            key=lambda item: decimal_sort_value(item[1]),
            reverse=True,
        )[:3]:
            role_pressure.append({"name": RISK_LABELS.get(name, name), "value": value})

    pending_disputes = [
        {
            "id": dispute.dispute_id,
            "title": dispute.get_dispute_type_display(),
            "status": dispute.get_status_display(),
            "age": relative_age(dispute.submitted_at),
        }
        for dispute in open_disputes_queryset.order_by("-submitted_at", "dispute_id")[:3]
    ]

    status = latest_run.get_status_display() if latest_run else ("运行中" if active_plan else "待初始化")
    site = active_plan.target_location if active_plan else "未配置据点"

    return {
        "site": site,
        "day": latest.simulation_day if latest else 1,
        "status": status,
        "current_time": timezone.localtime(timezone.now()).strftime("%H:%M"),
        "health": health,
        "metrics": [
            {
                "icon": "人",
                "label": "活跃成员",
                "value": str(active_members),
                "note": f"正式容量 {capacity_current} / {capacity_total}",
            },
            {
                "icon": "容",
                "label": "当前容量",
                "value": f"{capacity_current} / {capacity_total}",
                "note": f"容量使用率 {capacity_usage}%",
            },
            {
                "icon": "务",
                "label": "任务完成率",
                "value": f"{completion_rate}%",
                "note": f"已验收 {accepted_tasks} / {total_tasks}",
            },
            {
                "icon": "资",
                "label": "资源预警",
                "value": str(warning_resources),
                "note": "低于或等于预警线",
            },
            {
                "icon": "争",
                "label": "未关闭申诉",
                "value": str(open_disputes_count),
                "note": "需要治理跟进",
            },
        ],
        "timeline_events": timeline_events,
        "risk_overview": risk_overview,
        "capacity": {
            "current": f"{capacity_current} / {capacity_total}",
            "usage": capacity_usage,
            "threshold": "< 85%",
            "remaining": max(capacity_total - capacity_current, 0),
        },
        "role_pressure": role_pressure,
        "pending_disputes": pending_disputes,
    }
