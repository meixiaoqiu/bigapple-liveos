"""Public projection helpers for observer event pages."""

from __future__ import annotations

from typing import Any

from django.db.models import Q

from core.event_ledger import compute_event_hash, hash_json
from core.event_payloads import public_member_label
from core.models import Event, SystemEvent
from live_os.api.serializers.events import public_event_summary

# Whitelist keys allowed in public payload summary.
_PUBLIC_PAYLOAD_WHITELIST: frozenset[str] = frozenset([
    "application_id",
    "proposal_no",
    "task_id",
    "resource_id",
    "dispute_id",
    "status",
    "action_type",
    "source",
    "stage",
    "role_gap",
    "role_gap_label",
    "public_applicant_label",
    "public_member_label",
    "reason",
    "title",
    "summary",
])

# Keys that must never appear in public payload output.
_PUBLIC_PAYLOAD_DENYLIST: frozenset[str] = frozenset([
    "contact",
    "contact_name",
    "email",
    "phone",
    "wechat",
    "username",
    "account_username",
    "account_user_id",
    "password",
    "password1",
    "password2",
    "user_id",
    "member_id",
    "target_member_id",
    "voter_member_id",
    "actor_member_id",
])

_TRUNCATE_KEYS: frozenset[str] = frozenset(["reason", "summary"])


def _short_hash(value: str) -> str:
    return value[:12] + "…" if value else ""


def _sanitize_value(key: str, value: Any) -> Any:
    """Return a sanitised version of a single payload value."""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        if key in _TRUNCATE_KEYS and len(stripped) > 200:
            return stripped[:200] + "…"
        return stripped
    # Conservative: hide lists/dicts unless the key is explicitly allow-listed.
    if isinstance(value, (list, dict)):
        return "[已隐藏]"
    return value


def public_event_payload(event: Event) -> dict[str, Any]:
    """Extract a sanitised public summary from an observer-visible Event."""
    raw: dict[str, Any] = event.payload or {}
    result: dict[str, Any] = {}
    for key, value in raw.items():
        if key in _PUBLIC_PAYLOAD_DENYLIST:
            continue
        if key not in _PUBLIC_PAYLOAD_WHITELIST:
            continue
        sanitised = _sanitize_value(key, value)
        if sanitised is not None:
            result[key] = sanitised
    return result


def public_event_row(event: Event) -> dict[str, Any]:
    """A single row/card for the public community event stream."""
    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "event_type_display": event.get_event_type_display(),
        "severity": event.severity,
        "severity_display": event.get_severity_display(),
        "title": event.title,
        "summary": public_event_summary(event),
        "occurred_at": event.occurred_at,
        "generated_by": event.get_generated_by_display(),
        "simulation_day": event.simulation_day,
        "related_task_id": event.related_task_id,
        "related_dispute_id": event.related_dispute_id,
        "detail_url": f"/observer/events/{event.event_id}/",
    }


def _system_event_filter_for_public_event(event: Event) -> Q:
    payload = event.payload or {}
    query = Q()

    application_id = str(payload.get("application_id") or "").strip()
    if application_id:
        query |= Q(aggregate_type="MemberApplication", aggregate_id=application_id)
        query |= Q(payload_json__application_id=application_id)

    proposal_no = str(payload.get("proposal_no") or "").strip()
    if proposal_no:
        query |= Q(payload_json__proposal_no=proposal_no)

    proposal_id = str(payload.get("proposal_id") or "").strip()
    if proposal_id:
        query |= Q(aggregate_type="Proposal", aggregate_id=proposal_id)
        query |= Q(payload_json__proposal_id=proposal_id)

    task_id = str(payload.get("task_id") or event.related_task_id or "").strip()
    if task_id:
        query |= Q(aggregate_type="Task", aggregate_id=task_id)
        query |= Q(payload_json__task_id=task_id)

    resource_id = str(payload.get("resource_id") or "").strip()
    if resource_id:
        query |= Q(aggregate_type="Resource", aggregate_id=resource_id)
        query |= Q(payload_json__resource_id=resource_id)

    dispute_id = str(payload.get("dispute_id") or event.related_dispute_id or "").strip()
    if dispute_id:
        query |= Q(aggregate_type="Dispute", aggregate_id=dispute_id)
        query |= Q(payload_json__dispute_id=dispute_id)

    return query


def public_system_event_proof_rows_for_event(event: Event, *, limit: int = 8) -> list[dict[str, Any]]:
    """Return hash-chain proof rows that appear related to a public Event."""
    query = _system_event_filter_for_public_event(event)
    if not query:
        return []
    events = SystemEvent.objects.filter(query).order_by("seq")[:limit]
    return [
        {
            "seq": item.seq,
            "event_type_display": item.get_event_type_display(),
            "occurred_at": item.occurred_at,
            "event_hash_short": _short_hash(item.event_hash),
            "chain_valid": system_event_chain_check(item)["chain_valid"],
        }
        for item in events
    ]


