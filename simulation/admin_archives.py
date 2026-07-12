"""Django Admin configuration for simulation archives."""

from __future__ import annotations

from django.contrib import admin

from core.admin_support import ImmutableHistoryAdminMixin, model_field_names
from core.models import SimulationRunDisposition, SimulationSnapshot, SimulationSnapshotItem
from simulation.snapshot_display import raw_plan_node_title_map, snapshot_item_title, source_model_label


class SimulationSnapshotItemInline(admin.TabularInline):
    model = SimulationSnapshotItem
    extra = 0
    fields = ("sort_order", "item_type", "display_source_model", "source_pk", "display_title")
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="来源类型")
    def display_source_model(self, obj: SimulationSnapshotItem) -> str:
        return source_model_label(obj.source_model)

    @admin.display(description="标题")
    def display_title(self, obj: SimulationSnapshotItem) -> str:
        return snapshot_item_title(obj, node_title_map=raw_plan_node_title_map(obj.snapshot))


@admin.register(SimulationSnapshot)
class SimulationSnapshotAdmin(ImmutableHistoryAdminMixin, admin.ModelAdmin):
    list_display = (
        "snapshot_id",
        "simulation_round",
        "scenario",
        "source_world_id",
        "source_run_id",
        "run_status",
        "failure_type",
        "publication_status",
        "archived_at",
    )
    list_filter = ("source_world_id", "scenario", "publication_status", "run_status", "failure_type", "archived_at")
    search_fields = (
        "snapshot_id",
        "source_run_id",
        "title",
        "public_title",
        "public_summary",
        "failure_title",
        "raw_archive_hash",
    )
    date_hierarchy = "archived_at"
    ordering = ("-archived_at", "snapshot_id")
    list_per_page = 100
    readonly_fields = model_field_names(SimulationSnapshot)
    inlines = (SimulationSnapshotItemInline,)


@admin.register(SimulationRunDisposition)
class SimulationRunDispositionAdmin(ImmutableHistoryAdminMixin, admin.ModelAdmin):
    list_display = (
        "source_world_id",
        "simulation_round",
        "source_run_id",
        "disposition",
        "scenario",
        "decided_by",
        "decided_at",
        "snapshot",
    )
    list_filter = ("source_world_id", "disposition", "scenario", "decided_at")
    search_fields = ("disposition_id", "source_run_id", "reason", "decided_by", "snapshot__snapshot_id")
    list_select_related = ("snapshot",)
    date_hierarchy = "decided_at"
    ordering = ("-decided_at", "source_world_id", "simulation_round")
    list_per_page = 100
    readonly_fields = model_field_names(SimulationRunDisposition)


@admin.register(SimulationSnapshotItem)
class SimulationSnapshotItemAdmin(ImmutableHistoryAdminMixin, admin.ModelAdmin):
    list_display = (
        "sort_order",
        "item_type",
        "display_source_model",
        "display_title",
        "source_pk",
        "snapshot",
    )
    list_filter = ("item_type", "source_model")
    search_fields = ("item_id", "snapshot__snapshot_id", "source_pk", "title", "summary")
    list_select_related = ("snapshot",)
    ordering = ("snapshot", "sort_order", "item_id")
    list_per_page = 100
    readonly_fields = model_field_names(SimulationSnapshotItem)

    @admin.display(description="来源类型", ordering="source_model")
    def display_source_model(self, obj: SimulationSnapshotItem) -> str:
        return source_model_label(obj.source_model)

    @admin.display(description="标题", ordering="title")
    def display_title(self, obj: SimulationSnapshotItem) -> str:
        return snapshot_item_title(obj, node_title_map=raw_plan_node_title_map(obj.snapshot))
