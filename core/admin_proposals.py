"""Django Admin configuration for generic governance proposals."""

from __future__ import annotations

from django import forms
from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.urls import path
from django.utils import timezone

from .admin_support import (
    HiddenFromAdminIndexMixin,
    ImmutableHistoryAdminMixin,
    ImmutableHistoryInlineMixin,
    NoDeleteAdminMixin,
    model_field_names,
)
from .models import (
    ElectorateRuleTemplate,
    ElectorateRuleVersion,
    Proposal,
    ProposalExecution,
    ProposalTypeElectorateRule,
    ProposalVote,
    Role,
    RoleAssignment,
)


class ProposalVoteInline(ImmutableHistoryInlineMixin, admin.TabularInline):
    model = ProposalVote
    extra = 0
    fields = ("voter_member", "voter_role_assignment", "choice", "reason", "voted_at", "created_at", "updated_at")
    autocomplete_fields = ("voter_member", "voter_role_assignment")
    readonly_fields = model_field_names(ProposalVote)
    show_change_link = True


class ProposalExecutionInline(ImmutableHistoryInlineMixin, admin.TabularInline):
    model = ProposalExecution
    extra = 0
    fields = ("action_type", "status", "executor_member", "executor_role_assignment", "executed_at")
    autocomplete_fields = ("executor_member", "executor_role_assignment")
    readonly_fields = model_field_names(ProposalExecution)
    show_change_link = True


class ProposalAdminForm(forms.ModelForm):
    class Meta:
        model = Proposal
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields.get("proposer_role_assignment")
        if field is None:
            return
        field.label = "提案时角色身份"
        field.help_text = "先选择提案人；这里只能选择该提案人拥有的角色任命。"
        field.queryset = self.proposer_role_assignment_queryset()
        field.widget.attrs["data-role-assignment-options-url"] = "/admin/core/proposal/role-assignment-options/"

    def selected_proposer_member_pk(self):
        if self.data:
            return self.data.get(self.add_prefix("proposer_member")) or self.data.get("proposer_member")
        if self.initial.get("proposer_member"):
            return self.initial["proposer_member"]
        if self.instance and self.instance.proposer_member_id:
            return self.instance.proposer_member_id
        if self.instance and self.instance.proposer_role_assignment_id:
            return self.instance.proposer_role_assignment.member_id
        return None

    def proposer_role_assignment_queryset(self):
        checked_at = timezone.now()
        queryset = RoleAssignment.objects.select_related("member", "role", "role__organization").order_by(
            "-start_at",
            "id",
        ).filter(
            status=RoleAssignment.Status.ACTIVE,
            role__status=Role.Status.ACTIVE,
            start_at__lte=checked_at,
            end_at__gte=checked_at,
        )
        member_pk = self.selected_proposer_member_pk()
        if not member_pk:
            return queryset.none()
        return queryset.filter(member_id=member_pk)

    def clean(self):
        cleaned_data = super().clean()
        proposer_member = cleaned_data.get("proposer_member")
        proposer_role_assignment = cleaned_data.get("proposer_role_assignment")
        if proposer_role_assignment and not proposer_member:
            self.add_error("proposer_role_assignment", "选择提案时角色身份前必须先选择提案人。")
        if proposer_member and proposer_role_assignment and proposer_role_assignment.member_id != proposer_member.pk:
            self.add_error("proposer_role_assignment", "提案时角色身份必须属于当前提案人。")
        rule_version = cleaned_data.get("electorate_rule_version")
        proposal_type = cleaned_data.get("proposal_type")
        professional_domain = cleaned_data.get("professional_domain")
        if rule_version and proposal_type:
            from .electorate_rules import rule_snapshot_for_proposal

            parameters = (
                {"professional_domain": professional_domain.code}
                if professional_domain is not None
                else {}
            )
            try:
                self.instance.electorate_rule_snapshot_json = rule_snapshot_for_proposal(
                    proposal_type=proposal_type,
                    rule_version=rule_version,
                    parameters=parameters,
                )
            except ValidationError as exc:
                self.add_error("electorate_rule_version", exc)
        return cleaned_data


