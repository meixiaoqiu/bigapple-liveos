"""Project plan authority models."""

from django.db import models


class Ruleset(models.Model):
    """Versioned rule bundle used by task, ledger, and capacity decisions."""

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        ACTIVE = "active", "生效中"
        RETIRED = "retired", "已退役"

    ruleset_id = models.CharField("规则集ID", max_length=64, primary_key=True)
    version = models.CharField(
        "版本",
        max_length=32,
        unique=True,
        help_text="契约版本字符串，例如 ruleset-v0.1.0。",
    )
    status = models.CharField("状态", max_length=16, choices=Status.choices)
    effective_from = models.DateField("生效日期")
    effective_to = models.DateField("失效日期", null=True, blank=True)
    negative_point_floor = models.JSONField(
        "负积分下限",
        default=dict,
        help_text="不同成员类别的积分下限规则。",
    )
    task_point_rules = models.JSONField(
        "任务积分规则",
        default=list,
        blank=True,
        help_text="任务基础分和系数规则。",
    )
    created_at = models.DateTimeField("创建时间")
    created_by = models.JSONField(
        "创建人",
        default=dict,
        help_text="对该规则版本负责的实名责任人 ActorRef。",
    )
    change_summary = models.TextField("变更说明")
    metadata = models.JSONField("扩展数据", default=dict, blank=True)

    class Meta:
        db_table = "core_ruleset"
        verbose_name = "规则版本"
        verbose_name_plural = "规则版本"
        indexes = [models.Index(fields=["version"])]

    def __str__(self) -> str:
        return self.version


