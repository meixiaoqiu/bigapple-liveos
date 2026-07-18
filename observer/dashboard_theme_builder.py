"""Build theme-facing dashboard context from observer read models."""

from __future__ import annotations

import re
from typing import Any

from django.http import HttpRequest

from worlds.context import world_context_for_request

from .dashboard_theme_defaults import _default_dashboard_context
from .dashboard_theme_utils import (
    _event_level,
    _event_status,
    _first_location,
    _mission_progress,
    _mission_status,
    _parse_percent,
    _safe_int,
)


def build_dashboard_theme_context(request: HttpRequest, raw_data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a stable theme-facing dashboard context without changing business queries."""

    raw = raw_data or {}
    context = _default_dashboard_context()
    world = world_context_for_request(request)
    command_dashboard = raw.get("command_dashboard") or {}

    site = command_dashboard.get("site", "未配置据点")
    day = command_dashboard.get("day", 1)
    status = command_dashboard.get("status", "待初始化")
    current_time = str(command_dashboard.get("current_time") or "")
    health = command_dashboard.get("health") or {}
    subtitle = f"{site} · 第{day}天 · {status}"
    if current_time:
        subtitle = f"{subtitle} · 当前时间 {current_time}"
    context["hero"] = {
        "title": "大苹果社区动态",
        "subtitle": subtitle,
        "status_label": str(health.get("label") or "待初始化"),
        "status_level": "risk" if "风险" in str(health.get("label", "")) else "watch",
    }

    stats = []
    for index, metric in enumerate(command_dashboard.get("metrics") or []):
        label = str(metric.get("label") or f"指标 {index + 1}")
        value = str(metric.get("value") or "0")
        stats.append(
            {
                "key": re.sub(r"[^a-z0-9_]+", "_", label.lower()) or f"stat_{index + 1}",
                "label": label,
                "value": value,
                "percent": _parse_percent(value, default=0),
                "trend": str(metric.get("note") or ""),
                "icon": str(metric.get("icon") or "dot"),
            }
        )
    if stats:
        context["stats"] = stats

    missions = []
    plan_nodes = list(raw.get("current_plan_nodes") or []) + list(raw.get("next_plan_nodes") or [])
    for node in plan_nodes[:6]:
        status_value = str(getattr(node, "status", "planned"))
        progress_current, progress_total = _mission_progress(status_value)
        missions.append(
            {
                "id": str(getattr(node, "node_id", "")),
                "title": str(getattr(node, "title", "") or "未命名任务"),
                "summary": f"预计 {getattr(node, 'planned_duration_days', 0) or 0} 天 · {getattr(node, 'required_people_min', 0) or 0}-{getattr(node, 'required_people_max', 0) or 0} 人",
                "status": _mission_status(status_value),
                "progress_current": progress_current,
                "progress_total": progress_total,
                "reward": "计划推进",
                "icon": str(getattr(node, "node_type", "") or "mission"),
            }
        )
    if missions:
        context["missions"] = missions

    events = []
    for index, event in enumerate(command_dashboard.get("timeline_events") or []):
        tags = [str(tag) for tag in event.get("tags", [])]
        tone = str(event.get("tone") or "info")
        event_id = str(event.get("event_id") or "")
        ma_url = event.get("_member_application_detail_url", "")
        if ma_url:
            detail_url = ma_url
            action_label = "查看事项"
        else:
            detail_url = f"/events/{event_id}/" if event_id else ""
            action_label = "查看详情"
        events.append(
            {
                "id": event_id or f"timeline-{index + 1}",
                "title": str(event.get("title") or "未命名事件"),
                "summary": str(event.get("summary") or ""),
                "level": _event_level(tone),
                "status": _event_status(tone),
                "time": str(event.get("time") or ""),
                "location": _first_location(tags),
                "heat": str(event.get("metric_value") or ""),
                "photo_url": "",
                "action_label": action_label,
                "detail_url": detail_url,
            }
        )
    if events:
        context["events"] = events

    map_points = [
        {
            "id": "point-community",
            "title": str(site),
            "type": "community",
            "status": "active",
            "x": 50,
            "y": 48,
            "icon": "home",
            "label": "核心区",
            "score": None,
        }
    ]
    for index, mission in enumerate(context["missions"][:3]):
        map_points.append(
            {
                "id": f"mission-point-{mission['id'] or index}",
                "title": mission["title"],
                "type": "mission",
                "status": "active" if mission["status"] == "doing" else "normal",
                "x": 24 + index * 22,
                "y": 28 + index * 12,
                "icon": mission["icon"],
                "label": mission["title"],
                "score": None,
            }
        )
    for index, event in enumerate(context["events"][:3]):
        map_points.append(
            {
                "id": f"event-point-{index + 1}",
                "title": event["title"],
                "type": "event",
                "status": "risk" if event["level"] in {"high", "urgent"} else "new",
                "x": 34 + index * 18,
                "y": 64 - index * 10,
                "icon": event["level"],
                "label": event["location"] or "事件",
                "score": event["heat"] or None,
            }
        )
    context["map_points"] = map_points

    risk_summary = {"high": 0, "medium": 0, "low": 0, "resolved": 0}
    for item in command_dashboard.get("risk_overview") or []:
        tone = str(item.get("tone") or "")
        value = _safe_int(item.get("value"))
        if tone == "critical":
            risk_summary["high"] = value
        elif tone == "medium":
            risk_summary["medium"] = value
        elif tone == "resolved":
            risk_summary["resolved"] = value
        else:
            risk_summary["low"] = value
    context["risk_summary"] = risk_summary

    simulation_failures = []
    for failure in raw.get("latest_run_failures") or []:
        metadata = getattr(failure, "metadata", {}) if isinstance(getattr(failure, "metadata", {}), dict) else {}
        node = getattr(failure, "plan_node", None)
        node_label = f"{getattr(node, 'code', '')} {getattr(node, 'title', '')}".strip()
        missing_closures = []
        for item in metadata.get("missing_responsibility_closures") or []:
            if not isinstance(item, dict):
                continue
            missing_closures.append(
                {
                    "label": str(item.get("label") or item.get("code") or "未命名责任闭环"),
                    "status": str(item.get("status") or "未取得"),
                    "reasons": [str(reason) for reason in item.get("missing_reasons") or []],
                }
            )
        simulation_failures.append(
            {
                "node": node_label or str(getattr(failure, "plan_node_id", "") or "未关联节点"),
                "type": failure.get_failure_type_display(),
                "title": str(getattr(failure, "title", "") or ""),
                "description": str(getattr(failure, "description", "") or ""),
                "missing_closures": missing_closures,
                "cannot_continue_reasons": [str(reason) for reason in metadata.get("cannot_continue_reasons") or []],
                "recommended_actions": [str(action) for action in metadata.get("recommended_actions") or []],
            }
        )
    if simulation_failures:
        context["simulation_failures"] = simulation_failures[:3]

    role_pressure = []
    for item in command_dashboard.get("role_pressure") or []:
        role_pressure.append(
            {
                "name": str(item.get("name") or "未命名岗位"),
                "value": max(0, min(100, _safe_int(item.get("value")))),
            }
        )
    if role_pressure:
        context["role_pressure"] = role_pressure[:3]

    pending_disputes = []
    for item in command_dashboard.get("pending_disputes") or []:
        pending_disputes.append(
            {
                "id": str(item.get("id") or ""),
                "title": str(item.get("title") or "未命名争议"),
                "status": str(item.get("status") or "待处理"),
                "age": str(item.get("age") or ""),
            }
        )
    if pending_disputes:
        context["pending_disputes"] = pending_disputes[:3]

    capacity = command_dashboard.get("capacity") or {}
    current_text = str(capacity.get("current") or "0 / 0")
    match = re.search(r"(\d+)\s*/\s*(\d+)", current_text)
    current = _safe_int(match.group(1)) if match else 0
    total = _safe_int(match.group(2)) if match else 0
    context["capacity"] = {
        "current": current,
        "total": total,
        "percent": _safe_int(capacity.get("usage"), _parse_percent(current_text)),
        "safe_threshold": 85,
        "safe_label": str(capacity.get("threshold") or "< 85%"),
        "remaining": _safe_int(capacity.get("remaining"), max(total - current, 0)),
    }

    unlocked_count = sum(1 for achievement in context["achievements"] if achievement.get("unlocked"))
    context["user_progress"] = {
        "level": max(1, unlocked_count + 1),
        "xp": min(100, context["capacity"]["percent"]),
        "xp_next": 100,
        "points": raw.get("ledger_entries", 0) or 0,
        "badges_count": unlocked_count,
    }
    context["navigation"][0]["href"] = "/"
    context["navigation"][3]["href"] = "/api/v0.1/resources"
    context["navigation"][5]["href"] = "/api/v0.1/observer/summary"

    # ── top-nav (auth-aware) ──────────────────────────────────────────
    from live_os.access import is_authenticated, member_for_request

    top_nav: list[dict[str, Any]] = []
    if is_authenticated(request):
        member = member_for_request(request)
        top_nav.append({"label": "首页", "url": "/"})
        top_nav.append({"label": "事件流", "url": "/events/"})
        if member is not None:
            top_nav.append({"label": "我的主页", "url": f"/u/{member.member_no}/"})
        top_nav.append({"label": "Workspace", "url": "/workspace/"})
        top_nav.append({"label": "退出", "url": "/logout/"})
    else:
        top_nav.append({"label": "首页", "url": "/"})
        top_nav.append({"label": "事件流", "url": "/events/"})
        top_nav.append({"label": "注册", "url": "/register/"})
        top_nav.append({"label": "登录", "url": "/login/?next=/workspace/"})
        top_nav.append({"label": "Workspace", "url": "/workspace/"})
    context["top_nav"] = top_nav

    return context
