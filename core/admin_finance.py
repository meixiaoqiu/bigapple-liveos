"""Read-only Django Admin configuration for finance records."""

from __future__ import annotations

from django.contrib import admin

from .admin_support import ImmutableHistoryAdminMixin, model_field_names
from .models import Attachment, ExpenseClaim, ExpenseClaimAttachment, FinanceReview, FinanceTransaction, PaymentExecution


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


@admin.register(Attachment)
class AttachmentAdmin(ImmutableHistoryAdminMixin, admin.ModelAdmin):
    list_display = ("attachment_id", "detected_media_type", "byte_size", "audience", "lifecycle", "uploaded_by", "created_at")
    list_filter = ("audience", "lifecycle", "detected_media_type", "created_at")
    search_fields = ("attachment_id", "uploaded_by__member_no")
    list_select_related = ("uploaded_by", "source_attachment", "supersedes")
    readonly_fields = model_field_names(Attachment)


@admin.register(ExpenseClaimAttachment)
class ExpenseClaimAttachmentAdmin(ImmutableHistoryAdminMixin, admin.ModelAdmin):
    list_display = ("claim", "attachment", "purpose", "payment_execution", "created_at")
    list_filter = ("purpose", "created_at")
    search_fields = ("claim__claim_id", "attachment__attachment_id")
    list_select_related = ("claim", "attachment", "payment_execution")
    readonly_fields = model_field_names(ExpenseClaimAttachment)


@admin.register(PaymentExecution)
class PaymentExecutionAdmin(ImmutableHistoryAdminMixin, admin.ModelAdmin):
    list_display = ("execution_id", "claim", "backend_type", "status", "payment_date", "payer_member", "executed_at")
    list_filter = ("backend_type", "status", "sync_status", "payment_date")
    search_fields = ("execution_id", "claim__claim_id", "payer_member__member_no", "external_object_id")
    list_select_related = ("claim", "payer_member", "finance_transaction")
    readonly_fields = model_field_names(PaymentExecution)
