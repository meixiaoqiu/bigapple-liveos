"""Contribution ledger services."""

from __future__ import annotations

from django.db.models import Sum
from django.utils import timezone

from .db import atomic_for_model
from .event_ledger import append_event
from .event_payloads import actor_member_from_ref, ledger_entry_event_type, ledger_entry_payload
from .models import LedgerEntry, Member, Task


@atomic_for_model(LedgerEntry)
def create_ledger_entry(
    *,
    ledger_entry_id: str,
    member: Member,
    amount: int,
    entry_type: str,
    reason: str,
    rule_version: str,
    created_by: dict,
    related_task: Task | None = None,
    related_event_id: str = "",
    reviewer: dict | None = None,
    status: str = LedgerEntry.Status.POSTED,
    reverses_entry: LedgerEntry | None = None,
    metadata: dict | None = None,
    created_at=None,
) -> LedgerEntry:
    """Append a contribution ledger row and mirror it into the unified event ledger."""

    now = created_at or timezone.now()
    entry = LedgerEntry.objects.create(
        ledger_entry_id=ledger_entry_id,
        member=member,
        amount=amount,
        entry_type=entry_type,
        reason=reason,
        related_task=related_task,
        related_event_id=related_event_id,
        rule_version=rule_version,
        created_at=now,
        created_by=created_by,
        reviewer=reviewer or {},
        status=status,
        reverses_entry=reverses_entry,
        metadata=metadata or {},
    )
    actor_member = actor_member_from_ref(created_by) or actor_member_from_ref(reviewer)
    event = append_event(
        event_type=ledger_entry_event_type(entry),
        aggregate_type="LedgerEntry",
        aggregate_id=entry.pk,
        actor_member=actor_member,
        payload_json=ledger_entry_payload(entry),
        occurred_at=now,
    )
    entry.system_event = event
    entry.save(update_fields=["system_event"])
    return entry


@atomic_for_model(LedgerEntry)
def reverse_ledger_entry(
    *,
    entry: LedgerEntry,
    reason: str,
    created_by: dict,
    ledger_entry_id: str | None = None,
    created_at=None,
) -> LedgerEntry:
    """Append a reversing ledger row without editing the original historical row."""

    entry = LedgerEntry.objects.select_for_update().select_related("member", "related_task").get(
        ledger_entry_id=entry.ledger_entry_id
    )
    reversal_id = ledger_entry_id or f"ledger-reversal-{uuid4().hex[:12]}"
    return create_ledger_entry(
        ledger_entry_id=reversal_id,
        member=entry.member,
        amount=-entry.amount,
        entry_type=LedgerEntry.EntryType.REVERSAL,
        reason=reason,
        related_task=entry.related_task,
        related_event_id=entry.related_event_id,
        rule_version=entry.rule_version,
        created_by=created_by,
        reviewer=created_by,
        status=LedgerEntry.Status.POSTED,
        reverses_entry=entry,
        metadata={"reverses_entry_id": entry.pk},
        created_at=created_at,
    )


def ledger_balance_for_member(member: Member) -> int:
    """Compute the current point balance from posted contribution ledger rows."""

    return (
        LedgerEntry.objects.filter(member=member, status=LedgerEntry.Status.POSTED).aggregate(total=Sum("amount"))[
            "total"
        ]
        or 0
    )
