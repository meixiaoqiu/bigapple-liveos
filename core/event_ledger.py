"""Unified append-only system event ledger and hash-chain verification."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from django.db import IntegrityError, router, transaction
from django.utils import timezone

from .models import Member, RoleAssignment, SystemEvent


def _json_default(value: Any) -> str:
    return str(value)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default)


def hash_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def event_hash_payload(
    *,
    seq: int,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    actor_member_id: str | None,
    actor_role_assignment_id: int | None,
    payload_hash: str,
    prev_hash: str,
) -> dict[str, Any]:
    return {
        "seq": seq,
        "event_type": event_type,
        "aggregate_type": aggregate_type,
        "aggregate_id": aggregate_id,
        "actor_member_id": actor_member_id,
        "actor_role_assignment_id": actor_role_assignment_id,
        "payload_hash": payload_hash,
        "prev_hash": prev_hash,
    }


def compute_event_hash(
    *,
    seq: int,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    actor_member_id: str | None,
    actor_role_assignment_id: int | None,
    payload_hash: str,
    prev_hash: str,
) -> str:
    return hash_json(
        event_hash_payload(
            seq=seq,
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            actor_member_id=actor_member_id,
            actor_role_assignment_id=actor_role_assignment_id,
            payload_hash=payload_hash,
            prev_hash=prev_hash,
        )
    )


def append_event(
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    actor_member: Member | None = None,
    actor_role_assignment: RoleAssignment | None = None,
    payload_json: dict[str, Any] | None = None,
    occurred_at=None,
) -> SystemEvent:
    """Append one immutable system event to the shared hash chain."""

    payload = payload_json or {}
    db_alias = router.db_for_write(SystemEvent)
    last_error: IntegrityError | None = None
    for _attempt in range(3):
        try:
            with transaction.atomic(using=db_alias):
                latest = SystemEvent.objects.using(db_alias).select_for_update().order_by("-seq").first()
                seq = 1 if latest is None else latest.seq + 1
                prev_hash = "" if latest is None else latest.event_hash
                payload_hash = hash_json(payload)
                event_hash = compute_event_hash(
                    seq=seq,
                    event_type=event_type,
                    aggregate_type=aggregate_type,
                    aggregate_id=aggregate_id,
                    actor_member_id=actor_member.pk if actor_member else None,
                    actor_role_assignment_id=actor_role_assignment.pk if actor_role_assignment else None,
                    payload_hash=payload_hash,
                    prev_hash=prev_hash,
                )
                event = SystemEvent(
                    seq=seq,
                    event_type=event_type,
                    aggregate_type=aggregate_type,
                    aggregate_id=aggregate_id,
                    actor_member=actor_member,
                    actor_role_assignment=actor_role_assignment,
                    payload_json=payload,
                    payload_hash=payload_hash,
                    prev_hash=prev_hash,
                    event_hash=event_hash,
                    occurred_at=occurred_at or timezone.now(),
                )
                event._allow_append = True
                event.save(using=db_alias, force_insert=True)
                return event
        except IntegrityError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise RuntimeError("Failed to append system event.")


def verify_event_chain() -> bool:
    """Return False when any system event payload or chain hash is inconsistent."""

    expected_prev_hash = ""
    expected_seq = 1
    for event in SystemEvent.objects.order_by("seq"):
        if event.seq != expected_seq:
            return False
        if event.prev_hash != expected_prev_hash:
            return False
        expected_payload_hash = hash_json(event.payload_json)
        if event.payload_hash != expected_payload_hash:
            return False
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
        if event.event_hash != expected_event_hash:
            return False
        expected_prev_hash = event.event_hash
        expected_seq += 1
    return True
