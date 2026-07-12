"""Resource adjustment services."""

from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

from .db import atomic_for_model
from .event_ledger import append_event
from .event_payloads import actor_member_from_ref, resource_adjustment_payload
from .exceptions import DomainError
from .id_generators import generate_resource_event_id, generate_resource_transaction_id
from .models import Event, Resource, ResourceTransaction, SystemEvent


@atomic_for_model(Resource)
def record_resource_adjustment(
    *,
    resource: Resource,
    delta: Decimal,
    operator: dict,
    reason: str,
    replenishment_method: str,
    simulation_day: int,
) -> tuple[Resource, Event]:
    """Record an operator resource adjustment and append a resource event."""

    cleaned_reason = reason.strip()
    valid_methods = {value for value, _label in Resource.ReplenishmentMethod.choices}
    if not cleaned_reason:
        raise DomainError("资源调整原因不能为空。")
    if replenishment_method not in valid_methods:
        raise DomainError("资源补充方式无效。")

    resource = Resource.objects.select_for_update().get(resource_id=resource.resource_id)
    old_stock = resource.current_stock
    new_stock = old_stock + delta
    if new_stock < 0:
        raise DomainError("资源库存不能调整为负数。")

    now = timezone.now()
    resource.current_stock = new_stock
    resource.replenishment_method = replenishment_method
    resource.updated_at = now
    adjustment = {
        "source": "control_resource_adjustment",
        "operator": operator,
        "reason": cleaned_reason,
        "delta": str(delta),
        "old_stock": str(old_stock),
        "new_stock": str(new_stock),
        "recorded_at": now.isoformat(),
    }
    resource.metadata = {
        **resource.metadata,
        "last_adjustment": adjustment,
    }
    resource.save(update_fields=["current_stock", "replenishment_method", "updated_at", "metadata"])
    transaction = ResourceTransaction.objects.create(
        transaction_id=generate_resource_transaction_id(),
        resource=resource,
        transaction_type=_transaction_type_for_delta(delta),
        quantity_delta=delta,
        stock_before=old_stock,
        stock_after=new_stock,
        reason=cleaned_reason,
        operator=operator,
        occurred_at=now,
        created_at=now,
        metadata={
            "source": "control_resource_adjustment",
            "replenishment_method": replenishment_method,
        },
    )

    warning = new_stock <= resource.warning_threshold
    resource_label = resource.get_resource_type_display()
    unit_label = resource.get_unit_display()
    event = Event.objects.create(
        event_id=generate_resource_event_id(),
        event_type=Event.EventType.RESOURCE,
        simulation_day=simulation_day,
        severity=Event.Severity.WARNING if warning else Event.Severity.INFO,
        title=f"{resource_label}库存调整",
        summary=f"{resource_label}库存从 {old_stock} {unit_label} 调整为 {new_stock} {unit_label}。{cleaned_reason}",
        involved_member_ids=[operator["actor_id"]] if operator.get("actor_id") else [],
        related_task=None,
        related_dispute_id="",
        occurred_at=now,
        generated_by=Event.GeneratedBy.HUMAN_OPERATOR,
        visibility=Event.Visibility.PUBLIC,
        payload={
            "resource_id": resource.resource_id,
            "resource_type": resource.resource_type,
            "unit": resource.unit,
            "old_stock": str(old_stock),
            "delta": str(delta),
            "new_stock": str(new_stock),
            "warning_threshold": str(resource.warning_threshold),
            "is_warning": warning,
            "replenishment_method": replenishment_method,
            "reason": cleaned_reason,
            "operator": operator,
        },
    )
    system_event = append_event(
        event_type=SystemEvent.EventType.RESOURCE_ADJUSTED,
        aggregate_type="Resource",
        aggregate_id=resource.pk,
        actor_member=actor_member_from_ref(operator),
        payload_json=resource_adjustment_payload(
            resource,
            actor=operator,
            old_stock=old_stock,
            delta=delta,
            reason=cleaned_reason,
            warning=warning,
            transaction_id=transaction.transaction_id,
        ),
        occurred_at=now,
    )
    transaction.system_event = system_event
    transaction.save(update_fields=["system_event"])
    return resource, event


def _transaction_type_for_delta(delta: Decimal) -> str:
    if delta > 0:
        return ResourceTransaction.TransactionType.INBOUND
    if delta < 0:
        return ResourceTransaction.TransactionType.OUTBOUND
    return ResourceTransaction.TransactionType.MANUAL_ADJUSTMENT
