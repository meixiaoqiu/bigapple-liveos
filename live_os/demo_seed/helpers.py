"""Shared helpers for idempotent demo seed data."""

from __future__ import annotations

from typing import Any

from core.event_ledger import append_event
from core.event_payloads import actor_member_from_ref, ledger_entry_event_type, ledger_entry_payload
from core.models import LedgerEntry

RULE_VERSION = "ruleset-v0.1.0"


def actor(actor_id: str, display_name: str, actor_type: str = "human_member") -> dict[str, str]:
    return {
        "actor_id": actor_id,
        "actor_type": actor_type,
        "display_name": display_name,
    }


def upsert(model: Any, lookup: dict[str, Any], defaults: dict[str, Any]) -> tuple[Any, bool]:
    obj, created = model.objects.update_or_create(**lookup, defaults=defaults)
    return obj, created


def ensure_ledger_entry_system_event(entry: LedgerEntry) -> LedgerEntry:
    if entry.system_event_id:
        return entry
    event = append_event(
        event_type=ledger_entry_event_type(entry),
        aggregate_type="LedgerEntry",
        aggregate_id=entry.pk,
        actor_member=actor_member_from_ref(entry.created_by),
        payload_json=ledger_entry_payload(entry),
        occurred_at=entry.created_at,
    )
    entry.system_event = event
    entry.save(update_fields=["system_event"])
    return entry
