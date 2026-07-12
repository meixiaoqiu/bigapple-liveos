"""Django Admin configuration for immutable simulation run records."""

from __future__ import annotations

from django.contrib import admin

from core.admin_support import (
    ImmutableHistoryAdminMixin,
    model_field_names,
)
from core.models import PlanNodeRunState, SimulationFailure, SimulationRun, SimulationTurn


@admin.register(SimulationRun)
class SimulationRunAdmin(ImmutableHistoryAdminMixin, admin.ModelAdmin):
    list_display = ("run_id", "plan_revision", "status", "current_day", "max_turns", "started_at", "ended_at")
    list_filter = ("status", "plan_revision")
    search_fields = (
        "run_id",
        "plan_revision__revision_code",
        "plan_revision__plan__name",
        "failure_summary",
    )
    list_select_related = ("plan_revision", "plan_revision__plan")
    date_hierarchy = "started_at"
    ordering = ("-started_at", "run_id")
    list_per_page = 50
    readonly_fields = model_field_names(SimulationRun)
    fieldsets = (
        ("运行身份", {"fields": ("run_id", "plan_revision", "status")}),
        ("进度", {"fields": ("current_day", "max_turns", "failure_summary")}),
        ("时间和扩展", {"fields": ("started_at", "ended_at", "metadata")}),
    )


@admin.register(PlanNodeRunState)
class PlanNodeRunStateAdmin(ImmutableHistoryAdminMixin, admin.ModelAdmin):
    list_display = (
        "state_id",
        "run",
        "plan_node",
        "status",
        "started_day",
        "completed_day",
        "progress_percent",
        "actual_cost",
    )
    list_filter = ("status", "run__plan_revision")
    search_fields = ("state_id", "run__run_id", "plan_node__code", "plan_node__title", "blocker_reason")
    list_select_related = ("run", "plan_node", "plan_node__revision")
    ordering = ("run", "plan_node__sequence", "plan_node__node_id")
    list_per_page = 100
    readonly_fields = model_field_names(PlanNodeRunState)


@admin.register(SimulationTurn)
class SimulationTurnAdmin(ImmutableHistoryAdminMixin, admin.ModelAdmin):
    list_display = ("turn_id", "run", "turn_number", "simulation_day", "occurred_at")
    list_filter = ("run__status", "simulation_day")
    search_fields = ("turn_id", "run__run_id", "summary")
    list_select_related = ("run",)
    date_hierarchy = "occurred_at"
    ordering = ("run", "turn_number")
    list_per_page = 100
    readonly_fields = model_field_names(SimulationTurn)


@admin.register(SimulationFailure)
class SimulationFailureAdmin(ImmutableHistoryAdminMixin, admin.ModelAdmin):
    list_display = ("failure_id", "run", "plan_node", "failure_type", "severity", "simulation_day", "detected_at")
    list_filter = ("failure_type", "severity", "run__plan_revision")
    search_fields = ("failure_id", "run__run_id", "plan_node__title", "title", "description")
    list_select_related = ("run", "plan_node")
    date_hierarchy = "detected_at"
    ordering = ("-detected_at", "failure_id")
    list_per_page = 100
    readonly_fields = model_field_names(SimulationFailure)
