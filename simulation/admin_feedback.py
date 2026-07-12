"""Django Admin configuration for simulation feedback and plan-change records."""

from __future__ import annotations

from django.contrib import admin

from core.admin_support import (
    ImmutableHistoryAdminMixin,
    NoDeleteAdminMixin,
    StablePrimaryKeyAdminMixin,
    model_field_names,
)
from core.models import PlanChangeOperation, PlanChangeSet, PlanRevisionProposal


@admin.register(PlanRevisionProposal)
class PlanRevisionProposalAdmin(StablePrimaryKeyAdminMixin, NoDeleteAdminMixin, admin.ModelAdmin):
    stable_primary_key = "proposal_id"
    list_display = ("proposal_id", "plan_revision", "plan_node", "proposal_type", "status", "created_at")
    list_filter = ("proposal_type", "status", "plan_revision")
    search_fields = ("proposal_id", "title", "rationale", "plan_node__title", "run__run_id")
    autocomplete_fields = ("run", "source_failure", "plan_revision", "plan_node")
    list_select_related = ("run", "source_failure", "plan_revision", "plan_node")
    date_hierarchy = "created_at"
    ordering = ("-created_at", "proposal_id")
    list_per_page = 100
    readonly_fields = ("proposal_id", "run", "source_failure", "plan_revision", "plan_node", "created_at")
    fieldsets = (
        ("建议身份", {"fields": ("proposal_id", "run", "source_failure", "plan_revision", "plan_node")}),
        ("审核", {"fields": ("proposal_type", "status", "title", "rationale", "suggested_changes")}),
        ("时间和扩展", {"fields": ("created_at", "metadata")}),
    )

    def has_add_permission(self, request):
        return False


class PlanChangeOperationInline(admin.TabularInline):
    model = PlanChangeOperation
    extra = 0
    fields = (
        "sequence",
        "operation_type",
        "target_model",
        "target_id",
        "target_field",
        "is_required",
        "rationale",
    )
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(PlanChangeSet)
class PlanChangeSetAdmin(StablePrimaryKeyAdminMixin, NoDeleteAdminMixin, admin.ModelAdmin):
    stable_primary_key = "change_set_id"
    list_display = ("change_set_id", "proposal", "plan_revision", "status", "created_at", "applied_at", "applied_revision")
    list_filter = ("status", "plan_revision")
    search_fields = ("change_set_id", "proposal__title", "title", "summary", "run__run_id")
    autocomplete_fields = ("proposal", "run", "plan_revision", "applied_revision")
    list_select_related = ("proposal", "run", "plan_revision", "applied_revision")
    date_hierarchy = "created_at"
    ordering = ("-created_at", "change_set_id")
    list_per_page = 100
    actions = None
    readonly_fields = (
        "change_set_id",
        "run",
        "proposal",
        "plan_revision",
        "title",
        "summary",
        "created_at",
        "reviewed_at",
        "applied_at",
        "applied_revision",
        "metadata",
    )
    inlines = (PlanChangeOperationInline,)
    fieldsets = (
        ("变更集身份", {"fields": ("change_set_id", "run", "proposal", "plan_revision")}),
        ("审核状态", {"fields": ("status", "title", "summary")}),
        ("应用结果", {"fields": ("applied_revision", "reviewed_at", "applied_at")}),
        ("时间和扩展", {"fields": ("created_at", "metadata")}),
    )

    def has_add_permission(self, request):
        return False


@admin.register(PlanChangeOperation)
class PlanChangeOperationAdmin(ImmutableHistoryAdminMixin, admin.ModelAdmin):
    list_display = (
        "operation_id",
        "change_set",
        "sequence",
        "operation_type",
        "target_model",
        "target_id",
        "target_field",
        "is_required",
    )
    list_filter = ("operation_type", "target_model", "is_required", "change_set__status")
    search_fields = ("operation_id", "change_set__change_set_id", "target_id", "target_field", "rationale")
    list_select_related = ("change_set",)
    ordering = ("change_set", "sequence", "operation_id")
    list_per_page = 100
    readonly_fields = model_field_names(PlanChangeOperation)
