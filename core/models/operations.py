"""Operational task, credit ledger, and resource models."""

from django.db import models
from django.utils import timezone

from .applications import PartnerApplication
from .identity import Member
from .planning import PlanNode


class Task(models.Model):
    """A unit of work that members can claim, submit, and have reviewed."""

    class TaskType(models.TextChoices):
        COOKING = "cooking", "做饭"
        DISHWASHING = "dishwashing", "洗碗"
        PUBLIC_CLEANING = "public_cleaning", "公共清洁"
        WASTE = "waste", "垃圾处理"
        WAREHOUSE = "warehouse", "仓库整理"
        REPAIR = "repair", "维修"
        PURCHASE = "purchase", "采购"
        FARMING = "farming", "种植/农务"
        DUTY = "duty", "值班"
        CARE = "care", "照护"
        TRAINING = "training", "培训"
        ADMINISTRATION = "administration", "管理/文书"

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        OPEN = "open", "待领取"
        CLAIMED = "claimed", "已领取"
        IN_PROGRESS = "in_progress", "进行中"
        PENDING_REVIEW = "pending_review", "待验收"
        ACCEPTED = "accepted", "验收通过"
        REJECTED = "rejected", "验收驳回"
        DISPUTED = "disputed", "有争议"
        CLOSED = "closed", "已关闭"
        REVERSED = "reversed", "已冲正"

    class FailureConsequence(models.TextChoices):
        LOW = "low", "低"
        MEDIUM = "medium", "中"
        HIGH = "high", "高"
        CRITICAL = "critical", "严重"

    class SourceType(models.TextChoices):
        DIRECT = "direct", "直接创建"
        PROPOSAL = "proposal", "提案执行"
        PLAN = "plan", "计划派生"
        SIMULATION = "simulation", "仿真产生"
        SYSTEM = "system", "系统产生"

    task_id = models.CharField("任务ID", max_length=64, primary_key=True)
    title = models.CharField("标题", max_length=255)
    task_type = models.CharField("任务类型", max_length=32, choices=TaskType.choices)
    status = models.CharField("状态", max_length=32, choices=Status.choices, default=Status.DRAFT)
    standard_hours = models.DecimalField("标准工时", max_digits=8, decimal_places=2)
    base_points = models.IntegerField("基础积分")
    role_coefficient = models.DecimalField("岗位系数", max_digits=6, decimal_places=3, default=1)
    physical_load = models.DecimalField("体力要求", max_digits=5, decimal_places=2, null=True, blank=True)
    dirty_level = models.DecimalField("脏累程度", max_digits=5, decimal_places=2, null=True, blank=True)
    psychological_load = models.DecimalField("心理负担", max_digits=5, decimal_places=2, null=True, blank=True)
    urgency = models.DecimalField("紧急度", max_digits=5, decimal_places=2, null=True, blank=True)
    can_be_delayed = models.BooleanField("是否可延期", default=True)
    requires_review = models.BooleanField("是否需要验收", default=True)
    failure_consequence = models.CharField(
        "失败后果",
        max_length=16,
        choices=FailureConsequence.choices,
        blank=True,
    )
    assignee_member = models.ForeignKey(
        Member,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="assigned_tasks",
        verbose_name="领取成员",
        help_text="当前负责该任务的成员。",
    )
    plan_node = models.ForeignKey(
        PlanNode,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tasks",
        verbose_name="所属计划节点",
        help_text="该任务服务于哪个主线计划节点；为空表示临时运营任务。",
    )
    source_type = models.CharField(
        "来源类型",
        max_length=32,
        choices=SourceType.choices,
        default=SourceType.DIRECT,
        help_text="说明任务由直接运营、提案执行、计划派生、仿真或系统规则产生。",
    )
    source_proposal = models.ForeignKey(
        "Proposal",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="source_tasks",
        verbose_name="来源提案",
    )
    source_proposal_execution = models.ForeignKey(
        "ProposalExecution",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="source_tasks",
        verbose_name="来源提案执行",
    )
    rule_version = models.CharField("规则版本", max_length=32)
    created_at = models.DateTimeField("创建时间")
    due_at = models.DateTimeField("截止时间", null=True, blank=True)
    submitted_at = models.DateTimeField("提交时间", null=True, blank=True)
    reviewed_at = models.DateTimeField("验收时间", null=True, blank=True)
    metadata = models.JSONField("扩展数据", default=dict, blank=True)

    class Meta:
        db_table = "core_task"
        verbose_name = "任务"
        verbose_name_plural = "任务"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["task_type"]),
            models.Index(fields=["assignee_member"]),
            models.Index(fields=["source_type"]),
            models.Index(fields=["source_proposal"]),
        ]

    def __str__(self) -> str:
        return self.task_id


