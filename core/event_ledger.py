"""Unified append-only system event ledger and hash-chain verification."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from django.db import IntegrityError, router, transaction
from django.utils import timezone

from .models import Member, RoleAssignment, SystemEvent

# Public ledger schema identifier attached to every v2 SystemEvent.payload_json.
PUBLIC_LEDGER_SCHEMA = "liveos.system-event.public.v1"

# Keys that MUST NOT appear anywhere in a v2 payload except inside private_commitments[].name.
PUBLIC_LEDGER_DENYLIST_KEYS: frozenset[str] = frozenset({
    # PII / credentials
    "contact",
    "contact_name",
    "contact_info",
    "email",
    "phone",
    "wechat",
    "username",
    "account_username",
    "account_user_id",
    "password",
    "password1",
    "password2",
    # internal member identity
    "user_id",
    "member_id",
    "member_no",
    "target_member_id",
    "target_member_no",
    "voter_member_id",
    "voter_member_no",
    "actor_member_id",
    "assignee_member_id",
    "assignee_member_no",
    "claimant_member_id",
    "claimant_member_no",
    "respondent_member_id",
    "respondent_member_no",
    "proposer_member_id",
    "proposer_member_no",
    # internal DB primary keys
    "proposal_id",
    "role_id",
    "organization_id",
    "role_assignment_id",
    "proposer_role_assignment_id",
    "voter_role_assignment_id",
    "granted_by_id",
    "revoked_by_id",
    "ledger_entry_id",
    "system_event_id",
    "related_event_id",
    "related_ledger_entry_id",
    "related_task_id",
    # raw personal / operational details
    "applicant_name",
    "applicant_name_raw",
    "requested_member_no",
    "linked_member_id",
    "display_name",
    "display_name_raw",
    "assigned_member_display_name",
    # operational actors / notes
    "actor",
    "operator",
    "handler",
    "reviewer",
    "created_by",
    "reviewed_by",
    "decided_by",
    # opaque blobs
    "metadata",
    "payload",
    "result",
    "execution_result",
    "facts",
    "evidence_refs",
    # raw internal reasons
    "reason_raw",
    "resolution_raw",
})


def _json_default(value: Any) -> str:
    return str(value)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default)


def hash_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# v2 hash input — publicly verifiable, no internal DB primary keys
# ---------------------------------------------------------------------------

def event_hash_payload_v2(
    *,
    seq: int,
    event_type: str,
    aggregate_type: str,
    subject_ref: str,
    payload_hash: str,
    prev_hash: str,
) -> dict[str, Any]:
    """Publicly recomputable hash input (v2).

    Uses *subject_ref* (from ``payload_json.subject.ref``) instead of
    the internal DB column ``aggregate_id`` so the input is fully public.
    """
    return {
        "schema": "liveos.system-event-hash.v2",
        "seq": seq,
        "event_type": event_type,
        "aggregate_type": aggregate_type,
        "subject_ref": subject_ref,
        "payload_hash": payload_hash,
        "prev_hash": prev_hash,
    }


def compute_event_hash_v2(
    *,
    seq: int,
    event_type: str,
    aggregate_type: str,
    subject_ref: str,
    payload_hash: str,
    prev_hash: str,
) -> str:
    """Compute event_hash using v2 public inputs."""
    return hash_json(
        event_hash_payload_v2(
            seq=seq,
            event_type=event_type,
            aggregate_type=aggregate_type,
            subject_ref=subject_ref,
            payload_hash=payload_hash,
            prev_hash=prev_hash,
        )
    )


# ---------------------------------------------------------------------------
# Legacy v1 (kept for reading old records in verify_event_chain)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# v2 payload safety validation
# ---------------------------------------------------------------------------

def validate_public_ledger_payload(payload: dict[str, Any]) -> None:
    """Reject v2 SystemEvent payloads that expose private keys outside private_commitments.

    Raises ValueError with a path-qualified message on first violation.
    """

    if not isinstance(payload, dict):
        raise ValueError("SystemEvent.payload_json must be a dict")

    schema = payload.get("schema", "")
    if schema != PUBLIC_LEDGER_SCHEMA:
        raise ValueError(f"SystemEvent.payload_json schema must be '{PUBLIC_LEDGER_SCHEMA}'")

    subject = payload.get("subject")
    if not isinstance(subject, dict):
        raise ValueError("SystemEvent.payload_json.subject must be a dict")
    for req in ("type", "ref", "label"):
        if not str(subject.get(req, "")).strip():
            raise ValueError(f"SystemEvent.payload_json.subject.{req} is required and must be non-empty")

    for req in ("action", "stage", "summary"):
        if not str(payload.get(req, "")).strip():
            raise ValueError(f"SystemEvent.payload_json.{req} is required and must be non-empty")

    facts = payload.get("public_facts")
    if not isinstance(facts, dict):
        raise ValueError("SystemEvent.payload_json.public_facts must be a dict")

    commitments = payload.get("private_commitments")
    if not isinstance(commitments, list):
        raise ValueError("SystemEvent.payload_json.private_commitments must be a list")

    _validate_node(payload, "payload_json")


def _validate_node(node: Any, path: str, *, inside_commitments: bool = False) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            child_path = f"{path}.{key}" if path else key
            if inside_commitments:
                if key not in ("name", "present", "reason"):
                    raise ValueError(f"SystemEvent.{child_path}: unsupported key in private_commitments item")
                if isinstance(value, (dict, list)):
                    raise ValueError(f"SystemEvent.{child_path}: nested structure not allowed in private_commitments")
                continue
            if key == "private_commitments":
                if isinstance(value, list):
                    for idx, item in enumerate(value):
                        _validate_node(item, f"{child_path}[{idx}]", inside_commitments=True)
                continue
            if key in PUBLIC_LEDGER_DENYLIST_KEYS:
                raise ValueError(f"SystemEvent.{child_path} is not public-safe (denylist key: {key})")
            if isinstance(value, (dict, list)):
                _validate_node(value, child_path)
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            _validate_node(item, f"{path}[{idx}]")


# ---------------------------------------------------------------------------
# append_event
# ---------------------------------------------------------------------------

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
    """Append one immutable system event to the shared hash chain (v2)."""

    payload = payload_json or {}
    payload_schema = payload.get("schema", "")
    if payload_schema != PUBLIC_LEDGER_SCHEMA:
        raise ValueError(
            f"SystemEvent.payload_json must use schema '{PUBLIC_LEDGER_SCHEMA}', "
            f"got '{payload_schema}'. "
            "Use core.event_payloads helpers to build compliant payloads."
        )
    validate_public_ledger_payload(payload)
    subject_ref = str((payload.get("subject") or {}).get("ref", aggregate_id))

    db_alias = router.db_for_write(SystemEvent)
    last_error: IntegrityError | None = None
    for _attempt in range(3):
        try:
            with transaction.atomic(using=db_alias):
                latest = SystemEvent.objects.using(db_alias).select_for_update().order_by("-seq").first()
                seq = 1 if latest is None else latest.seq + 1
                prev_hash = "" if latest is None else latest.event_hash
                payload_hash = hash_json(payload)
                event_hash = compute_event_hash_v2(
                    seq=seq,
                    event_type=event_type,
                    aggregate_type=aggregate_type,
                    subject_ref=subject_ref,
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


# ---------------------------------------------------------------------------
# chain verification
# ---------------------------------------------------------------------------

def verify_event_chain() -> bool:
    """Return False when any system event payload or chain hash is inconsistent.

    V2 events are verified with *compute_event_hash_v2*;
    legacy events (no ``schema`` in payload_json) are verified with v1.
    """
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

        payload = event.payload_json or {}
        is_v2 = payload.get("schema") == PUBLIC_LEDGER_SCHEMA

        if is_v2:
            subject_ref = str((payload.get("subject") or {}).get("ref", event.aggregate_id))
            expected_event_hash = compute_event_hash_v2(
                seq=event.seq,
                event_type=event.event_type,
                aggregate_type=event.aggregate_type,
                subject_ref=subject_ref,
                payload_hash=event.payload_hash,
                prev_hash=event.prev_hash,
            )
        else:
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
