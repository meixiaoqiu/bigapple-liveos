"""Read-only Django Admin configuration for finance records."""

from __future__ import annotations

from django.contrib import admin

from .admin_support import ImmutableHistoryAdminMixin, model_field_names
from .models import ExpenseClaim, FinanceReview, FinanceTransaction


@admin.register(ExpenseClaim)
class ExpenseClaimAdmin(ImmutableHistoryAdminMixin, admin.ModelAdmin):
    list_display = ("claim_id", "title", "claimant_member", "amount", "currency", "status", "created_at")
    list_filter = ("status", "category", "currency", "created_at")
    search_fields = ("claim_id", "title", "claimant_member__member_no", "vendor")
    list_select_related = ("claimant_member",)
    date_hierarchy = "created_at"
    readonly_fields = model_field_names(ExpenseClaim)


@admin.register(FinanceReview)
class FinanceReviewAdmin(ImmutableHistoryAdminMixin, admin.ModelAdmin):
    list_display = ("review_id", "claim", "reviewer_member", "decision", "reviewed_at")
    list_filter = ("decision", "reviewed_at")
    search_fields = ("review_id", "claim__claim_id", "claim__title", "reviewer_member__member_no")
    list_select_related = ("claim", "reviewer_member")
    date_hierarchy = "reviewed_at"
    readonly_fields = model_field_names(FinanceReview)


@admin.register(FinanceTransaction)
class FinanceTransactionAdmin(ImmutableHistoryAdminMixin, admin.ModelAdmin):
    list_display = ("transaction_id", "transaction_type", "direction", "amount", "currency", "occurred_at")
    list_filter = ("transaction_type", "direction", "currency", "occurred_at")
    search_fields = ("transaction_id", "summary", "claim__claim_id", "recorded_by__member_no")
    list_select_related = ("claim", "recorded_by")
    date_hierarchy = "occurred_at"
    readonly_fields = model_field_names(FinanceTransaction)
