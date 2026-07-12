"""Django Admin configuration for immutable history and audit records."""

from __future__ import annotations

from django.contrib import admin

from .admin_support import ImmutableHistoryAdminMixin, model_field_names
from .models import LedgerEntry, SystemEvent


@admin.register(LedgerEntry)
class LedgerEntryAdmin(ImmutableHistoryAdminMixin, admin.ModelAdmin):
    list_display = (
        "system_event_seq",
        "ledger_entry_id",
        "system_event",
        "member",
        "amount",
        "entry_type",
        "status",
        "related_task",
        "created_at",
    )
    list_filter = ("entry_type", "status", "rule_version")
    search_fields = ("ledger_entry_id", "member__member_no", "related_task__task_id", "system_event__event_hash")
    autocomplete_fields = ("member", "related_task", "reverses_entry", "system_event")
    list_select_related = ("member", "related_task", "reverses_entry", "system_event")
    date_hierarchy = "created_at"
    ordering = ("system_event__seq", "created_at", "ledger_entry_id")
    list_per_page = 50
    readonly_fields = model_field_names(LedgerEntry)

    @admin.display(description="事件序号", ordering="system_event__seq")
    def system_event_seq(self, obj: LedgerEntry) -> int | None:
        return obj.system_event.seq if obj.system_event_id else None


@admin.register(SystemEvent)
class SystemEventAdmin(ImmutableHistoryAdminMixin, admin.ModelAdmin):
    list_display = (
        "seq",
        "event_type",
        "aggregate_type",
        "aggregate_id",
        "actor_member",
        "actor_role_assignment",
        "occurred_at",
        "short_event_hash",
    )
    list_filter = ("event_type", "aggregate_type", "occurred_at")
    search_fields = (
        "event_type",
        "aggregate_type",
        "aggregate_id",
        "event_hash",
        "prev_hash",
        "actor_member__member_no",
        "actor_member__display_name",
    )
    autocomplete_fields = ("actor_member", "actor_role_assignment")
    list_select_related = ("actor_member", "actor_role_assignment")
    date_hierarchy = "occurred_at"
    ordering = ("seq",)
    list_per_page = 100
    readonly_fields = model_field_names(SystemEvent)

    @admin.display(description="事件哈希")
    def short_event_hash(self, obj: SystemEvent) -> str:
        return obj.event_hash[:12]
