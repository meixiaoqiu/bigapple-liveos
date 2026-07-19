"""Shared runtime template context processors."""

from __future__ import annotations

from .runtime_nav import build_runtime_nav


def runtime_nav(request):
    """Inject unified runtime nav into every template context."""
    return {"runtime_nav": build_runtime_nav(request)}
