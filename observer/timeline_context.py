"""Observer timeline filtering helpers."""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest


def observer_timeline_events_for_request(request: HttpRequest, dashboard: dict[str, Any]) -> list[dict[str, Any]]:
    """Filter presentation timeline rows for HTMX partial rendering."""

    rows = list(dashboard["timeline_events"])
    only_open = request.GET.get("only_open") == "1"
    selected_level = request.GET.get("level", "all")
    if only_open:
        rows = [row for row in rows if row["tone"] != "resolved"]
    if selected_level and selected_level != "all":
        rows = [row for row in rows if row["level"] == selected_level]
    return rows