def public_event_detail(event: Event) -> dict[str, Any]:
    """Full public detail for a community event."""
    return {
        **public_event_row(event),
        "payload_public": public_event_payload(event),
        "audit_events": public_system_event_proof_rows_for_event(event),
    }


def _sensitive_aggregate(aggregate_type: str, aggregate_id: str) -> str:
    """Hide internal primary keys for identity aggregate types."""
    if aggregate_type in ("Member", "User"):
        return "已隐藏"
    return aggregate_id


def _actor_label(event: SystemEvent) -> str:
    """Return a de-identified label for the event actor."""
    if event.actor_member is None:
        return ""
    return public_member_label(
        event.actor_member.display_name,
        event.actor_member.member_no,
    )


def public_system_event_payload(event: SystemEvent) -> dict[str, Any]:
    """Extract a sanitised public summary from *event.payload_json*.

    - Only whitelist keys are shown.
    - Denylist keys are never shown.
    - Strings are stripped; *reason* / *summary* are truncated at 200 chars.
    - None values and empty strings are dropped.
    - Lists and dicts are hidden unless the key is in the whitelist.
    """
    raw: dict[str, Any] = event.payload_json or {}
    result: dict[str, Any] = {}
    for key, value in raw.items():
        if key in _PUBLIC_PAYLOAD_DENYLIST:
            continue
        if key not in _PUBLIC_PAYLOAD_WHITELIST:
            continue
        sanitised = _sanitize_value(key, value)
        if sanitised is not None:
            result[key] = sanitised
    return result


def public_system_event_row(event: SystemEvent) -> dict[str, Any]:
    """A single row for the public hash-chain ledger list."""
    return {
        "seq": event.seq,
        "event_type": event.event_type,
        "event_type_display": event.get_event_type_display(),
        "aggregate_type": event.aggregate_type,
        "aggregate_id": _sensitive_aggregate(event.aggregate_type, event.aggregate_id),
        "actor_label": _actor_label(event),
        "occurred_at": event.occurred_at,
        "event_hash_short": _short_hash(event.event_hash),
        "detail_url": f"/observer/event-ledger/{event.seq}/",
        "detail_name": "observer-event-ledger-detail",
    }


def public_system_event_detail(event: SystemEvent) -> dict[str, Any]:
    """Full public detail for a single SystemEvent."""
    chain = system_event_chain_check(event)
    return {
        "seq": event.seq,
        "event_type": event.event_type,
        "event_type_display": event.get_event_type_display(),
        "aggregate_type": event.aggregate_type,
        "aggregate_id": _sensitive_aggregate(event.aggregate_type, event.aggregate_id),
        "actor_label": _actor_label(event),
        "occurred_at": event.occurred_at,
        "payload_hash": event.payload_hash,
        "prev_hash": event.prev_hash,
        "event_hash": event.event_hash,
        "payload_public": public_system_event_payload(event),
        "chain_valid": chain["chain_valid"],
        "payload_hash_valid": chain["payload_hash_valid"],
        "prev_hash_valid": chain["prev_hash_valid"],
        "event_hash_valid": chain["event_hash_valid"],
        "has_prev_event": chain.get("has_prev_event", False),
    }


def system_event_chain_check(event: SystemEvent) -> dict[str, Any]:
    """Perform single-event hash-chain verification.

    Checks:
    1. *payload_hash* matches ``hash_json(event.payload_json)``.
    2. *prev_hash* matches the *event_hash* of the preceding event (seq - 1).
    3. *event_hash* matches the recomputed hash.
    """
    payload_hash_valid = hash_json(event.payload_json or {}) == event.payload_hash

    prev = SystemEvent.objects.filter(seq=event.seq - 1).first()
    has_prev_event = prev is not None
    if has_prev_event:
        prev_hash_valid = event.prev_hash == prev.event_hash
    else:
        # seq == 1: prev_hash must be empty.
        prev_hash_valid = event.prev_hash == ""

    expected_event_hash = compute_event_hash(
        seq=event.seq,
        event_type=event.event_type,
        aggregate_type=event.aggregate_type,
        aggregate_id=event.aggregate_id,
        actor_member_id=event.actor_member_id,
        actor_role_assignment_id=event.actor_role_assignment_id,
        payload_hash=event.payload_hash,
        prev_hash=event.prev_hash,
    )
    event_hash_valid = event.event_hash == expected_event_hash

    return {
        "payload_hash_valid": payload_hash_valid,
        "prev_hash_valid": prev_hash_valid,
        "event_hash_valid": event_hash_valid,
        "chain_valid": payload_hash_valid and prev_hash_valid and event_hash_valid,
        "has_prev_event": has_prev_event,
    }
