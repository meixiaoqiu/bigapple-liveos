"""Authority records for deliberator qualification exams."""

from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import models

from .identity import Member, RoleAssignment


def _stable_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:16]}"


def _new_policy_id() -> str:
    return _stable_id("delib-policy")


def _new_question_id() -> str:
    return _stable_id("delib-question")


def _new_attempt_id() -> str:
    return _stable_id("delib-attempt")


class DeliberatorExamPolicy(models.Model):
    """A versioned policy controlling deliberator exam selection and grading."""

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        ACTIVE = "active", "生效中"
        RETIRED = "retired", "已停用"

    policy_id = models.CharField("政策 ID", max_length=64, unique=True, default=_new_policy_id)
    version = models.PositiveIntegerField("版本", unique=True)
    question_count = models.PositiveSmallIntegerField("抽题数量", default=1)
    passing_percent = models.PositiveSmallIntegerField("及格百分比", default=100)
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.DRAFT)
    active_slot = models.PositiveSmallIntegerField(
        "生效唯一槽位",
        null=True,
        blank=True,
        unique=True,
        editable=False,
        help_text="仅生效政策写入固定值 1，利用数据库唯一约束保证每个 world 至多一项生效政策。",
    )
    published_by = models.ForeignKey(Member, null=True, blank=True, on_delete=models.PROTECT, related_name="published_deliberator_exam_policies", verbose_name="发布人")
    published_at = models.DateTimeField("发布时间", null=True, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "执衡者考试政策"
        verbose_name_plural = "执衡者考试政策"
        ordering = ("-version",)
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(status="active", active_slot=1)
                    | (~models.Q(status="active") & models.Q(active_slot__isnull=True))
                ),
                name="deliberator_policy_active_slot_consistent",
            ),
        ]

    def clean(self):
        self.active_slot = 1 if self.status == self.Status.ACTIVE else None
        if self.question_count < 1:
            raise ValidationError({"question_count": "抽题数量必须大于零。"})
        if not 1 <= self.passing_percent <= 100:
            raise ValidationError({"passing_percent": "及格百分比必须在 1 到 100 之间。"})

    def save(self, *args, **kwargs):
        self.active_slot = 1 if self.status == self.Status.ACTIVE else None
        if kwargs.get("update_fields") is not None and "status" in kwargs["update_fields"]:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {"active_slot"}
        return super().save(*args, **kwargs)


class DeliberatorExamQuestion(models.Model):
    """A versioned single-choice question in the deliberator question bank."""

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        PUBLISHED = "published", "已发布"
        RETIRED = "retired", "已停用"

    question_id = models.CharField("题目 ID", max_length=64, default=_new_question_id, help_text="同一道题不同版本共用的稳定标识。")
    version = models.PositiveIntegerField("版本", default=1)
    prompt = models.TextField("题干")
    options_json = models.JSONField("选项", default=list, help_text="选项列表，每项包含稳定 id 和显示文本。")
    correct_option_id = models.CharField("正确选项 ID", max_length=64, help_text="仅用于服务端评分，不得输出到普通成员页面或日志。")
    explanation = models.TextField("解释", blank=True, help_text="仅供题库维护和内部审计，不向考生显示。")
    points = models.PositiveSmallIntegerField("分值", default=1)
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(Member, null=True, blank=True, on_delete=models.PROTECT, related_name="created_deliberator_exam_questions", verbose_name="创建人")
    published_by = models.ForeignKey(Member, null=True, blank=True, on_delete=models.PROTECT, related_name="published_deliberator_exam_questions", verbose_name="发布人")
    published_at = models.DateTimeField("发布时间", null=True, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "执衡者考试题目"
        verbose_name_plural = "执衡者考试题目"
        ordering = ("question_id", "-version")
        constraints = [models.UniqueConstraint(fields=("question_id", "version"), name="unique_deliberator_question_version")]

    def clean(self):
        options = self.options_json if isinstance(self.options_json, list) else []
        ids = [str(item.get("id", "")) for item in options if isinstance(item, dict)]
        if len(options) < 2 or len(ids) != len(options) or any(not value for value in ids) or len(set(ids)) != len(ids):
            raise ValidationError({"options_json": "必须提供至少两个具有唯一非空 ID 的选项。"})
        if self.correct_option_id not in ids:
            raise ValidationError({"correct_option_id": "正确选项必须存在于选项列表中。"})
        if self.points < 1:
            raise ValidationError({"points": "分值必须大于零。"})


class DeliberatorExamAttempt(models.Model):
    """An immutable question snapshot and final result for one member attempt."""

    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "答题中"
        PASSED = "passed", "已通过"
        FAILED = "failed", "未通过"
        INVALIDATED = "invalidated", "资格失效"

    attempt_id = models.CharField("考试尝试 ID", max_length=64, unique=True, default=_new_attempt_id)
    member = models.ForeignKey(Member, on_delete=models.PROTECT, related_name="deliberator_exam_attempts", verbose_name="成员")
    policy = models.ForeignKey(DeliberatorExamPolicy, on_delete=models.PROTECT, related_name="attempts", verbose_name="考试政策")
    policy_version = models.PositiveIntegerField("政策版本", help_text="开始考试时生效的政策版本快照。")
    question_snapshot_json = models.JSONField("题目与评分快照", default=list, help_text="私有不可变快照，包含评分所需正确答案，不得公开。")
    answers_json = models.JSONField("作答", default=dict, blank=True)
    score = models.PositiveIntegerField("得分", null=True, blank=True)
    total_points = models.PositiveIntegerField("总分")
    passing_score = models.PositiveIntegerField("及格分")
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.IN_PROGRESS)
    role_assignment = models.OneToOneField(RoleAssignment, null=True, blank=True, on_delete=models.PROTECT, related_name="deliberator_exam_attempt", verbose_name="产生的执衡者任期")
    started_at = models.DateTimeField("开始时间", auto_now_add=True)
    submitted_at = models.DateTimeField("提交时间", null=True, blank=True)

    class Meta:
        verbose_name = "执衡者考试尝试"
        verbose_name_plural = "执衡者考试尝试"
        ordering = ("-started_at",)
        indexes = [models.Index(fields=("member", "status"))]

    def clean(self):
        completed = self.status != self.Status.IN_PROGRESS
        if completed != bool(self.submitted_at):
            raise ValidationError("考试完成状态必须与提交时间一致。")
        if self.role_assignment_id and self.status != self.Status.PASSED:
            raise ValidationError("只有通过的考试可以关联执衡者任期。")
