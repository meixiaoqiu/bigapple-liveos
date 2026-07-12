"""Django Admin configuration for operational maintenance models."""

from __future__ import annotations

from django.contrib import admin

from .admin_support import ImmutableHistoryAdminMixin, NoDeleteAdminMixin, StablePrimaryKeyAdminMixin
from .models import Dispute, Resource, ResourceTransaction, SupplierQuote, Task


@admin.register(Task)
class TaskAdmin(StablePrimaryKeyAdminMixin, NoDeleteAdminMixin, admin.ModelAdmin):
    stable_primary_key = "task_id"
    list_display = (
        "task_id",
        "title",
        "task_type",
        "status",
        "source_type",
        "assignee_member",
        "requires_review",
        "failure_consequence",
        "due_at",
        "rule_version",
    )
    list_filter = ("task_type", "status", "source_type", "requires_review", "failure_consequence", "rule_version")
    search_fields = (
        "task_id",
        "title",
        "assignee_member__member_no",
        "plan_node__title",
        "plan_node__code",
        "source_proposal__proposal_no",
        "source_proposal__title",
    )
    autocomplete_fields = ("assignee_member", "plan_node", "source_proposal", "source_proposal_execution")
    list_select_related = ("assignee_member", "plan_node", "source_proposal", "source_proposal_execution")
    date_hierarchy = "created_at"
    ordering = ("status", "due_at", "task_id")
    list_per_page = 50
    readonly_fields = ("created_at", "submitted_at", "reviewed_at")
    fieldsets = (
        ("任务身份", {"fields": ("task_id", "title", "task_type", "status")}),
        (
            "积分和负担",
            {
                "fields": (
                    "standard_hours",
                    "base_points",
                    "role_coefficient",
                    "physical_load",
                    "dirty_level",
                    "psychological_load",
                    "urgency",
                )
            },
        ),
        (
            "执行和验收",
            {
                "fields": (
                    "assignee_member",
                    "plan_node",
                    "can_be_delayed",
                    "requires_review",
                    "failure_consequence",
                    "due_at",
                    "submitted_at",
                    "reviewed_at",
                )
            },
        ),
        ("来源", {"fields": ("source_type", "source_proposal", "source_proposal_execution")}),
        ("规则和扩展", {"fields": ("rule_version", "metadata")}),
        ("时间", {"fields": ("created_at",)}),
    )


@admin.register(Resource)
class ResourceAdmin(StablePrimaryKeyAdminMixin, NoDeleteAdminMixin, admin.ModelAdmin):
    stable_primary_key = "resource_id"
    list_display = (
        "resource_id",
        "name",
        "resource_type",
        "status",
        "location",
        "stock_status",
        "current_stock",
        "unit",
        "daily_consumption_estimate",
        "warning_threshold",
        "replenishment_method",
        "updated_at",
    )
    list_filter = ("resource_type", "status", "unit", "replenishment_method", "rule_version")
    search_fields = ("resource_id", "name", "location", "description")
    date_hierarchy = "updated_at"
    ordering = ("resource_type", "resource_id")
    list_per_page = 50
    readonly_fields = ("updated_at",)
    fieldsets = (
        ("资源身份", {"fields": ("resource_id", "name", "resource_type", "status", "location", "description", "unit")}),
        (
            "库存状态",
            {"fields": ("current_stock", "daily_consumption_estimate", "warning_threshold", "loss_rate")},
        ),
        ("补充和影响", {"fields": ("replenishment_method", "shortage_impact")}),
        ("规则和扩展", {"fields": ("rule_version", "metadata")}),
        ("时间", {"fields": ("updated_at",)}),
    )

    @admin.display(description="库存状态", ordering="current_stock")
    def stock_status(self, obj: Resource) -> str:
        return "低于预警" if obj.current_stock <= obj.warning_threshold else "正常"


