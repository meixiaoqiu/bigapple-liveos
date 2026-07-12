"""Django Admin configuration for public application records."""

from __future__ import annotations

from django.contrib import admin

from .admin_support import HiddenFromAdminIndexMixin, NoDeleteAdminMixin
from .models import MemberApplication, PartnerApplication


@admin.register(MemberApplication)
class MemberApplicationAdmin(HiddenFromAdminIndexMixin, NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = (
        "application_id",
        "applicant_name",
        "status",
        "availability_hours_per_week",
        "can_issue_responsibility_documents",
        "linked_member",
        "submitted_at",
        "reviewed_at",
    )
    list_filter = ("status", "can_issue_responsibility_documents", "submitted_at")
    search_fields = (
        "application_id",
        "applicant_name",
        "contact",
        "requested_member_no",
        "linked_member__member_no",
        "linked_member__display_name",
    )
    autocomplete_fields = ("linked_member", "reviewed_by")
    readonly_fields = ("submitted_at", "reviewed_at")
    ordering = ("-submitted_at", "application_id")
    list_per_page = 100


@admin.register(PartnerApplication)
class PartnerApplicationAdmin(HiddenFromAdminIndexMixin, NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = (
        "application_id",
        "organization_name",
        "contact_name",
        "status",
        "can_issue_responsibility_documents",
        "service_area",
        "submitted_at",
        "reviewed_at",
    )
    list_filter = ("status", "can_issue_responsibility_documents", "submitted_at")
    search_fields = (
        "application_id",
        "organization_name",
        "contact_name",
        "contact",
        "service_area",
        "qualification_summary",
    )
    autocomplete_fields = ("reviewed_by",)
    readonly_fields = ("submitted_at", "reviewed_at")
    ordering = ("-submitted_at", "application_id")
    list_per_page = 100
