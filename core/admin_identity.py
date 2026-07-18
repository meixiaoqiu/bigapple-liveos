"""Django Admin configuration for members, roles, and role-derived permissions."""

from __future__ import annotations

from django.contrib import admin
from django.utils import timezone

from .admin_support import (
    HiddenFromAdminIndexMixin,
    ImmutableHistoryAdminMixin,
    ImmutableHistoryInlineMixin,
    NoDeleteAdminMixin,
    NoDeleteInlineMixin,
    StablePrimaryKeyAdminMixin,
    model_field_names,
)
from .models import CredentialGrant, CredentialTemplate, Member, MemberPublicProfile, Organization, Permission, Role, RoleAssignment, RolePermission


class ActiveRoleListFilter(admin.SimpleListFilter):
    title = "当前角色"
    parameter_name = "active_role"

    def lookups(self, request, model_admin):
        return tuple((str(role.pk), str(role)) for role in Role.objects.order_by("organization__name", "name"))

    def queryset(self, request, queryset):
        if not self.value():
            return queryset
        checked_at = timezone.now()
        return queryset.filter(
            role_assignments__role_id=self.value(),
            role_assignments__status=RoleAssignment.Status.ACTIVE,
            role_assignments__start_at__lte=checked_at,
            role_assignments__end_at__gte=checked_at,
        ).distinct()


class OrganizationRoleInline(NoDeleteInlineMixin, admin.TabularInline):
    model = Role
    extra = 0
    fields = ("name", "status", "description", "created_at", "updated_at")
    readonly_fields = ("created_at", "updated_at")
    show_change_link = True


class MemberRoleAssignmentInline(NoDeleteInlineMixin, admin.TabularInline):
    model = RoleAssignment
    fk_name = "member"
    extra = 0
    fields = (
        "role",
        "status",
        "source_type",
        "source_proposal",
        "source_proposal_execution",
        "start_at",
        "end_at",
        "granted_by",
        "revoked_by",
        "created_at",
        "updated_at",
    )
    autocomplete_fields = ("role", "source_proposal", "source_proposal_execution", "granted_by", "revoked_by")
    readonly_fields = (
        "role", "status", "source_type", "source_proposal", "source_proposal_execution",
        "start_at", "end_at", "granted_by", "revoked_by", "created_at", "updated_at",
    )
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


class RolePermissionInline(ImmutableHistoryInlineMixin, admin.TabularInline):
    model = RolePermission
    extra = 0
    fields = ("permission", "scope", "constraints_json", "created_at", "updated_at")
    autocomplete_fields = ("permission",)
    readonly_fields = ("created_at", "updated_at")
    show_change_link = True


class RoleAssignmentInline(NoDeleteInlineMixin, admin.TabularInline):
    model = RoleAssignment
    fk_name = "role"
    extra = 0
    fields = (
        "member",
        "status",
        "source_type",
        "source_proposal",
        "source_proposal_execution",
        "start_at",
        "end_at",
        "granted_by",
        "revoked_by",
        "created_at",
        "updated_at",
    )
    autocomplete_fields = ("member", "source_proposal", "source_proposal_execution", "granted_by", "revoked_by")
    readonly_fields = (
        "member", "status", "source_type", "source_proposal", "source_proposal_execution",
        "start_at", "end_at", "granted_by", "revoked_by", "created_at", "updated_at",
    )
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


class MemberPublicProfileInline(NoDeleteInlineMixin, admin.StackedInline):
    model = MemberPublicProfile
    extra = 0
    max_num = 1
    fields = ("public_name", "avatar_url", "bio", "is_visible", "created_at", "updated_at")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Member)
class MemberAdmin(StablePrimaryKeyAdminMixin, NoDeleteAdminMixin, admin.ModelAdmin):
    stable_primary_key = "member_no"
    list_display = (
        "member_no",
        "display_name",
        "user",
        "active_roles",
        "status",
        "batch_id",
        "joined_simulation_day",
        "credit_floor",
        "created_at",
    )
    list_filter = (ActiveRoleListFilter, "status")
    search_fields = (
        "member_no",
        "display_name",
        "user__username",
        "user__email",
        "batch_id",
        "role_assignments__role__name",
        "role_assignments__role__organization__name",
    )
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    inlines = (MemberPublicProfileInline, MemberRoleAssignmentInline,)
    ordering = ("member_no",)
    list_per_page = 50
    readonly_fields = ("created_at",)
    fieldsets = (
        ("身份", {"fields": ("member_no", "display_name", "user", "status", "batch_id")}),
        ("准入和积分边界", {"fields": ("joined_simulation_day", "credit_floor")}),
        ("模拟画像", {"fields": ("profile", "metadata")}),
        ("时间", {"fields": ("created_at",)}),
    )

    @admin.display(description="当前角色")
    def active_roles(self, obj: Member) -> str:
        return obj.active_roles_display