@admin.register(SupplierQuote)
class SupplierQuoteAdmin(StablePrimaryKeyAdminMixin, NoDeleteAdminMixin, admin.ModelAdmin):
    stable_primary_key = "quote_id"
    list_display = (
        "quote_id",
        "partner_application",
        "resource",
        "status",
        "unit_price",
        "currency",
        "available_quantity",
        "lead_time_days",
        "quality_grade",
        "valid_until",
    )
    list_filter = (
        "status",
        "resource__resource_type",
        "quality_grade",
        "partner_application__status",
        "valid_until",
    )
    search_fields = (
        "quote_id",
        "partner_application__organization_name",
        "partner_application__contact_name",
        "resource__resource_id",
        "resource__name",
        "quality_summary",
        "notes",
    )
    autocomplete_fields = ("partner_application", "resource")
    list_select_related = ("partner_application", "resource")
    date_hierarchy = "created_at"
    ordering = ("resource", "unit_price", "lead_time_days", "quote_id")
    list_per_page = 50
    readonly_fields = ("created_at",)
    fieldsets = (
        ("报价身份", {"fields": ("quote_id", "partner_application", "resource", "status")}),
        (
            "价格和供给",
            {
                "fields": (
                    "unit_price",
                    "currency",
                    "available_quantity",
                    "minimum_order_quantity",
                    "lead_time_days",
                )
            },
        ),
        ("质量和有效期", {"fields": ("quality_grade", "quality_summary", "valid_from", "valid_until")}),
        ("说明", {"fields": ("notes", "metadata")}),
        ("时间", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(ResourceTransaction)
class ResourceTransactionAdmin(ImmutableHistoryAdminMixin, admin.ModelAdmin):
    list_display = (
        "transaction_id",
        "resource",
        "transaction_type",
        "quantity_delta",
        "stock_before",
        "stock_after",
        "occurred_at",
        "system_event",
    )
    list_filter = ("transaction_type", "resource__resource_type", "occurred_at")
    search_fields = (
        "transaction_id",
        "resource__resource_id",
        "resource__name",
        "reason",
        "system_event__event_hash",
    )
    autocomplete_fields = ("resource", "related_task", "related_supplier_quote", "system_event")
    list_select_related = ("resource", "related_task", "related_supplier_quote", "system_event")
    date_hierarchy = "occurred_at"
    ordering = ("-occurred_at", "transaction_id")
    list_per_page = 50
    readonly_fields = (
        "transaction_id",
        "resource",
        "transaction_type",
        "quantity_delta",
        "stock_before",
        "stock_after",
        "reason",
        "operator",
        "related_task",
        "related_supplier_quote",
        "system_event",
        "occurred_at",
        "created_at",
        "metadata",
    )
    fieldsets = (
        ("流水身份", {"fields": ("transaction_id", "resource", "transaction_type")}),
        ("库存变化", {"fields": ("quantity_delta", "stock_before", "stock_after", "reason")}),
        ("关联对象", {"fields": ("operator", "related_task", "related_supplier_quote", "system_event")}),
        ("时间和扩展", {"fields": ("occurred_at", "created_at", "metadata")}),
    )

@admin.register(Dispute)
class DisputeAdmin(StablePrimaryKeyAdminMixin, NoDeleteAdminMixin, admin.ModelAdmin):
    stable_primary_key = "dispute_id"
    list_display = (
        "dispute_id",
        "dispute_type",
        "status",
        "claimant_member",
        "respondent_member",
        "related_task",
        "submitted_at",
        "resolved_at",
    )
    list_filter = ("dispute_type", "status")
    search_fields = ("dispute_id", "claimant_member__member_no", "facts")
    autocomplete_fields = ("claimant_member", "respondent_member", "related_task", "related_ledger_entry")
    list_select_related = ("claimant_member", "respondent_member", "related_task", "related_ledger_entry")
    date_hierarchy = "submitted_at"
    ordering = ("status", "-submitted_at", "dispute_id")
    list_per_page = 50
    readonly_fields = ("submitted_at",)
    fieldsets = (
        ("申诉身份", {"fields": ("dispute_id", "dispute_type", "status")}),
        ("当事人", {"fields": ("claimant_member", "respondent_member")}),
        ("关联对象", {"fields": ("related_task", "related_ledger_entry")}),
        ("事实和证据", {"fields": ("facts", "evidence_refs")}),
        ("处理", {"fields": ("handler", "reviewer", "resolution", "appeal_path", "resolved_at")}),
        ("时间和扩展", {"fields": ("submitted_at", "metadata")}),
    )
