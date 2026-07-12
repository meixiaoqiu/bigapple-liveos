"""Resource contract serializers."""

from __future__ import annotations

from typing import Any

from core.models import Resource

from .base import drop_none, encode_value


def resource_to_contract(resource: Resource) -> dict[str, Any]:
    return drop_none(
        {
            "resource_id": resource.resource_id,
            "resource_type": resource.resource_type,
            "unit": resource.unit,
            "current_stock": encode_value(resource.current_stock),
            "daily_consumption_estimate": encode_value(resource.daily_consumption_estimate),
            "replenishment_method": resource.replenishment_method,
            "loss_rate": encode_value(resource.loss_rate),
            "warning_threshold": encode_value(resource.warning_threshold),
            "shortage_impact": resource.shortage_impact,
            "updated_at": encode_value(resource.updated_at),
            "rule_version": resource.rule_version,
            "metadata": resource.metadata,
        }
    )


def public_resource_to_contract(resource: Resource) -> dict[str, Any]:
    return drop_none(
        {
            "resource_id": resource.resource_id,
            "resource_type": resource.resource_type,
            "unit": resource.unit,
            "current_stock": encode_value(resource.current_stock),
            "daily_consumption_estimate": encode_value(resource.daily_consumption_estimate),
            "replenishment_method": resource.replenishment_method,
            "loss_rate": encode_value(resource.loss_rate),
            "warning_threshold": encode_value(resource.warning_threshold),
            "shortage_impact": resource.shortage_impact,
            "updated_at": encode_value(resource.updated_at),
            "rule_version": resource.rule_version,
        }
    )
