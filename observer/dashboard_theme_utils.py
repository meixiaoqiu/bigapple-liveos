"""Small presentation helpers for dashboard theme context building."""

from __future__ import annotations

import re
from typing import Any


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def _parse_percent(value: Any, default: int = 0) -> int:
    text = str(value or "")
    if "%" in text:
        return max(0, min(100, _safe_int(text.split("%", 1)[0].strip(), default)))
    match = re.search(r"(\d+)\s*/\s*(\d+)", text)
    if match:
        current = _safe_int(match.group(1))
        total = _safe_int(match.group(2), 1)
        if total > 0:
            return max(0, min(100, round(current / total * 100)))
    return default

def _first_location(tags: list[str]) -> str:
    for tag in tags:
        if "位置" in tag:
            return tag.replace("位置", "").strip() or tag
    return ""

def _event_level(tone: str) -> str:
    return {
        "critical": "urgent",
        "high": "high",
        "medium": "medium",
        "notice": "notice",
        "info": "info",
        "resolved": "info",
    }.get(tone, "info")

def _event_status(tone: str) -> str:
    return "done" if tone == "resolved" else "watching" if tone in {"notice", "medium"} else "new"