class ProjectPlan(models.Model):
    """Editable master execution plan for a real or simulated settlement project."""

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        ACTIVE = "active", "执行中"
        ARCHIVED = "archived", "已归档"

    plan_id = models.CharField("执行计划ID", max_length=64, primary_key=True)
    name = models.CharField("名称", max_length=255)
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.DRAFT)
    description = models.TextField("说明", blank=True)
    target_location = models.CharField("目标地点", max_length=255, blank=True)
    owner = models.JSONField("责任人", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间")
    updated_at = models.DateTimeField("更新时间", null=True, blank=True)
    metadata = models.JSONField("扩展数据", default=dict, blank=True)

    class Meta:
        db_table = "core_project_plan"
        verbose_name = "项目执行计划"
        verbose_name_plural = "项目执行计划"
        indexes = [models.Index(fields=["status"])]

    def __str__(self) -> str:
        return self.name


class PlanRevision(models.Model):
    """Versioned plan baseline used by simulations and future real execution."""

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        PUBLISHED = "published", "已发布"
        RETIRED = "retired", "已退役"

    revision_id = models.CharField("计划版本ID", max_length=64, primary_key=True)
    plan = models.ForeignKey(ProjectPlan, on_delete=models.PROTECT, related_name="revisions", verbose_name="执行计划")
    revision_code = models.CharField("版本号", max_length=64)
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.DRAFT)
    title = models.CharField("标题", max_length=255)
    change_summary = models.TextField("变更说明")
    created_at = models.DateTimeField("创建时间")
    created_by = models.JSONField("创建人", default=dict, blank=True)
    published_at = models.DateTimeField("发布时间", null=True, blank=True)
    metadata = models.JSONField("扩展数据", default=dict, blank=True)

    class Meta:
        db_table = "core_plan_revision"
        verbose_name = "计划版本"
        verbose_name_plural = "计划版本"
        indexes = [
            models.Index(fields=["plan", "status"]),
            models.Index(fields=["revision_code"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["plan", "revision_code"], name="unique_plan_revision_code"),
        ]

    def __str__(self) -> str:
        return f"{self.plan_id}:{self.revision_code}"


class PlanNode(models.Model):
    """A milestone, stage, work package, or capacity gate in an execution plan."""

    class NodeType(models.TextChoices):
        STAGE = "stage", "阶段"
        MILESTONE = "milestone", "里程碑"
        WORK_PACKAGE = "work_package", "工程包"
        OPERATIONS = "operations", "运营包"
        GOVERNANCE = "governance", "治理节点"
        RECRUITMENT = "recruitment", "招募节点"
        ARRIVAL = "arrival", "抵达节点"
        CAPACITY_GATE = "capacity_gate", "容量门槛"
        EXPANSION = "expansion", "扩容节点"

    class Status(models.TextChoices):
        PLANNED = "planned", "计划中"
        IN_PROGRESS = "in_progress", "推进中"
        BLOCKED = "blocked", "受阻"
        COMPLETED = "completed", "已完成"
        CANCELLED = "cancelled", "已取消"

    node_id = models.CharField("计划节点ID", max_length=96, primary_key=True)
    revision = models.ForeignKey(PlanRevision, on_delete=models.PROTECT, related_name="nodes", verbose_name="计划版本")
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
        verbose_name="父节点",
    )
    sequence = models.PositiveIntegerField("排序", default=0)
    code = models.CharField("节点编号", max_length=64)
    title = models.CharField("标题", max_length=255)
    node_type = models.CharField("节点类型", max_length=32, choices=NodeType.choices)
    status = models.CharField("状态", max_length=32, choices=Status.choices, default=Status.PLANNED)
    is_required = models.BooleanField("是否必要节点", default=True)
    is_expandable = models.BooleanField("是否可分阶段扩容", default=False)
    allow_simulation_adjustment = models.BooleanField("允许模拟提出调整", default=True)
    description = models.TextField("说明", blank=True)
    planned_start_day = models.PositiveIntegerField("计划开始日", null=True, blank=True)
    planned_duration_days = models.PositiveIntegerField("计划工期天数", default=1)
    planned_end_day = models.PositiveIntegerField("计划完成日", null=True, blank=True)
    estimated_cost_low = models.DecimalField("低估成本", max_digits=14, decimal_places=2, default=0)
    estimated_cost_expected = models.DecimalField("预期成本", max_digits=14, decimal_places=2, default=0)
    estimated_cost_high = models.DecimalField("高估成本", max_digits=14, decimal_places=2, default=0)
    required_people_min = models.PositiveIntegerField("最低人数", default=0)
    required_people_max = models.PositiveIntegerField("建议人数", default=0)
    required_person_days = models.DecimalField("预计人天", max_digits=10, decimal_places=2, default=0)
    required_skills = models.JSONField("所需技能", default=list, blank=True)
    required_resources = models.JSONField("所需资源", default=list, blank=True)
    completion_criteria = models.JSONField("完成标准", default=list, blank=True)
    risk_notes = models.TextField("风险说明", blank=True)
    created_at = models.DateTimeField("创建时间")
    updated_at = models.DateTimeField("更新时间", null=True, blank=True)
    metadata = models.JSONField("扩展数据", default=dict, blank=True)

    class Meta:
        db_table = "core_plan_node"
        verbose_name = "计划节点"
        verbose_name_plural = "计划节点"
        ordering = ["sequence", "node_id"]
        indexes = [
            models.Index(fields=["revision", "status"]),
            models.Index(fields=["revision", "node_type"]),
            models.Index(fields=["parent", "sequence"]),
        ]

    def __str__(self) -> str:
        return f"{self.code} {self.title}"


class PlanDependency(models.Model):
    """Directed dependency between two plan nodes."""

    class DependencyType(models.TextChoices):
        FINISH_TO_START = "finish_to_start", "完成后开始"
        RESOURCE_GATE = "resource_gate", "资源门槛"
        CAPACITY_GATE = "capacity_gate", "容量门槛"
        GOVERNANCE_APPROVAL = "governance_approval", "治理确认"
        RECRUITMENT_THRESHOLD = "recruitment_threshold", "招募门槛"

    dependency_id = models.CharField("依赖ID", max_length=96, primary_key=True)
    revision = models.ForeignKey(PlanRevision, on_delete=models.PROTECT, related_name="dependencies", verbose_name="计划版本")
    node = models.ForeignKey(PlanNode, on_delete=models.PROTECT, related_name="dependencies", verbose_name="后续节点")
    depends_on = models.ForeignKey(PlanNode, on_delete=models.PROTECT, related_name="dependents", verbose_name="前置节点")
    dependency_type = models.CharField("依赖类型", max_length=32, choices=DependencyType.choices)
    description = models.TextField("说明", blank=True)
    metadata = models.JSONField("扩展数据", default=dict, blank=True)

    class Meta:
        db_table = "core_plan_dependency"
        verbose_name = "计划依赖"
        verbose_name_plural = "计划依赖"
        indexes = [
            models.Index(fields=["revision", "node"]),
            models.Index(fields=["revision", "depends_on"]),
        ]

    def __str__(self) -> str:
        return f"{self.depends_on_id} -> {self.node_id}"


