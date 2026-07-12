"""Static resource demo seed specs."""

from __future__ import annotations

from decimal import Decimal

from core.models import Resource


def resource_specs():
    resources = [
        {
            "resource_id": "res-cash",
            "resource_type": Resource.ResourceType.CASH,
            "unit": Resource.Unit.YUAN,
            "current_stock": Decimal("9000000"),
            "daily_consumption_estimate": Decimal("0"),
            "replenishment_method": Resource.ReplenishmentMethod.MANUAL_ADJUSTMENT,
            "loss_rate": Decimal("0.00000"),
            "warning_threshold": Decimal("1000000"),
            "shortage_impact": {"plan_execution_delta": -40, "procurement_delay_delta": 30},
        },
        {
            "resource_id": "res-grain",
            "resource_type": Resource.ResourceType.GRAIN,
            "unit": Resource.Unit.KG,
            "current_stock": Decimal("1250"),
            "daily_consumption_estimate": Decimal("180"),
            "replenishment_method": Resource.ReplenishmentMethod.PURCHASE,
            "loss_rate": Decimal("0.02000"),
            "warning_threshold": Decimal("600"),
            "shortage_impact": {"satisfaction_delta": -12, "conflict_risk_delta": 16},
        },
        {
            "resource_id": "res-water",
            "resource_type": Resource.ResourceType.WATER,
            "unit": Resource.Unit.LITER,
            "current_stock": Decimal("42000"),
            "daily_consumption_estimate": Decimal("8500"),
            "replenishment_method": Resource.ReplenishmentMethod.PURCHASE,
            "loss_rate": Decimal("0.01000"),
            "warning_threshold": Decimal("18000"),
            "shortage_impact": {"satisfaction_delta": -20, "conflict_risk_delta": 22},
        },
        {
            "resource_id": "res-beds",
            "resource_type": Resource.ResourceType.BEDS,
            "unit": Resource.Unit.SLOT,
            "current_stock": Decimal("142"),
            "daily_consumption_estimate": Decimal("100"),
            "replenishment_method": Resource.ReplenishmentMethod.MANUAL_ADJUSTMENT,
            "loss_rate": Decimal("0.00000"),
            "warning_threshold": Decimal("120"),
            "shortage_impact": {"satisfaction_delta": -18, "fatigue_recovery_delta": -15},
        },
        {
            "resource_id": "res-cleaning",
            "resource_type": Resource.ResourceType.CLEANING_SUPPLIES,
            "unit": Resource.Unit.COUNT,
            "current_stock": Decimal("86"),
            "daily_consumption_estimate": Decimal("14"),
            "replenishment_method": Resource.ReplenishmentMethod.PURCHASE,
            "loss_rate": Decimal("0.03000"),
            "warning_threshold": Decimal("40"),
            "shortage_impact": {"task_completion_delta": -10, "conflict_risk_delta": 8},
        },
        {
            "resource_id": "res-medicine",
            "resource_type": Resource.ResourceType.MEDICINE,
            "unit": Resource.Unit.COUNT,
            "current_stock": Decimal("18"),
            "daily_consumption_estimate": Decimal("6"),
            "replenishment_method": Resource.ReplenishmentMethod.PURCHASE,
            "loss_rate": Decimal("0.01000"),
            "warning_threshold": Decimal("30"),
            "shortage_impact": {"health_risk_delta": 24, "conflict_risk_delta": 10},
        },
        {
            "resource_id": "res-tools",
            "resource_type": Resource.ResourceType.TOOLS,
            "unit": Resource.Unit.COUNT,
            "current_stock": Decimal("36"),
            "daily_consumption_estimate": Decimal("4"),
            "replenishment_method": Resource.ReplenishmentMethod.REUSE,
            "loss_rate": Decimal("0.04000"),
            "warning_threshold": Decimal("20"),
            "shortage_impact": {"repair_task_delay_delta": 18},
        },
    ]
    return resources
