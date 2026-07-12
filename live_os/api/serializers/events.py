"""Business event contract serializers."""

from __future__ import annotations

from typing import Any

from core.models import Event

from .base import drop_none, encode_value


def event_to_contract(event: Event) -> dict[str, Any]:
    return drop_none(
        {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "simulation_day": event.simulation_day,
            "severity": event.severity,
            "title": event.title,
            "summary": event.summary,
            "involved_member_ids": event.involved_member_ids,
            "related_task_id": event.related_task_id,
            "related_dispute_id": event.related_dispute_id,
            "occurred_at": encode_value(event.occurred_at),
            "generated_by": event.generated_by,
            "visibility": event.visibility,
            "payload": event.payload,
        }
    )


def public_event_to_contract(event: Event) -> dict[str, Any]:
    return drop_none(
        {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "simulation_day": event.simulation_day,
            "severity": event.severity,
            "title": event.title,
            "summary": public_event_summary(event),
            "related_task_id": event.related_task_id,
            "occurred_at": encode_value(event.occurred_at),
            "generated_by": event.generated_by,
            "visibility": event.visibility,
        }
    )


def public_event_summary(event: Event) -> str:
    if event.generated_by == Event.GeneratedBy.HUMAN_OPERATOR:
        return event.title
    return event.summary
