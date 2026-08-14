"""Event-centered member feedback model."""

from django.db import models

from .events import Event
from .identity import Member


class EventFeedback(models.Model):
    """Real-name feedback fixed to one user-visible business event."""

    class FeedbackType(models.TextChoices):
        CORRECTION = "correction", "纠错"
        OPINION = "opinion", "意见"
        COMPLAINT = "complaint", "投诉"
        REPORT = "report", "举报"
        REVIEW = "review", "复核"
        RISK = "risk", "风险"

    class Status(models.TextChoices):
        SUBMITTED = "submitted", "已提交"
        VERIFYING = "verifying", "核实中"
        AWAITING_RESPONSE = "awaiting_response", "等待回应"
        CONCLUDED = "concluded", "已形成结论"
        CLOSED = "closed", "已结束"
        WITHDRAWN = "withdrawn", "已撤回"

    class SubmitterVisibility(models.TextChoices):
        PUBLIC = "public", "公开"
        PARTIES_AND_HANDLERS = "parties_and_handlers", "仅相关方和处理人"
        HANDLERS_ONLY = "handlers_only", "仅处理人"

    class Conclusion(models.TextChoices):
        CONFIRMED = "confirmed", "属实"
        PARTLY_CONFIRMED = "partly_confirmed", "部分属实"
        NOT_CONFIRMED = "not_confirmed", "不属实"
        INCONCLUSIVE = "inconclusive", "无法核实"
        NOT_APPLICABLE = "not_applicable", "不适用"

    feedback_id = models.CharField("反馈ID", max_length=64, primary_key=True)
    related_event = models.ForeignKey(Event, on_delete=models.PROTECT, related_name="feedbacks", verbose_name="关联事件")
    feedback_type = models.CharField("反馈类型", max_length=24, choices=FeedbackType.choices)
    status = models.CharField("状态", max_length=24, choices=Status.choices, default=Status.SUBMITTED)
    submitted_by = models.ForeignKey(Member, on_delete=models.PROTECT, related_name="submitted_event_feedbacks", verbose_name="提交人")
    subject_member = models.ForeignKey(Member, null=True, blank=True, on_delete=models.PROTECT, related_name="subject_event_feedbacks", verbose_name="相关方")
    statement = models.TextField("事实陈述")
    requested_outcome = models.TextField("期望结果", blank=True)
    evidence_refs = models.JSONField("证据引用", default=list, blank=True, help_text="仅保存稳定证据标识；公开输出不得直接暴露受保护凭据。")
    submitter_visibility = models.CharField("提交人身份展示范围", max_length=24, choices=SubmitterVisibility.choices, default=SubmitterVisibility.PUBLIC, help_text="只控制提交人身份展示，不改变系统内部实名记录。")
    privacy_reason = models.TextField("限制身份展示理由", blank=True, help_text="选择非公开身份展示范围时必填，仅处理者可见。")
    assigned_handler = models.ForeignKey(Member, null=True, blank=True, on_delete=models.PROTECT, related_name="assigned_event_feedbacks", verbose_name="核实责任人")
    response_statement = models.TextField("相关方回应", blank=True)
    responded_by = models.ForeignKey(Member, null=True, blank=True, on_delete=models.PROTECT, related_name="responded_event_feedbacks", verbose_name="回应人")
    responded_at = models.DateTimeField("回应时间", null=True, blank=True)
    conclusion = models.CharField("结论", max_length=24, choices=Conclusion.choices, blank=True)
    conclusion_reason = models.TextField("结论依据", blank=True)
    resolution_event = models.ForeignKey(Event, null=True, blank=True, on_delete=models.PROTECT, related_name="resolved_feedbacks", verbose_name="结果事件")
    concluded_by = models.ForeignKey(Member, null=True, blank=True, on_delete=models.PROTECT, related_name="concluded_event_feedbacks", verbose_name="结论责任人")
    submitted_at = models.DateTimeField("提交时间")
    verification_started_at = models.DateTimeField("开始核实时间", null=True, blank=True)
    concluded_at = models.DateTimeField("形成结论时间", null=True, blank=True)
    closed_at = models.DateTimeField("结束时间", null=True, blank=True)
    metadata = models.JSONField("扩展数据", default=dict, blank=True)

    class Meta:
        db_table = "core_event_feedback"
        verbose_name = "事件反馈"
        verbose_name_plural = "事件反馈"
        ordering = ["-submitted_at", "feedback_id"]
        indexes = [models.Index(fields=["status"]), models.Index(fields=["submitted_by"]), models.Index(fields=["assigned_handler"])]

    def __str__(self) -> str:
        return self.feedback_id