@admin.register(Organization)
class OrganizationAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("name", "parent", "status", "created_at", "updated_at")
    list_filter = ("status",)
    search_fields = ("name", "parent__name")
    autocomplete_fields = ("parent",)
    list_select_related = ("parent",)
    inlines = (OrganizationRoleInline,)
    ordering = ("name",)
    list_per_page = 50
    readonly_fields = ("created_at", "updated_at")


@admin.register(Role)
class RoleAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = (
        "name",
        "organization",
        "status",
        "appointment_electorate_role",
        "appointment_required_percent",
        "role_permission_count",
        "created_at",
        "updated_at",
    )
    list_filter = ("organization", "status")
    search_fields = ("name", "description", "organization__name", "appointment_electorate_role__name")
    autocomplete_fields = ("organization", "appointment_electorate_role")
    list_select_related = ("organization", "appointment_electorate_role")
    inlines = (RolePermissionInline, RoleAssignmentInline)
    ordering = ("organization", "name")
    list_per_page = 50
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="权限数")
    def role_permission_count(self, obj: Role) -> int:
        return obj.role_permissions.count()


@admin.register(Permission)
class PermissionAdmin(HiddenFromAdminIndexMixin, NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("code", "name", "category", "created_at", "updated_at")
    list_filter = ("category",)
    search_fields = ("code", "name", "category", "description")
    ordering = ("category", "code")
    list_per_page = 100
    readonly_fields = ("created_at", "updated_at")


@admin.register(RoleAssignment)
class RoleAssignmentAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("member", "role", "status", "source_type", "start_at", "end_at", "granted_by", "revoked_by")
    list_filter = ("status", "source_type", "role__organization")
    search_fields = (
        "member__member_no",
        "member__display_name",
        "role__name",
        "role__organization__name",
        "granted_by__display_name",
        "source_proposal__proposal_no",
        "source_proposal__title",
    )
    autocomplete_fields = ("member", "role", "source_proposal", "source_proposal_execution", "granted_by", "revoked_by")
    list_select_related = (
        "member",
        "role",
        "role__organization",
        "source_proposal",
        "source_proposal_execution",
        "granted_by",
        "revoked_by",
    )
    date_hierarchy = "start_at"
    ordering = ("-start_at", "member__member_no")
    list_per_page = 100
    readonly_fields = (
        "member", "role", "status", "source_type", "source_proposal",
        "source_proposal_execution", "start_at", "end_at", "granted_by",
        "revoked_by", "created_at", "updated_at",
    )

    def has_add_permission(self, request):
        return False


@admin.register(RolePermission)
class RolePermissionAdmin(HiddenFromAdminIndexMixin, ImmutableHistoryAdminMixin, admin.ModelAdmin):
    list_display = ("role", "permission", "scope", "created_at", "updated_at")
    list_filter = ("scope", "permission__category", "role__organization")
    search_fields = ("role__name", "role__organization__name", "permission__code", "permission__name")
    autocomplete_fields = ("role", "permission")
    list_select_related = ("role", "role__organization", "permission")
    ordering = ("role__organization", "role__name", "permission__code")
    list_per_page = 100
    readonly_fields = model_field_names(RolePermission)


@admin.register(MemberPublicProfile)
class MemberPublicProfileAdmin(HiddenFromAdminIndexMixin, NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("member", "public_name", "is_visible", "updated_at")
    list_filter = ("is_visible",)
    search_fields = ("member__member_no", "member__display_name", "public_name", "bio")
    autocomplete_fields = ("member",)
    list_select_related = ("member",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(CredentialTemplate)
class CredentialTemplateAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("code", "name", "credential_type", "status", "display_order")
    list_filter = ("status", "credential_type")
    search_fields = ("code", "name", "description")
    readonly_fields = model_field_names(CredentialTemplate)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        if obj is not None:
            return False
        return super().has_change_permission(request, obj)


@admin.register(CredentialGrant)
class CredentialGrantAdmin(admin.ModelAdmin):
    list_display = ("grant_id", "template", "member", "display_no", "status", "source_type", "issued_at")
    list_filter = ("template", "status", "source_type")
    search_fields = (
        "grant_id", "display_no", "template__code", "template__name",
        "member__member_no", "member__display_name",
    )
    list_select_related = ("template", "member")
    readonly_fields = (
        "grant_id", "template", "member", "serial_no", "display_no", "title",
        "status", "issued_at", "issued_by", "source_type", "source_proposal",
        "source_proposal_execution", "metadata", "created_at", "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
