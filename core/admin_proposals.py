"""统一提案、选民规则与实名票据的只读审计后台。"""

from django.contrib import admin

from .admin_support import ImmutableHistoryAdminMixin, model_field_names
from .models import (
    ApprovalProposal,
    ElectorateRuleTemplate,
    ElectorateRuleVersion,
    ProposalBallot,
    ProposalElectorSnapshot,
    ProposalExecutionRecord,
    ProposalResolution,
)


class _ReadOnlyProposalAdmin(ImmutableHistoryAdminMixin, admin.ModelAdmin):
    readonly_fields = ()

    def get_readonly_fields(self, request, obj=None):
        return model_field_names(self.model)


@admin.register(ApprovalProposal)
class ApprovalProposalAdmin(_ReadOnlyProposalAdmin):
    list_display = ("proposal_id", "proposal_type", "strategy_type", "status", "submitted_by", "submitted_at")
    list_filter = ("proposal_type", "strategy_type", "status")
    search_fields = ("proposal_id", "title", "submitted_by__member_no")


@admin.register(ElectorateRuleTemplate)
class ElectorateRuleTemplateAdmin(_ReadOnlyProposalAdmin):
    list_display = ("rule_code", "proposal_type", "name", "is_active", "created_by")


@admin.register(ElectorateRuleVersion)
class ElectorateRuleVersionAdmin(_ReadOnlyProposalAdmin):
    list_display = ("rule_version_id", "template", "version", "published_by", "published_at")


@admin.register(ProposalElectorSnapshot)
class ProposalElectorSnapshotAdmin(_ReadOnlyProposalAdmin):
    list_display = ("proposal", "member", "rule_version", "snapshotted_at")


@admin.register(ProposalBallot)
class ProposalBallotAdmin(_ReadOnlyProposalAdmin):
    list_display = ("ballot_id", "proposal", "voter", "revision", "choice", "submitted_at")


@admin.register(ProposalResolution)
class ProposalResolutionAdmin(_ReadOnlyProposalAdmin):
    list_display = ("proposal", "outcome", "reason_code", "decided_by", "decided_at")


@admin.register(ProposalExecutionRecord)
class ProposalExecutionRecordAdmin(_ReadOnlyProposalAdmin):
    list_display = ("execution_id", "proposal", "executed_by", "status", "completed_at")
