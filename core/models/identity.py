"""Members, organizations, roles, and role-derived permissions."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Member(models.Model):
    """A member known to Live OS.

    Member roles are represented by active ``RoleAssignment`` records. There is
    no separate identity type, virtual-member flag, or single role field here.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "活跃"
        PENDING_TRAINING = "pending_training", "待培训"
        PENDING_REVIEW = "pending_review", "待审核"
        ADMITTED = "admitted", "已接纳"
        APPLICATION_REJECTED = "application_rejected", "报名未通过"
        SUSPENDED = "suspended", "已暂停"
        EXITED = "exited", "已退出"

    id = models.BigAutoField("ID", primary_key=True)
    member_no = models.CharField(
        "成员编号",
        max_length=64,
        unique=True,
        help_text="稳定的业务编号，例如 mem-0001；不是数据库主键。",
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="member",
        verbose_name="登录用户",
    )
    display_name = models.CharField("显示名称", max_length=255, blank=True)
    status = models.CharField("状态", max_length=32, choices=Status.choices)
    batch_id = models.CharField(
        "批次ID",
        max_length=64,
        blank=True,
        help_text="准入批次或模拟批次标识。",
    )
    joined_simulation_day = models.PositiveIntegerField(
        "进入模拟日期",
        null=True,
        blank=True,
        help_text="成员进入据点的模拟第几天。",
    )
    credit_floor = models.IntegerField(
        "积分下限",
        help_text="该成员类别允许的最低积分余额。",
    )
    profile = models.JSONField(
        "成员画像",
        default=dict,
        blank=True,
        help_text="面向模拟的成员特征，例如疲劳值、满意度和技能。",
    )
    created_at = models.DateTimeField("创建时间", help_text="成员记录创建时的 UTC 时间。")
    metadata = models.JSONField("扩展数据", default=dict, blank=True)

    class Meta:
        db_table = "core_member"
        verbose_name = "成员"
        verbose_name_plural = "成员"

    def __str__(self) -> str:
        return self.member_no

    def active_role_names(self) -> list[str]:
        checked_at = timezone.now()
        return list(
            self.role_assignments.filter(
                status="active",
                role__status="active",
                start_at__lte=checked_at,
                end_at__gte=checked_at,
            )
            .select_related("role", "role__organization")
            .values_list("role__name", flat=True)
        )

    @property
    def active_roles_display(self) -> str:
        return "、".join(self.active_role_names())


class Organization(models.Model):
    """A governance container. Meaning comes from roles, not organization categories."""

    class Status(models.TextChoices):
        ACTIVE = "active", "活跃"
        INACTIVE = "inactive", "停用"
        ARCHIVED = "archived", "已归档"

    name = models.CharField("名称", max_length=255)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
        verbose_name="上级组织",
    )
    status = models.CharField("状态", max_length=32, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "core_organization"
        verbose_name = "组织"
        verbose_name_plural = "组织"
        indexes = [
            models.Index(fields=["parent", "status"]),
        ]

    def __str__(self) -> str:
        return self.name


class Role(models.Model):
    """A member role inside an organization."""

    class Status(models.TextChoices):
        ACTIVE = "active", "活跃"
        INACTIVE = "inactive", "停用"
        RETIRED = "retired", "已退役"

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="roles", verbose_name="组织")
    name = models.CharField("名称", max_length=255)
    description = models.TextField("说明", blank=True)
    status = models.CharField("状态", max_length=32, choices=Status.choices, default=Status.ACTIVE)
    appointment_electorate_role = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="appointable_roles",
        verbose_name="任命表决角色",
        help_text="拥有该角色的成员可参与任命此角色；为空表示暂不启用表决流程。",
    )
    appointment_required_percent = models.PositiveSmallIntegerField(
        "任命通过比例",
        default=50,
        help_text="任命此角色所需赞成比例，50 表示过半，100 表示全票通过。",
    )
    appointment_deadline_days = models.PositiveIntegerField(
        "任命截止天数",
        default=7,
        help_text="任命表决默认截止天数。",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "core_role"
        verbose_name = "角色"
        verbose_name_plural = "角色"
        indexes = [models.Index(fields=["organization", "status"])]
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="unique_role_name_per_organization"),
        ]

    def __str__(self) -> str:
        return f"{self.organization} - {self.name}"

    def clean(self):
        super().clean()
        if self.appointment_required_percent < 1 or self.appointment_required_percent > 100:
            raise ValidationError({"appointment_required_percent": "任命通过比例必须在 1 到 100 之间。"})


