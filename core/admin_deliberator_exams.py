"""Admin maintenance surfaces for deliberator exams."""

from django.contrib import admin, messages

from .access import member_for_user
from .deliberator_exam_services import (
    copy_exam_question_to_draft,
    publish_exam_policy,
    publish_exam_question,
    retire_exam_question,
)
from .exceptions import DomainError
from .governance_setup import DELIBERATOR_EXAM_MANAGE_PERMISSION
from .models import DeliberatorExamAttempt, DeliberatorExamPolicy, DeliberatorExamQuestion
from .access import member_can_administer


class ExamMaintenanceAdminMixin:
    def _allowed(self, request) -> bool:
        member = member_for_user(request.user)
        return bool(member and member_can_administer(member, DELIBERATOR_EXAM_MANAGE_PERMISSION))

    def has_module_permission(self, request):
        return self._allowed(request)

    def has_view_permission(self, request, obj=None):
        return self._allowed(request)


@admin.register(DeliberatorExamQuestion)
class DeliberatorExamQuestionAdmin(ExamMaintenanceAdminMixin, admin.ModelAdmin):
    list_display = ("question_id", "version", "prompt", "points", "status", "published_by", "published_at")
    list_filter = ("status",)
    search_fields = ("question_id", "prompt")
    readonly_fields = ("question_id", "version", "created_by", "published_by", "published_at", "created_at", "updated_at")
    actions = ("publish_selected", "copy_selected_to_draft", "retire_selected")

    def has_add_permission(self, request):
        return self._allowed(request)

    def has_change_permission(self, request, obj=None):
        return self._allowed(request) and (obj is None or obj.status == DeliberatorExamQuestion.Status.DRAFT)

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if obj.created_by_id is None:
            obj.created_by = member_for_user(request.user)
        obj.status = DeliberatorExamQuestion.Status.DRAFT
        obj.full_clean()
        super().save_model(request, obj, form, change)

    @admin.action(description="发布所选草稿题目")
    def publish_selected(self, request, queryset):
        actor = member_for_user(request.user)
        published = 0
        for question in queryset:
            try:
                publish_exam_question(actor=actor, question=question)
            except DomainError as exc:
                self.message_user(request, str(exc), level=messages.ERROR)
            else:
                published += 1
        if published:
            self.message_user(request, f"已发布 {published} 道题。", level=messages.SUCCESS)

    @admin.action(description="将所选最新版本复制为可编辑草稿")
    def copy_selected_to_draft(self, request, queryset):
        actor = member_for_user(request.user)
        copied = 0
        for question in queryset:
            try:
                copy_exam_question_to_draft(actor=actor, question=question)
            except DomainError as exc:
                self.message_user(request, str(exc), level=messages.ERROR)
            else:
                copied += 1
        if copied:
            self.message_user(request, f"已创建 {copied} 道新版本草稿。", level=messages.SUCCESS)

    @admin.action(description="停用所选题目版本")
    def retire_selected(self, request, queryset):
        actor = member_for_user(request.user)
        retired = 0
        for question in queryset:
            try:
                retire_exam_question(actor=actor, question=question)
            except DomainError as exc:
                self.message_user(request, str(exc), level=messages.ERROR)
            else:
                retired += 1
        if retired:
            self.message_user(request, f"已停用 {retired} 道题目版本。", level=messages.SUCCESS)


@admin.register(DeliberatorExamPolicy)
class DeliberatorExamPolicyAdmin(ExamMaintenanceAdminMixin, admin.ModelAdmin):
    list_display = ("version", "question_count", "passing_percent", "status", "published_by", "published_at")
    readonly_fields = ("policy_id", "version", "published_by", "published_at", "created_at", "updated_at")
    actions = ("publish_selected",)

    def has_add_permission(self, request):
        return self._allowed(request)

    def has_change_permission(self, request, obj=None):
        return self._allowed(request) and (obj is None or obj.status == DeliberatorExamPolicy.Status.DRAFT)

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if obj.pk is None:
            latest = DeliberatorExamPolicy.objects.order_by("-version").first()
            obj.version = (latest.version + 1) if latest else 1
        obj.status = DeliberatorExamPolicy.Status.DRAFT
        obj.full_clean()
        super().save_model(request, obj, form, change)

    @admin.action(description="发布所选草稿政策")
    def publish_selected(self, request, queryset):
        actor = member_for_user(request.user)
        for draft in queryset:
            if draft.status != DeliberatorExamPolicy.Status.DRAFT:
                self.message_user(request, "只能发布草稿政策。", level=messages.ERROR)
                continue
            try:
                published = publish_exam_policy(
                    actor=actor,
                    question_count=draft.question_count,
                    passing_percent=draft.passing_percent,
                )
            except DomainError as exc:
                self.message_user(request, str(exc), level=messages.ERROR)
            else:
                draft.delete()
                self.message_user(request, f"已发布政策 v{published.version}。", level=messages.SUCCESS)


@admin.register(DeliberatorExamAttempt)
class DeliberatorExamAttemptAdmin(ExamMaintenanceAdminMixin, admin.ModelAdmin):
    list_display = ("attempt_id", "member", "policy_version", "score", "total_points", "passing_score", "status", "started_at", "submitted_at")
    list_filter = ("status", "policy_version")
    search_fields = ("attempt_id", "member__member_no", "member__display_name")
    exclude = ("question_snapshot_json", "answers_json")
    readonly_fields = tuple(field.name for field in DeliberatorExamAttempt._meta.fields if field.name not in {"question_snapshot_json", "answers_json"})

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