class PlanRequirement(models.Model):
    """Detailed budget, labor, material, skill, or permit requirement for a plan node."""

    class RequirementType(models.TextChoices):
        BUDGET = "budget", "预算"
        LABOR = "labor", "人力"
        SKILL = "skill", "技能"
        MATERIAL = "material", "材料"
        EQUIPMENT = "equipment", "设备"
        SPACE = "space", "空间"
        PERMIT = "permit", "许可/手续"
        CAPACITY = "capacity", "容量"

    requirement_id = models.CharField("需求ID", max_length=96, primary_key=True)
    node = models.ForeignKey(PlanNode, on_delete=models.PROTECT, related_name="requirements", verbose_name="计划节点")
    resource = models.ForeignKey(
        "core.Resource",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="plan_requirements",
        verbose_name="对应资源",
        help_text="当需求对应当前库存台账中的某类资源时填写，用于计算库存缺口和匹配供应商报价。",
    )
    requirement_type = models.CharField("需求类型", max_length=32, choices=RequirementType.choices)
    name = models.CharField("名称", max_length=255)
    quantity = models.DecimalField("数量", max_digits=14, decimal_places=3, default=0)
    unit = models.CharField("单位", max_length=32, blank=True)
    unit_cost = models.DecimalField("单价", max_digits=14, decimal_places=2, default=0)
    total_cost_estimate = models.DecimalField("总成本估算", max_digits=14, decimal_places=2, default=0)
    is_must = models.BooleanField("是否刚性需求", default=True)
    notes = models.TextField("说明", blank=True)
    metadata = models.JSONField("扩展数据", default=dict, blank=True)

    class Meta:
        db_table = "core_plan_requirement"
        verbose_name = "计划需求"
        verbose_name_plural = "计划需求"
        indexes = [
            models.Index(fields=["node", "requirement_type"]),
            models.Index(fields=["requirement_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.node_id}:{self.name}"


class PlanCapacityImpact(models.Model):
    """Capacity delta produced by completing a plan node."""

    class ImpactType(models.TextChoices):
        MEMBER_CAPACITY = "member_capacity", "成员容量"
        BED_SLOTS = "bed_slots", "床位"
        CANTEEN_MEALS_PER_DAY = "canteen_meals_per_day", "供餐能力"
        PV_MW = "pv_mw", "光伏装机"
        ELECTRICITY_KWH_PER_DAY = "electricity_kwh_per_day", "日供电量"
        STORAGE_CUBIC_METER = "storage_cubic_meter", "仓储体积"
        OFFICE_SQUARE_METER = "office_square_meter", "办公面积"
        RECREATION_SQUARE_METER = "recreation_square_meter", "活动空间"
        HOSPITALITY_ROOMS = "hospitality_rooms", "接待房间"

    impact_id = models.CharField("容量影响ID", max_length=96, primary_key=True)
    node = models.ForeignKey(PlanNode, on_delete=models.PROTECT, related_name="capacity_impacts", verbose_name="计划节点")
    impact_type = models.CharField("影响类型", max_length=40, choices=ImpactType.choices)
    delta = models.DecimalField("变化量", max_digits=14, decimal_places=3)
    unit = models.CharField("单位", max_length=32)
    description = models.TextField("说明", blank=True)
    metadata = models.JSONField("扩展数据", default=dict, blank=True)

    class Meta:
        db_table = "core_plan_capacity_impact"
        verbose_name = "计划容量影响"
        verbose_name_plural = "计划容量影响"
        indexes = [
            models.Index(fields=["node", "impact_type"]),
            models.Index(fields=["impact_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.node_id}:{self.impact_type}:{self.delta}"