class Permission(models.Model):
    """A domain governance permission, separate from Django model permissions."""

    code = models.CharField("权限代码", max_length=128, unique=True)
    name = models.CharField("名称", max_length=255)
    category = models.CharField("分类", max_length=64)
    description = models.TextField("说明", blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "core_permission"
        verbose_name = "治理权限"
        verbose_name_plural = "治理权限"
        ordering = ["category", "code"]
        indexes = [models.Index(fields=["category"])]

    def __str__(self) -> str:
        return self.code


class RoleAssignment(models.Model):
    """A member's active or historical assignment to a role."""

    class Status(models.TextChoices):
        ACTIVE = "active", "生效中"
        REVOKED = "revoked", "已撤销"
        SUSPENDED = "suspended", "已暂停"
        EXPIRED = "expired", "已过期"

    class SourceType(models.TextChoices):
        DIRECT = "direct", "直接任命"
        PROPOSAL = "proposal", "提案执行"
        INITIALIZATION = "initialization", "初始化"
        SYSTEM = "system", "系统产生"

    member = models.ForeignKey(Member, on_delete=models.PROTECT, related_name="role_assignments", verbose_name="成员")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="assignments", verbose_name="角色")
    status = models.CharField("状态", max_length=32, choices=Status.choices, default=Status.ACTIVE)
    start_at = models.DateTimeField("开始时间", default=timezone.now)
    end_at = models.DateTimeField("结束时间")
    granted_by = models.ForeignKey(
        Member,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="granted_role_assignments",
        verbose_name="任命人",
    )
    revoked_by = models.ForeignKey(
        Member,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="revoked_role_assignments",
        verbose_name="卸任处理人",
    )
    source_type = models.CharField(
        "来源类型",
        max_length=32,
        choices=SourceType.choices,
        default=SourceType.DIRECT,
        help_text="说明这条角色任命由直接任命、提案执行、初始化或系统规则产生。",
    )
    source_proposal = models.ForeignKey(
        "Proposal",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="source_role_assignments",
        verbose_name="来源提案",
    )
    source_proposal_execution = models.ForeignKey(
        "ProposalExecution",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="source_role_assignments",
        verbose_name="来源提案执行",
    )
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "core_role_assignment"
        verbose_name = "角色任命"
        verbose_name_plural = "角色任命"
        indexes = [
            models.Index(fields=["member", "status"]),
            models.Index(fields=["role", "status"]),
            models.Index(fields=["start_at", "end_at"]),
            models.Index(fields=["source_type"]),
            models.Index(fields=["source_proposal"]),
        ]

    def __str__(self) -> str:
        return f"{self.member} -> {self.role}"

    def clean(self):
        super().clean()
        if not self.end_at:
            raise ValidationError({"end_at": "角色任命必须填写结束时间。"})
        if self.start_at and self.end_at and self.end_at <= self.start_at:
            raise ValidationError({"end_at": "角色任命结束时间必须晚于开始时间。"})
        if self.status == self.Status.ACTIVE and self.member_id and self.role_id:
            duplicate = type(self).objects.filter(
                member_id=self.member_id,
                role_id=self.role_id,
                status=self.Status.ACTIVE,
            )
            if self.pk:
                duplicate = duplicate.exclude(pk=self.pk)
            if duplicate.exists():
                raise ValidationError("同一成员不能重复拥有同一个 active 角色。")

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)


class RolePermission(models.Model):
    """A permission granted to a role."""

    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="role_permissions", verbose_name="角色")
    permission = models.ForeignKey(Permission, on_delete=models.PROTECT, related_name="role_permissions", verbose_name="权限")
    scope = models.CharField("作用域", max_length=128, blank=True, default="global")
    constraints_json = models.JSONField("约束", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "core_role_permission"
        verbose_name = "角色权限"
        verbose_name_plural = "角色权限"
        indexes = [
            models.Index(fields=["role"]),
            models.Index(fields=["permission"]),
            models.Index(fields=["scope"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["role", "permission", "scope"], name="unique_role_permission_scope"),
        ]

    def __str__(self) -> str:
        return f"{self.role}: {self.permission.code}"