class LedgerEntry(models.Model):
    """Append-only point ledger entry.

    Balances are derived from these rows. Corrections must create new rows
    rather than modifying historical entries.
    """

    class EntryType(models.TextChoices):
        CONTRIBUTION = "contribution", "贡献"
        CONSUMPTION = "consumption", "消费"
        PENALTY = "penalty", "扣减"
        COMPENSATION = "compensation", "补偿"
        CORRECTION = "correction", "更正"
        REVERSAL = "reversal", "冲正"

    class Status(models.TextChoices):
        POSTED = "posted", "已入账"
        PENDING_REVIEW = "pending_review", "待复核"
        REVERSED = "reversed", "已冲正"

    ledger_entry_id = models.CharField("账本流水ID", max_length=64, primary_key=True)
    member = models.ForeignKey(Member, on_delete=models.PROTECT, related_name="ledger_entries", verbose_name="成员")
    amount = models.IntegerField("积分变化", help_text="有符号积分变化值。")
    entry_type = models.CharField("流水类型", max_length=32, choices=EntryType.choices)
    reason = models.TextField("原因")
    related_task = models.ForeignKey(
        Task,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
        verbose_name="关联任务",
    )
    related_event_id = models.CharField("关联事件ID", max_length=64, blank=True)
    rule_version = models.CharField("规则版本", max_length=32)
    created_at = models.DateTimeField("创建时间")
    created_by = models.JSONField("创建人", default=dict)
    reviewer = models.JSONField("验收人/责任人", default=dict, blank=True)
    status = models.CharField("状态", max_length=32, choices=Status.choices, default=Status.POSTED)
    reverses_entry = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reversal_entries",
        verbose_name="冲正对象",
    )
    system_event = models.ForeignKey(
        "SystemEvent",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
        verbose_name="统一事件账本记录",
    )
    metadata = models.JSONField("扩展数据", default=dict, blank=True)

    class Meta:
        db_table = "core_ledger_entry"
        verbose_name = "积分流水"
        verbose_name_plural = "积分流水"
        ordering = ["system_event__seq", "created_at", "ledger_entry_id"]
        indexes = [
            models.Index(fields=["member", "created_at"]),
            models.Index(fields=["related_task"]),
            models.Index(fields=["system_event"]),
        ]

    def __str__(self) -> str:
        return self.ledger_entry_id


