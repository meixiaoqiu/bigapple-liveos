"""Community feedback model — public engagement, not governance."""

from django.db import models

from .identity import Member
from .proposals import Proposal


def _generate_feedback_id() -> str:
    from uuid import uuid4

    return f"feedback-{uuid4().hex[:12]}"


class CommunityFeedback(models.Model):
    """A public question, suggestion, concern or proposal seed from a registered member.

    Feedback is NOT a governance proposal — it does not change any
    authoritative system state.  Governance members may respond,
    hide inappropriate content, or link feedback to a formal Proposal
    for further governance action.  Runtime authorisation still flows
    exclusively through RoleAssignment → RolePermission.
    """

    class Category(models.TextChoices):
        QUESTION = "question", "问题"
        SUGGESTION = "suggestion", "建议"
        CONCERN = "concern", "担忧/质疑"
        PROPOSAL_SEED = "proposal_seed", "提案种子"
        OTHER = "other", "其他"

    class Status(models.TextChoices):
        OPEN = "open", "待回应"
        ACKNOWLEDGED = "acknowledged", "已看到"
        ANSWERED = "answered", "已回应"
        LINKED = "linked", "已转入治理流程"
        CLOSED = "closed", "已关闭"
        HIDDEN = "hidden", "已隐藏"

    feedback_id = models.CharField(
        "反馈 ID",
        max_length=64,
        unique=True,
        default=_generate_feedback_id,
        help_text="稳定的业务 ID。",
    )
    author_member = models.ForeignKey(
        Member,
        on_delete=models.PROTECT,
        related_name="community_feedbacks",
        verbose_name="作者",
        help_text="提出反馈的注册成员。",
    )
    title = models.CharField("标题", max_length=120)
    category = models.CharField(
        "类别", max_length=32, choices=Category.choices, default=Category.OTHER
    )
    body = models.TextField("正文", help_text="反馈的详细内容，纯文本。")
    status = models.CharField(
        "状态",
        max_length=32,
        choices=Status.choices,
        default=Status.OPEN,
        help_text="反馈的当前处理状态。",
    )
    official_response = models.TextField(
        "官方回应", blank=True, help_text="治理成员的公开回应。"
    )
    responded_by = models.ForeignKey(
        Member,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="responded_community_feedbacks",
        verbose_name="回应人",
        help_text="最近回应该反馈的治理成员。",
    )
    responded_at = models.DateTimeField(
        "回应时间", null=True, blank=True, help_text="最近一次回应的发生时间。"
    )
    linked_proposal = models.ForeignKey(
        Proposal,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="community_feedbacks",
        verbose_name="关联提案",
        help_text="由此反馈转入的正式治理提案。",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "社区反馈"
        verbose_name_plural = "社区反馈"
        ordering = ("-created_at", "-id")

    def __str__(self) -> str:
        return self.title or self.feedback_id
