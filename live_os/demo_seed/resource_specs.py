"""Static resource seed specs — split into base catalog, demo, and zero-start layers."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

from core.models import Resource


def base_resource_specs():
    """Return the immutable resource catalog (no stock/demo values)."""
    return [
        {
            "resource_id": "res-cash",
            "name": "运营现金储备",
            "resource_type": Resource.ResourceType.CASH,
            "location": "财务账户",
            "description": "用于紧急采购、房租押金、维修和临时人员保障的流动资金。",
            "status": Resource.Status.ACTIVE,
            "unit": Resource.Unit.YUAN,
            "replenishment_method": Resource.ReplenishmentMethod.MANUAL_ADJUSTMENT,
            "loss_rate": Decimal("0.00000"),
            "warning_threshold": Decimal("1000000"),
            "shortage_impact": {"plan_execution_delta": -40, "procurement_delay_delta": 30},
        },
        {
            "resource_id": "res-grain",
            "name": "基础粮食库存",
            "resource_type": Resource.ResourceType.GRAIN,
            "location": "一号仓库 A 区",
            "description": "米面杂粮等主食储备，用于社区食堂和应急餐食。",
            "status": Resource.Status.ACTIVE,
            "unit": Resource.Unit.KG,
            "replenishment_method": Resource.ReplenishmentMethod.PURCHASE,
            "loss_rate": Decimal("0.02000"),
            "warning_threshold": Decimal("600"),
            "shortage_impact": {"satisfaction_delta": -12, "conflict_risk_delta": 16},
        },
        {
            "resource_id": "res-water",
            "name": "生活饮用水",
            "resource_type": Resource.ResourceType.WATER,
            "location": "水站与地下储水罐",
            "description": "饮用水和基础生活用水储备。",
            "status": Resource.Status.ACTIVE,
            "unit": Resource.Unit.LITER,
            "replenishment_method": Resource.ReplenishmentMethod.PURCHASE,
            "loss_rate": Decimal("0.01000"),
            "warning_threshold": Decimal("18000"),
            "shortage_impact": {"satisfaction_delta": -20, "conflict_risk_delta": 22},
        },
        {
            "resource_id": "res-beds",
            "name": "可用床位",
            "resource_type": Resource.ResourceType.BEDS,
            "location": "临时住宿区",
            "description": "可立即安排入住或轮换休息的床位容量。",
            "status": Resource.Status.ACTIVE,
            "unit": Resource.Unit.SLOT,
            "replenishment_method": Resource.ReplenishmentMethod.MANUAL_ADJUSTMENT,
            "loss_rate": Decimal("0.00000"),
            "warning_threshold": Decimal("120"),
            "shortage_impact": {"satisfaction_delta": -18, "fatigue_recovery_delta": -15},
        },
        {
            "resource_id": "res-cleaning",
            "name": "清洁消杀用品",
            "resource_type": Resource.ResourceType.CLEANING_SUPPLIES,
            "location": "后勤间 B2",
            "description": "消毒液、手套、垃圾袋、拖布和公共区域清洁耗材。",
            "status": Resource.Status.ACTIVE,
            "unit": Resource.Unit.COUNT,
            "replenishment_method": Resource.ReplenishmentMethod.PURCHASE,
            "loss_rate": Decimal("0.03000"),
            "warning_threshold": Decimal("40"),
            "shortage_impact": {"task_completion_delta": -10, "conflict_risk_delta": 8},
        },
        {
            "resource_id": "res-medicine",
            "name": "常用药品与急救包",
            "resource_type": Resource.ResourceType.MEDICINE,
            "location": "医务角锁柜",
            "description": "退烧药、创可贴、消毒棉片和急救包等基础医疗物资。",
            "status": Resource.Status.ACTIVE,
            "unit": Resource.Unit.COUNT,
            "replenishment_method": Resource.ReplenishmentMethod.PURCHASE,
            "loss_rate": Decimal("0.01000"),
            "warning_threshold": Decimal("30"),
            "shortage_impact": {"health_risk_delta": 24, "conflict_risk_delta": 10},
        },
        {
            "resource_id": "res-tools",
            "name": "维修工具套装",
            "resource_type": Resource.ResourceType.TOOLS,
            "location": "维修间工具墙",
            "description": "螺丝刀、电钻、扳手、万用表等可重复使用工具。",
            "status": Resource.Status.ACTIVE,
            "unit": Resource.Unit.COUNT,
            "replenishment_method": Resource.ReplenishmentMethod.REUSE,
            "loss_rate": Decimal("0.04000"),
            "warning_threshold": Decimal("20"),
            "shortage_impact": {"repair_task_delay_delta": 18},
        },
        {
            "resource_id": "res-vegetables",
            "name": "新鲜蔬菜",
            "resource_type": Resource.ResourceType.VEGETABLES,
            "location": "冷藏柜与食堂暂存区",
            "description": "叶菜、根茎类和当日配送蔬菜，用于食堂配餐。",
            "status": Resource.Status.ACTIVE,
            "unit": Resource.Unit.KG,
            "replenishment_method": Resource.ReplenishmentMethod.PURCHASE,
            "loss_rate": Decimal("0.06000"),
            "warning_threshold": Decimal("180"),
            "shortage_impact": {"satisfaction_delta": -10, "nutrition_balance_delta": -14},
        },
        {
            "resource_id": "res-electricity",
            "name": "备用电力额度",
            "resource_type": Resource.ResourceType.ELECTRICITY,
            "location": "主配电柜与储能系统",
            "description": "可用于照明、冷藏、通信和基础设备运行的电力储备。",
            "status": Resource.Status.ACTIVE,
            "unit": Resource.Unit.KWH,
            "replenishment_method": Resource.ReplenishmentMethod.PRODUCTION,
            "loss_rate": Decimal("0.01500"),
            "warning_threshold": Decimal("900"),
            "shortage_impact": {"service_interrupt_delta": 20, "food_storage_risk_delta": 18},
        },
        {
            "resource_id": "res-materials",
            "name": "维修通用材料",
            "resource_type": Resource.ResourceType.MATERIAL,
            "location": "维修间材料架",
            "description": "水管接头、电线、扎带、密封胶、木板等通用维修材料。",
            "status": Resource.Status.ACTIVE,
            "unit": Resource.Unit.BAG,
            "replenishment_method": Resource.ReplenishmentMethod.PURCHASE,
            "loss_rate": Decimal("0.02000"),
            "warning_threshold": Decimal("12"),
            "shortage_impact": {"repair_task_delay_delta": 12, "facility_risk_delta": 8},
        },
        {
            "resource_id": "res-equipment",
            "name": "公用设备",
            "resource_type": Resource.ResourceType.EQUIPMENT,
            "location": "公共设备间",
            "description": "折叠桌、移动灯、对讲机、插线板等运营可调配设备。",
            "status": Resource.Status.ACTIVE,
            "unit": Resource.Unit.COUNT,
            "replenishment_method": Resource.ReplenishmentMethod.REUSE,
            "loss_rate": Decimal("0.02500"),
            "warning_threshold": Decimal("25"),
            "shortage_impact": {"event_capacity_delta": -10, "task_completion_delta": -6},
        },
        {
            "resource_id": "res-warehouse-capacity",
            "name": "仓储可用容量",
            "resource_type": Resource.ResourceType.WAREHOUSE_CAPACITY,
            "location": "一号仓库与临时周转区",
            "description": "扣除安全通道、冷藏区和待检区后的可用仓储体积。",
            "status": Resource.Status.ACTIVE,
            "unit": Resource.Unit.CUBIC_METER,
            "replenishment_method": Resource.ReplenishmentMethod.MANUAL_ADJUSTMENT,
            "loss_rate": Decimal("0.00000"),
            "warning_threshold": Decimal("220"),
            "shortage_impact": {"procurement_delay_delta": 16, "stock_rotation_delta": -12},
        },
        {
            "resource_id": "res-training-room",
            "name": "培训与会议空间",
            "resource_type": Resource.ResourceType.ROOM,
            "location": "社区中心二层",
            "description": "可用于成员培训、协调会议、临时面试和申诉调解的房间。",
            "status": Resource.Status.ACTIVE,
            "unit": Resource.Unit.COUNT,
            "replenishment_method": Resource.ReplenishmentMethod.MANUAL_ADJUSTMENT,
            "loss_rate": Decimal("0.00000"),
            "warning_threshold": Decimal("1"),
            "shortage_impact": {"training_delay_delta": 12, "governance_queue_delta": 8},
        },
    ]
    return resources


_DEMO_STOCK_OVERRIDES = {
    "res-cash":       {"current_stock": Decimal("9000000"), "daily_consumption_estimate": Decimal("0")},
    "res-grain":      {"current_stock": Decimal("1250"),   "daily_consumption_estimate": Decimal("180")},
    "res-water":      {"current_stock": Decimal("42000"),  "daily_consumption_estimate": Decimal("8500")},
    "res-beds":       {"current_stock": Decimal("142"),    "daily_consumption_estimate": Decimal("100")},
    "res-cleaning":   {"current_stock": Decimal("86"),     "daily_consumption_estimate": Decimal("14")},
    "res-medicine":   {"current_stock": Decimal("18"),     "daily_consumption_estimate": Decimal("6")},
    "res-tools":      {"current_stock": Decimal("36"),     "daily_consumption_estimate": Decimal("4")},
    "res-vegetables": {"current_stock": Decimal("320"),    "daily_consumption_estimate": Decimal("75")},
    "res-electricity":{"current_stock": Decimal("2600"),   "daily_consumption_estimate": Decimal("420")},
    "res-materials":  {"current_stock": Decimal("24"),     "daily_consumption_estimate": Decimal("3")},
    "res-equipment":  {"current_stock": Decimal("58"),     "daily_consumption_estimate": Decimal("2")},
    "res-warehouse-capacity": {"current_stock": Decimal("680"), "daily_consumption_estimate": Decimal("35")},
    "res-training-room": {"current_stock": Decimal("3"),   "daily_consumption_estimate": Decimal("1")},
}


def _apply_stock_overrides(base_specs: list[dict], overrides: dict) -> list[dict]:
    result = []
    for spec in base_specs:
        item = deepcopy(spec)
        override = overrides.get(item["resource_id"], {})
        item["current_stock"] = override.get("current_stock", Decimal("0"))
        item["daily_consumption_estimate"] = override.get("daily_consumption_estimate", Decimal("0"))
        result.append(item)
    return result


def demo_resource_specs():
    """Resource specs with demo stock levels (non-zero inventory)."""
    return _apply_stock_overrides(base_resource_specs(), _DEMO_STOCK_OVERRIDES)


def zero_start_resource_specs():
    """Resource specs for zero-start: full catalog, all stock = Decimal('0').

    Daily consumption estimates are kept so that consuming extensions
    (e.g. 'days until depletion') can still derive meaningful numbers.
    """
    zero_overrides = {}
    for base in base_resource_specs():
        rid = base["resource_id"]
        demo = _DEMO_STOCK_OVERRIDES.get(rid, {})
        zero_overrides[rid] = {
            "current_stock": Decimal("0"),
            "daily_consumption_estimate": demo.get("daily_consumption_estimate", Decimal("0")),
        }
    return _apply_stock_overrides(base_resource_specs(), zero_overrides)


def resource_specs():
    """Backward-compatible alias for demo_resource_specs."""
    return demo_resource_specs()