class Resource(models.Model):
    """Current resource state visible to capacity evaluation and observer views."""

    class ResourceType(models.TextChoices):
        FACILITY = "facility", "设施"
        ROOM = "room", "房间"
        SYSTEM = "system", "系统"
        MATERIAL = "material", "材料"
        EQUIPMENT = "equipment", "设备"
        GRAIN = "grain", "粮食"
        VEGETABLES = "vegetables", "蔬菜"
        WATER = "water", "水"
        ELECTRICITY = "electricity", "电"
        CASH = "cash", "现金"
        MEDICINE = "medicine", "药品"
        TOOLS = "tools", "工具"
        CLEANING_SUPPLIES = "cleaning_supplies", "清洁用品"
        BEDS = "beds", "床位"
        WAREHOUSE_CAPACITY = "warehouse_capacity", "仓库容量"

    class Unit(models.TextChoices):
        KG = "kg", "千克"
        BAG = "bag", "袋"
        LITER = "liter", "升"
        KWH = "kwh", "千瓦时"
        YUAN = "yuan", "元"
        COUNT = "count", "个"
        SLOT = "slot", "位"
        CUBIC_METER = "cubic_meter", "立方米"

    class ReplenishmentMethod(models.TextChoices):
        PURCHASE = "purchase", "采购"
        DONATION = "donation", "捐赠"
        PRODUCTION = "production", "生产"
        REUSE = "reuse", "复用"
        MANUAL_ADJUSTMENT = "manual_adjustment", "人工调整"

    class Status(models.TextChoices):
        ACTIVE = "active", "可用"
        INACTIVE = "inactive", "停用"
        MAINTENANCE = "maintenance", "维护中"
        RETIRED = "retired", "已退役"

    resource_id = models.CharField("资源ID", max_length=64, primary_key=True)
    name = models.CharField("名称", max_length=255, blank=True, default="")
    resource_type = models.CharField("资源类型", max_length=32, choices=ResourceType.choices)
    location = models.CharField("位置", max_length=255, blank=True, default="")
    description = models.TextField("说明", blank=True, default="")
    status = models.CharField("状态", max_length=32, choices=Status.choices, default=Status.ACTIVE)
    unit = models.CharField("单位", max_length=16, choices=Unit.choices)
    current_stock = models.DecimalField("当前库存", max_digits=14, decimal_places=3)
    daily_consumption_estimate = models.DecimalField("预计每日消耗", max_digits=14, decimal_places=3)
    replenishment_method = models.CharField("补充方式", max_length=32, choices=ReplenishmentMethod.choices)
    loss_rate = models.DecimalField("损耗率", max_digits=6, decimal_places=5)
    warning_threshold = models.DecimalField("预警线", max_digits=14, decimal_places=3)
    shortage_impact = models.JSONField("短缺影响", default=dict, blank=True)
    updated_at = models.DateTimeField("更新时间")
    rule_version = models.CharField("规则版本", max_length=32)
    metadata = models.JSONField("扩展数据", default=dict, blank=True)

    class Meta:
        db_table = "core_resource"
        verbose_name = "资源"
        verbose_name_plural = "资源"
        indexes = [
            models.Index(fields=["resource_type"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return self.resource_id


class SupplierQuote(models.Model):
    """A partner quote for supplying a concrete resource."""

    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        ACTIVE = "active", "有效"
        EXPIRED = "expired", "已过期"
        REJECTED = "rejected", "已拒绝"

    class QualityGrade(models.TextChoices):
        UNKNOWN = "unknown", "未评估"
        LOW_RISK = "low_risk", "低风险"
        STANDARD = "standard", "标准"
        HIGH_QUALITY = "high_quality", "高质量"
        RISKY = "risky", "高风险"

    quote_id = models.CharField("报价ID", max_length=96, primary_key=True)
    partner_application = models.ForeignKey(
        PartnerApplication,
        on_delete=models.PROTECT,
        related_name="supplier_quotes",
        verbose_name="合作方报名",
        help_text="报价来源。第一版直接引用合作方报名，后续可沉淀为供应商档案。",
    )
    resource = models.ForeignKey(
        Resource,
        on_delete=models.PROTECT,
        related_name="supplier_quotes",
        verbose_name="资源",
    )
    unit_price = models.DecimalField("单价", max_digits=14, decimal_places=2)
    currency = models.CharField("币种", max_length=16, default="CNY")
    available_quantity = models.DecimalField("可供数量", max_digits=14, decimal_places=3, default=0)
    minimum_order_quantity = models.DecimalField("最小起订量", max_digits=14, decimal_places=3, default=0)
    lead_time_days = models.PositiveIntegerField("交付周期天数", default=0)
    quality_grade = models.CharField("质量评估", max_length=32, choices=QualityGrade.choices, default=QualityGrade.UNKNOWN)
    quality_summary = models.TextField("质量说明", blank=True)
    valid_from = models.DateTimeField("有效开始", null=True, blank=True)
    valid_until = models.DateTimeField("有效截止", null=True, blank=True)
    status = models.CharField("状态", max_length=32, choices=Status.choices, default=Status.ACTIVE)
    notes = models.TextField("备注", blank=True)
    created_at = models.DateTimeField("创建时间", default=timezone.now)
    updated_at = models.DateTimeField("更新时间", null=True, blank=True)
    metadata = models.JSONField("扩展数据", default=dict, blank=True)

    class Meta:
        db_table = "core_supplier_quote"
        verbose_name = "供应商报价"
        verbose_name_plural = "供应商报价"
        ordering = ["resource", "unit_price", "lead_time_days", "quote_id"]
        indexes = [
            models.Index(fields=["resource", "status"]),
            models.Index(fields=["partner_application", "status"]),
            models.Index(fields=["valid_until"]),
        ]

    def __str__(self) -> str:
        return f"{self.quote_id}:{self.resource_id}:{self.unit_price} {self.currency}"


class ResourceTransaction(models.Model):
    """Append-only stock movement for one resource."""

    class TransactionType(models.TextChoices):
        INBOUND = "inbound", "入库"
        OUTBOUND = "outbound", "出库"
        STOCKTAKE_ADJUSTMENT = "stocktake_adjustment", "盘点调整"
        LOSS = "loss", "损耗"
        SCRAP = "scrap", "报废"
        TRANSFER = "transfer", "调拨"
        MANUAL_ADJUSTMENT = "manual_adjustment", "人工调整"

    transaction_id = models.CharField("库存流水ID", max_length=96, primary_key=True)
    resource = models.ForeignKey(
        Resource,
        on_delete=models.PROTECT,
        related_name="transactions",
        verbose_name="资源",
    )
    transaction_type = models.CharField("流水类型", max_length=32, choices=TransactionType.choices)
    quantity_delta = models.DecimalField("变动数量", max_digits=14, decimal_places=3)
    stock_before = models.DecimalField("变动前库存", max_digits=14, decimal_places=3)
    stock_after = models.DecimalField("变动后库存", max_digits=14, decimal_places=3)
    reason = models.TextField("原因")
    operator = models.JSONField("操作人", default=dict, blank=True)
    related_task = models.ForeignKey(
        Task,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="resource_transactions",
        verbose_name="关联任务",
    )
    related_supplier_quote = models.ForeignKey(
        SupplierQuote,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="resource_transactions",
        verbose_name="关联供应商报价",
    )
    system_event = models.ForeignKey(
        "core.SystemEvent",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="resource_transactions",
        verbose_name="统一事件账本记录",
    )
    occurred_at = models.DateTimeField("发生时间")
    created_at = models.DateTimeField("创建时间", default=timezone.now)
    metadata = models.JSONField("扩展数据", default=dict, blank=True)

    class Meta:
        db_table = "core_resource_transaction"
        verbose_name = "库存流水"
        verbose_name_plural = "库存流水"
        ordering = ["occurred_at", "transaction_id"]
        indexes = [
            models.Index(fields=["resource", "occurred_at"]),
            models.Index(fields=["transaction_type"]),
            models.Index(fields=["system_event"]),
        ]

    def __str__(self) -> str:
        return self.transaction_id
