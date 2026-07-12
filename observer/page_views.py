"""HTML and HTMX observer views."""

from __future__ import annotations

from typing import Any

from django.http import Http404, HttpRequest
from django.shortcuts import render
from django.views.decorators.http import require_GET

from core.models import SimulationSnapshot

from .page_context import observer_context
from .dashboard_theme import build_dashboard_theme_context
from .simulation_reports import public_simulation_report, public_simulation_reports
from .theme import get_theme_partial_path, get_theme_template_path
from .timeline_context import observer_timeline_events_for_request
from .theme_views import apply_theme_query_override


@require_GET
def observer_page(request: HttpRequest, **_kwargs):
    apply_theme_query_override(request)
    context = observer_context()
    context["timeline_events"] = observer_timeline_events_for_request(request, context["command_dashboard"])
    context["timeline_compact"] = request.GET.get("compact") == "1"
    context["selected_task_id"] = request.GET.get("quest_task") or request.GET.get("task_id") or ""
    context["quest_status"] = request.GET.get("quest_status") or ""
    context["dashboard_context"] = build_dashboard_theme_context(request, context)
    return render(request, get_theme_template_path(request, "dashboard.html"), context)


@require_GET
def simulation_report_list_page(request: HttpRequest, **_kwargs):
    apply_theme_query_override(request)
    return render(
        request,
        get_theme_template_path(request, "simulation_reports.html"),
        {
            "reports": public_simulation_reports(),
        },
    )


@require_GET
def simulation_report_detail_page(request: HttpRequest, snapshot_id: str, **_kwargs):
    apply_theme_query_override(request)
    try:
        report = public_simulation_report(snapshot_id)
    except SimulationSnapshot.DoesNotExist as exc:
        raise Http404("Simulation report not found.") from exc
    return render(
        request,
        get_theme_template_path(request, "simulation_report_detail.html"),
        {
            "report": report,
        },
    )


def dashboard_theme_context(request: HttpRequest) -> dict[str, Any]:
    apply_theme_query_override(request)
    context = observer_context()
    context["selected_task_id"] = request.GET.get("quest_task") or request.GET.get("task_id") or ""
    context["quest_status"] = request.GET.get("quest_status") or ""
    context["dashboard_context"] = build_dashboard_theme_context(request, context)
    return context


@require_GET
def dashboard_missions_partial(request: HttpRequest, **_kwargs):
    return render(request, get_theme_partial_path(request, "mission_list.html"), dashboard_theme_context(request))


@require_GET
def dashboard_events_partial(request: HttpRequest, **_kwargs):
    return render(request, get_theme_partial_path(request, "event_feed.html"), dashboard_theme_context(request))


@require_GET
def dashboard_map_points_partial(request: HttpRequest, **_kwargs):
    return render(request, get_theme_partial_path(request, "map_points.html"), dashboard_theme_context(request))


@require_GET
def dashboard_task_detail_partial(request: HttpRequest, **_kwargs):
    return render(request, get_theme_partial_path(request, "task_detail.html"), dashboard_theme_context(request))


@require_GET
def dashboard_risk_partial(request: HttpRequest, **_kwargs):
    return render(request, get_theme_partial_path(request, "risk_panel.html"), dashboard_theme_context(request))


@require_GET
def dashboard_capacity_partial(request: HttpRequest, **_kwargs):
    return render(request, get_theme_partial_path(request, "capacity_panel.html"), dashboard_theme_context(request))


@require_GET
def dashboard_photo_story_partial(request: HttpRequest, **_kwargs):
    return render(request, get_theme_partial_path(request, "photo_story_feed.html"), dashboard_theme_context(request))
