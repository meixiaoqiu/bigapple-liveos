"""Default dashboard theme presentation contract."""

from __future__ import annotations

from typing import Any


def _default_dashboard_context() -> dict[str, Any]:
    return {
        "hero": {
            "title": "大苹果社区动态",
            "subtitle": "未配置据点 · 第1天 · 待初始化",
            "status_label": "待初始化",
            "status_level": "watch",
        },
        "stats": [],
        "mainline": {
            "plan_title": "",
            "revision_title": "",
            "stage": None,
            "current_nodes": [],
            "next_nodes": [],
            "blockers": [],
            "progress": {"completed": 0, "total": 0, "percent": 0},
            "latest_run": None,
            "proposal_summary": None,
            "empty": True,
        },
        "events": [],
        "photos": [],
        "resources": [],
        "risk_summary": {"high": 0, "medium": 0, "low": 0, "resolved": 0},
        "role_pressure": [],
        "pending_disputes": [],
        "capacity": {"current": 0, "total": 0, "percent": 0, "safe_threshold": 85, "remaining": 0},
        "navigation": [
            {"key": "overview", "label": "总览", "href": "/"},
            {"key": "events", "label": "事件", "href": "#events"},
            {"key": "resources", "label": "全部资源", "href": "/resources/"},
            {"key": "members", "label": "成员动态", "href": "#events"},
            {"key": "data", "label": "审计账本", "href": "/event-ledger/"},
        ],
    }
