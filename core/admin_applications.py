"""Django Admin configuration for public application records."""

from __future__ import annotations

from django.contrib import admin, messages

from core.access import member_for_user
from core.application_services import review_member_application
from core.exceptions import DomainError

from .admin_support import HiddenFromAdminIndexMixin, NoDeleteAdminMixin
from .models import MemberApplication, PartnerApplication


@admin.register(MemberApplication)
class MemberApplicationAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = (
        "application_id",
        "applicant_name",
        "status",
        "role_gap",
        "account_user",
        "can_issue_responsibility_documents",
        "linked_member",
        "admission_proposal",
        "submitted_at",
        "reviewed_at",
    )
    list_filter = ("status", "role_gap", "can_issue_responsibility_documents", "submitted_at")
    search_fields = (
        "application_id",
        "applicant_name",
        "contact",
        "requested_member_no",
        "account_user__username",
        "linked_member__member_no",
        "linked_member__display_name",
    )
    readonly_fields = (
        "status",
        "account_user",
        "linked_member",
        "admission_proposal",
        "frozen_at",
        "reviewed_by",
        "submitted_at",
        "reviewed_at",
    )
    ordering = ("-submitted_at", "application_id")
    list_per_page = 100
    actions = (
        "mark_under_review",
        "accept_as_candidate",
        "mark_standby",
        "reject_applications",
    )

    def _review_selected(self, request, queryset, *, status: str, note: str) -> None:
        reviewer = member_for_user(request.user)
        succeeded = 0
        failed: list[str] = []
        for application in queryset:
            try:
                review_member_application(
                    application=application,
                    status=status,
                    reviewed_by=reviewer,
                    review_note=note,
                )
            except DomainError as exc:
                failed.append(f"{application.application_id}: {exc}")
            else:
                succeeded += 1
        if succeeded:
            self.message_user(request, f"已处理 {succeeded} 条成员报名。", messages.SUCCESS)
        if failed:
            self.message_user(request, "；".join(failed), messages.WARNING)

    @admin.action(description="标记为审核中")
    def mark_under_review(self, request, queryset) -> None:
        self._review_selected(
            request,
            queryset,
            status=MemberApplication.Status.UNDER_REVIEW,
            note="后台标记为审核中。",
        )

    @admin.action(description="审核通过为候选成员")
    def accept_as_candidate(self, request, queryset) -> None:
        self._review_selected(
            request,
            queryset,
            status=MemberApplication.Status.CANDIDATE,
            note="后台审核通过为候选成员。",
        )

    @admin.action(description="标记为备用")
    def mark_standby(self, request, queryset) -> None:
        self._review_selected(
            request,
            queryset,
            status=MemberApplication.Status.STANDBY,
            note="后台标记为备用。",
        )

    @admin.action(description="拒绝成员报名")
    def reject_applications(self, request, queryset) -> None:
        self._review_selected(
            request,
            queryset,
            status=MemberApplication.Status.REJECTED,
            note="后台拒绝成员报名。",
        )


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