@admin.register(Proposal)
class ProposalAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    form = ProposalAdminForm
    list_display = (
        "proposal_no",
        "title",
        "proposal_type",
        "electorate_rule_version",
        "professional_domain",
        "status",
        "proposer_member",
        "organization",
        "deadline_at",
        "created_at",
    )
    list_filter = ("proposal_type", "electorate_rule_version__template", "professional_domain", "status", "organization", "deadline_at")
    search_fields = (
        "proposal_no",
        "title",
        "body",
        "proposer_member__member_no",
        "proposer_member__display_name",
    )
    autocomplete_fields = (
        "proposer_member",
        "organization",
        "professional_domain",
        "electorate_rule_version",
    )
    list_select_related = (
        "proposer_member",
        "proposer_role_assignment",
        "organization",
        "professional_domain",
        "electorate_rule_version__template",
    )
    inlines = (ProposalVoteInline, ProposalExecutionInline)
    date_hierarchy = "deadline_at"
    ordering = ("status", "deadline_at", "proposal_no")
    list_per_page = 100
    readonly_fields = (
        "proposal_no",
        "eligible_voters_snapshot_json",
        "electorate_rule_snapshot_json",
        "result_json",
        "passed_at",
        "failed_at",
        "cancelled_at",
        "executed_at",
        "created_at",
        "updated_at",
    )

    class Media:
        js = ("core/admin/proposal_role_assignment_filter.js",)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "role-assignment-options/",
                self.admin_site.admin_view(self.role_assignment_options),
                name="core_proposal_role_assignment_options",
            ),
        ]
        return custom_urls + urls

    def has_change_permission(self, request, obj=None):
        if obj is not None:
            return False
        return super().has_change_permission(request, obj)

    def role_assignment_options(self, request):
        if not self.has_view_or_change_permission(request):
            raise PermissionDenied
        member_pk = request.GET.get("member_pk", "").strip()
        assignments = RoleAssignment.objects.none()
        if member_pk:
            checked_at = timezone.now()
            assignments = (
                RoleAssignment.objects.filter(member_id=member_pk)
                .select_related("member", "role", "role__organization")
                .filter(
                    status=RoleAssignment.Status.ACTIVE,
                    role__status=Role.Status.ACTIVE,
                    start_at__lte=checked_at,
                    end_at__gte=checked_at,
                )
                .order_by("-start_at", "id")
            )
        return JsonResponse(
            {
                "results": [
                    {
                        "id": assignment.pk,
                        "text": str(assignment),
                    }
                    for assignment in assignments
                ]
            }
        )


@admin.register(ProposalVote)
class ProposalVoteAdmin(HiddenFromAdminIndexMixin, ImmutableHistoryAdminMixin, admin.ModelAdmin):
    list_display = ("proposal", "voter_member", "choice", "voter_role_assignment", "voted_at", "created_at", "updated_at")
    list_filter = ("choice", "proposal__status", "proposal__proposal_type")
    search_fields = (
        "proposal__proposal_no",
        "proposal__title",
        "voter_member__member_no",
        "voter_member__display_name",
    )
    autocomplete_fields = ("proposal", "voter_member", "voter_role_assignment")
    list_select_related = ("proposal", "voter_member", "voter_role_assignment")
    readonly_fields = model_field_names(ProposalVote)


@admin.register(ProposalExecution)
class ProposalExecutionAdmin(HiddenFromAdminIndexMixin, ImmutableHistoryAdminMixin, admin.ModelAdmin):
    list_display = ("proposal", "action_type", "status", "executor_member", "executed_at")
    list_filter = ("action_type", "status", "proposal__proposal_type")
    search_fields = (
        "proposal__proposal_no",
        "proposal__title",
        "executor_member__member_no",
        "executor_member__display_name",
        "error_message",
    )
    autocomplete_fields = ("proposal", "executor_member", "executor_role_assignment")
    list_select_related = ("proposal", "executor_member", "executor_role_assignment")
    readonly_fields = model_field_names(ProposalExecution)


@admin.register(ElectorateRuleTemplate)
class ElectorateRuleTemplateAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("code", "name", "status", "updated_at")
    list_filter = ("status",)
    search_fields = ("code", "name")


@admin.register(ElectorateRuleVersion)
class ElectorateRuleVersionAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("template", "version", "created_at")
    list_filter = ("template",)
    search_fields = ("template__code", "template__name")
    readonly_fields = model_field_names(ElectorateRuleVersion)


@admin.register(ProposalTypeElectorateRule)
class ProposalTypeElectorateRuleAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("proposal_type", "template", "created_at")
    list_filter = ("proposal_type", "template")
    readonly_fields = model_field_names(ProposalTypeElectorateRule)
