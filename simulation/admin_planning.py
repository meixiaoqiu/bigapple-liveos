"""Django Admin configuration for project plan authority records."""

from __future__ import annotations

from django.contrib import admin

from core.admin_support import NoDeleteAdminMixin, StablePrimaryKeyAdminMixin
from core.models import (
    PlanCapacityImpact,
    PlanDependency,
    PlanNode,
    PlanRequirement,
    PlanRevision,
    ProjectPlan,
)


class PlanRequirementInline(admin.TabularInline):
    model = PlanRequirement
    extra = 0
    fields = (
        "requirement_type",
        "name",
        "quantity",
        "unit",
        "unit_cost",
        "total_cost_estimate",
        "is_must",
        "notes",
    )


class PlanCapacityImpactInline(admin.TabularInline):
    model = PlanCapacityImpact
    extra = 0
    fields = ("impact_type", "delta", "unit", "description")


@admin.register(ProjectPlan)
class ProjectPlanAdmin(StablePrimaryKeyAdminMixin, NoDeleteAdminMixin, admin.ModelAdmin):
    stable_primary_key = "plan_id"
    list_display = ("plan_id", "name", "status", "target_location", "created_at", "updated_at")
    list_filter = ("status",)
    search_fields = ("plan_id", "name", "target_location", "description")
    date_hierarchy = "created_at"
    ordering = ("status", "plan_id")
    list_per_page = 50
    readonly_fields = ("updated_at",)
    fieldsets = (
        ("计划身份", {"fields": ("plan_id", "name", "status", "target_location")}),
        ("说明和责任", {"fields": ("description", "owner")}),
        ("时间和扩展", {"fields": ("created_at", "updated_at", "metadata")}),
    )


@admin.register(PlanRevision)
class PlanRevisionAdmin(StablePrimaryKeyAdminMixin, NoDeleteAdminMixin, admin.ModelAdmin):
    stable_primary_key = "revision_id"
    list_display = ("revision_id", "plan", "revision_code", "status", "title", "created_at", "published_at")
    list_filter = ("status", "plan")
    search_fields = ("revision_id", "revision_code", "title", "plan__name", "change_summary")
    autocomplete_fields = ("plan",)
    list_select_related = ("plan",)
    date_hierarchy = "created_at"
    ordering = ("plan", "-created_at", "revision_code")
    list_per_page = 50
    fieldsets = (
        ("版本身份", {"fields": ("revision_id", "plan", "revision_code", "status", "title")}),
        ("变更", {"fields": ("change_summary", "created_by")}),
        ("时间和扩展", {"fields": ("created_at", "published_at", "metadata")}),
    )


@admin.register(PlanNode)
class PlanNodeAdmin(StablePrimaryKeyAdminMixin, NoDeleteAdminMixin, admin.ModelAdmin):
    stable_primary_key = "node_id"
    list_display = (
        "sequence",
        "code",
        "title",
        "revision",
        "parent",
        "node_type",
        "status",
        "is_required",
        "planned_start_day",
        "planned_end_day",
        "estimated_cost_expected",
    )
    list_filter = ("revision", "node_type", "status", "is_required", "is_expandable")
    search_fields = ("node_id", "code", "title", "description", "revision__revision_code", "revision__plan__name")
    autocomplete_fields = ("revision", "parent")
    list_select_related = ("revision", "revision__plan", "parent")
    ordering = ("revision", "sequence", "node_id")
    list_per_page = 100
    readonly_fields = ("updated_at",)
    inlines = (PlanRequirementInline, PlanCapacityImpactInline)
    fieldsets = (
        ("节点身份", {"fields": ("node_id", "revision", "parent", "sequence", "code", "title")}),
        ("节点属性", {"fields": ("node_type", "status", "is_required", "is_expandable", "allow_simulation_adjustment")}),
        ("计划时间", {"fields": ("planned_start_day", "planned_duration_days", "planned_end_day")}),
        (
            "成本和人力",
            {
                "fields": (
                    "estimated_cost_low",
                    "estimated_cost_expected",
                    "estimated_cost_high",
                    "required_people_min",
                    "required_people_max",
                    "required_person_days",
                    "required_skills",
                    "required_resources",
                )
            },
        ),
        ("完成和风险", {"fields": ("completion_criteria", "risk_notes", "description")}),
        ("时间和扩展", {"fields": ("created_at", "updated_at", "metadata")}),
    )


@admin.register(PlanDependency)
class PlanDependencyAdmin(StablePrimaryKeyAdminMixin, NoDeleteAdminMixin, admin.ModelAdmin):
    stable_primary_key = "dependency_id"
    list_display = ("dependency_id", "revision", "depends_on", "node", "dependency_type")
    list_filter = ("revision", "dependency_type")
    search_fields = ("dependency_id", "node__title", "depends_on__title", "description")
    autocomplete_fields = ("revision", "node", "depends_on")
    list_select_related = ("revision", "node", "depends_on")
    ordering = ("revision", "dependency_id")
    list_per_page = 100
    fieldsets = (
        ("依赖身份", {"fields": ("dependency_id", "revision", "depends_on", "node", "dependency_type")}),
        ("说明", {"fields": ("description", "metadata")}),
    )


@admin.register(PlanRequirement)
class PlanRequirementAdmin(StablePrimaryKeyAdminMixin, NoDeleteAdminMixin, admin.ModelAdmin):
    stable_primary_key = "requirement_id"
    list_display = (
        "requirement_id",
        "node",
        "requirement_type",
        "name",
        "quantity",
        "unit",
        "total_cost_estimate",
        "is_must",
    )
    list_filter = ("requirement_type", "is_must", "node__revision")
    search_fields = ("requirement_id", "node__title", "name", "notes")
    autocomplete_fields = ("node",)
    list_select_related = ("node", "node__revision")
    ordering = ("node", "requirement_type", "requirement_id")
    list_per_page = 100


@admin.register(PlanCapacityImpact)
class PlanCapacityImpactAdmin(StablePrimaryKeyAdminMixin, NoDeleteAdminMixin, admin.ModelAdmin):
    stable_primary_key = "impact_id"
    list_display = ("impact_id", "node", "impact_type", "delta", "unit")
    list_filter = ("impact_type", "node__revision")
    search_fields = ("impact_id", "node__title", "description")
    autocomplete_fields = ("node",)
    list_select_related = ("node", "node__revision")
    ordering = ("node", "impact_type", "impact_id")
    list_per_page = 100
