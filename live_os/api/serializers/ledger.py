"""Credit ledger contract serializers."""

from __future__ import annotations

from typing import Any

from core.models import LedgerEntry

from .base import drop_none, encode_value


def ledger_entry_to_contract(entry: LedgerEntry) -> dict[str, Any]:
    return drop_none(
        {
            "ledger_entry_id": entry.ledger_entry_id,
            "member_no": entry.member.member_no,
            "amount": entry.amount,
            "entry_type": entry.entry_type,
            "reason": entry.reason,
            "related_task_id": entry.related_task_id,
            "related_event_id": entry.related_event_id,
            "rule_version": entry.rule_version,
            "created_at": encode_value(entry.created_at),
            "created_by": entry.created_by,
            "reviewer": entry.reviewer,
            "status": entry.status,
            "reverses_entry_id": entry.reverses_entry_id,
            "system_event_id": entry.system_event_id,
            "system_event_seq": entry.system_event.seq if entry.system_event_id else None,
            "metadata": entry.metadata,
        }
    )
