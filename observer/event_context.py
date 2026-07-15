"""Public projection helpers for observer event pages."""

from __future__ import annotations

from typing import Any

from django.db.models import Q

from core.event_ledger import (
    PUBLIC_LEDGER_DENYLIST_KEYS,
    PUBLIC_LEDGER_SCHEMA,
    canonical_json,
    compute_event_hash,
    compute_event_hash_v2,
    event_hash_payload_v2,
    hash_json,
    validate_public_ledger_payload,
)
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
# Builds from the authoritative core denylist to prevent drift.
_PUBLIC_PAYLOAD_DENYLIST: frozenset[str] = frozenset(PUBLIC_LEDGER_DENYLIST_KEYS)

_TRUNCATE_KEYS: frozenset[str] = frozenset(["reason", "summary"])

_GENERIC_LABEL_MAP: dict[str, str] = {
    "application_id": "报名编号",
    "proposal_no": "提案编号",
    "task_id": "任务编号",
    "resource_id": "资源编号",
    "dispute_id": "申诉编号",
    "status": "状态",
    "action_type": "操作类型",
    "source": "来源",
    "stage": "阶段",
    "role_gap": "意向角色",
    "role_gap_label": "意向角色",
    "public_applicant_label": "报名者",
    "public_member_label": "成员",
    "reason": "原因",
    "title": "标题",
    "summary": "摘要",
}


def _short_hash(value: str) -> str:
    return value[:12] + "…" if value else ""


def _sanitize_value(key: str, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        if key in _TRUNCATE_KEYS and len(stripped) > 200:
            return stripped[:200] + "…"
        return stripped
    if isinstance(value, (list, dict)):
        return "[已隐藏]"
    return value


def public_event_payload(event: Event) -> dict[str, Any]:
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


def _is_member_application_event(event: Event) -> bool:
    payload = event.payload or {}
    if payload.get("source") == "member_application":
        return True
    if (event.event_id or "").startswith("member-application-"):
        return True
    if payload.get("application_id") and payload.get("stage") in {"submitted", "admitted", "rejected"}:
        return True
    return False


def _stage_display(stage: str) -> str:
    mapping = {
        "submitted": "已提交，进入治理表决",
        "admitted": "已通过准入，成为成员",
        "rejected": "未通过准入",
    }
    return mapping.get(stage, stage or "未公开")


def _member_application_semantic_summary(event: Event) -> list[dict[str, str]]:
    payload = event.payload or {}
    entries: list[dict[str, str]] = []
    entries.append({"label": "事项", "value": "成员报名"})
    applicant = (
        str(payload.get("public_applicant_label") or "").strip()
        or str(payload.get("public_member_label") or "").strip()
    )
    entries.append({"label": "报名者", "value": applicant or "未公开"})
    role = (
        str(payload.get("role_gap_label") or "").strip()
        or str(payload.get("role_gap") or "").strip()
    )
    entries.append({"label": "意向角色", "value": role or "未公开"})
    proposal_no = str(payload.get("proposal_no") or "").strip()
    entries.append({"label": "准入提案", "value": proposal_no or "未关联"})
    entries.append({"label": "阶段", "value": _stage_display(str(payload.get("stage") or ""))})
    entries.append({"label": "公开说明", "value": public_event_summary(event)})
    return entries


def _generic_semantic_summary(event: Event) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = [
        {"label": "事件类型", "value": event.get_event_type_display()},
        {"label": "严重程度", "value": event.get_severity_display()},
        {"label": "来源", "value": event.get_generated_by_display()},
    ]
    if event.related_task_id:
        entries.append({"label": "关联任务", "value": event.related_task_id})
    if event.related_dispute_id:
        entries.append({"label": "关联申诉", "value": event.related_dispute_id})
    for key, value in public_event_payload(event).items():
        label = _GENERIC_LABEL_MAP.get(key, key)
        entries.append({"label": label, "value": str(value)})
    return entries


def public_event_semantic_summary(event: Event) -> list[dict[str, str]]:
    if _is_member_application_event(event):
        return _member_application_semantic_summary(event)
    return _generic_semantic_summary(event)


def _system_event_filter_for_public_event(event: Event) -> Q:
    payload = event.payload or {}
    query = Q()
    application_id = str(payload.get("application_id") or "").strip()
    if application_id:
        query |= Q(aggregate_type="MemberApplication", aggregate_id=application_id)
        query |= Q(payload_json__public_facts__application_id=application_id)
        query |= Q(payload_json__application_id=application_id)
    proposal_no = str(payload.get("proposal_no") or "").strip()
    if proposal_no:
        query |= Q(payload_json__public_facts__proposal_no=proposal_no)
        query |= Q(payload_json__proposal_no=proposal_no)
    proposal_id = str(payload.get("proposal_id") or "").strip()
    if proposal_id:
        query |= Q(aggregate_type="Proposal", aggregate_id=proposal_id)
    task_id = str(payload.get("task_id") or event.related_task_id or "").strip()
    if task_id:
        query |= Q(aggregate_type="Task", aggregate_id=task_id)
    resource_id = str(payload.get("resource_id") or "").strip()
    if resource_id:
        query |= Q(aggregate_type="Resource", aggregate_id=resource_id)
    dispute_id = str(payload.get("dispute_id") or event.related_dispute_id or "").strip()
    if dispute_id:
        query |= Q(aggregate_type="Dispute", aggregate_id=dispute_id)
    return query


def public_system_event_proof_rows_for_event(event: Event, *, limit: int = 8) -> list[dict[str, Any]]:
    """Return hash-chain proof rows for a public Event.

    Each row includes full public payload and canonical JSON inputs
    so the browser can independently recompute both payload_hash and event_hash.
    """
    query = _system_event_filter_for_public_event(event)
    if not query:
        return []
    items = SystemEvent.objects.filter(query).order_by("seq")[:limit]
    rows: list[dict[str, Any]] = []
    for item in items:
        pk = item.payload_json or {}
        is_new_schema = pk.get("schema") == PUBLIC_LEDGER_SCHEMA

        chain = system_event_chain_check(item)

        if is_new_schema:
            payload_public_display = public_system_event_payload(item)  # safe projection (may be unsafe_status)
            legacy_note = ""
        else:
            payload_public_display = {"legacy_status": "旧格式审计事件，不公开复算"}
            legacy_note = "旧格式事件，hash 不可在浏览器端完整复算。"

        # Defensive: even a v2-schema payload from a bypassed write or old DB
        # may contain denylist keys.  Only expose raw canonical JSON to the
        # browser when the payload passes the same validator applied at write time.
        can_browser_verify = False
        if is_new_schema:
            try:
                validate_public_ledger_payload(pk)
                can_browser_verify = True
            except ValueError:
                can_browser_verify = False
                legacy_note = "此审计记录 payload 未通过公开安全校验，不能在浏览器端复算。"

        payload_public = dict(pk) if can_browser_verify else {}
        payload_canonical = canonical_json(item.payload_json or {}) if can_browser_verify else ""

        if can_browser_verify:
            try:
                subject_ref = str((pk.get("subject") or {}).get("ref", item.aggregate_id))
                event_hash_input = event_hash_payload_v2(
                    seq=item.seq,
                    event_type=item.event_type,
                    aggregate_type=item.aggregate_type,
                    subject_ref=subject_ref,
                    payload_hash=item.payload_hash,
                    prev_hash=item.prev_hash,
                )
                event_hash_input_canonical = canonical_json(event_hash_input)
            except Exception:
                subject_ref = ""
                event_hash_input = {}
                event_hash_input_canonical = ""
        else:
            subject_ref = ""
            event_hash_input = {}
            event_hash_input_canonical = ""

        rows.append({
            "seq": item.seq,
            "event_type_display": item.get_event_type_display(),
            "occurred_at": item.occurred_at,
            "aggregate_type": item.aggregate_type,
            "subject_ref": subject_ref,
            "payload_hash": item.payload_hash,
            "prev_hash": item.prev_hash,
            "event_hash": item.event_hash,
            "event_hash_short": _short_hash(item.event_hash),
            "payload_hash_valid": chain["payload_hash_valid"],
            "prev_hash_valid": chain["prev_hash_valid"],
            "event_hash_valid": chain["event_hash_valid"],
            "chain_valid": chain["chain_valid"],
            "payload_json": payload_public,
            "payload_public_display": payload_public_display,
            "payload_canonical_json": payload_canonical,
            "event_hash_input": event_hash_input,
            "event_hash_input_canonical_json": event_hash_input_canonical,
            "legacy_note": legacy_note,
            "is_new_schema": is_new_schema,
            "can_browser_verify": can_browser_verify,
            "payload_json_script_id": f"audit-payload-json-{item.seq}",
            "event_hash_input_json_script_id": f"audit-event-hash-input-json-{item.seq}",
        })
    return rows


def public_event_detail(event: Event) -> dict[str, Any]:
    return {
        **public_event_row(event),
        "payload_public": public_event_payload(event),
        "semantic_summary": public_event_semantic_summary(event),
        "audit_events": public_system_event_proof_rows_for_event(event),
        "event_id_explanation": (
            "事件 ID 由事件类型和业务对象 ID 组成，用于公开追踪和防止重复写入。"
        ),
        "audit_explanation": (
            "审计证明来自 SystemEvent 哈希链（v2）。"
            "payload_hash = SHA-256(payload_json 规范化 JSON)。"
            "event_hash = SHA-256(event_hash_input 规范化 JSON)，"
            "输入包含 seq、event_type、aggregate_type、subject_ref、payload_hash、prev_hash；"
            "subject_ref 取自公开 payload_json.subject.ref，不使用内部 aggregate_id。"
            "prev_hash 指向上一条审计事件，使历史修改可被发现。"
        ),
    }


def _sensitive_aggregate(aggregate_type: str, aggregate_id: str) -> str:
    if aggregate_type in ("Member", "User"):
        return "已隐藏"
    return aggregate_id


def _actor_label(event: SystemEvent) -> str:
    if event.actor_member is None:
        return ""
    return public_member_label(
        event.actor_member.display_name,
        event.actor_member.member_no,
    )


def public_system_event_payload(event: SystemEvent) -> dict[str, Any]:
    """Return safe public projection of a SystemEvent payload.

    For legacy events, returns a legacy_status note.
    For v2 events that fail validation, returns an unsafe_status note.
    Only validated v2 events get a full safe projection.
    """
    pk = event.payload_json or {}
    if pk.get("schema") != PUBLIC_LEDGER_SCHEMA:
        return {"legacy_status": "旧格式审计事件，不公开复算"}

    try:
        validate_public_ledger_payload(pk)
    except ValueError:
        return {"unsafe_status": "此审计记录 payload 未通过公开安全校验，不能公开展示 payload。"}

    subject = pk.get("subject") if isinstance(pk.get("subject"), dict) else {}
    facts = pk.get("public_facts") if isinstance(pk.get("public_facts"), dict) else {}
    commitments = pk.get("private_commitments") if isinstance(pk.get("private_commitments"), list) else []

    safe_facts = {}
    for key, value in facts.items():
        if key in _PUBLIC_PAYLOAD_DENYLIST:
            continue
        safe = _sanitize_value(key, value)
        if safe is not None:
            safe_facts[key] = safe

    safe_commitments = []
    for item in commitments:
        if not isinstance(item, dict):
            continue
        safe_commitments.append({
            "name": str(item.get("name", "")),
            "present": bool(item.get("present", False)),
            "reason": str(item.get("reason", "")),
        })

    return {
        "schema": pk.get("schema"),
        "subject": {
            "type": str(subject.get("type", "")),
            "ref": str(subject.get("ref", "")),
            "label": str(subject.get("label", "")),
        },
        "action": str(pk.get("action", "")),
        "stage": str(pk.get("stage", "")),
        "summary": str(pk.get("summary", "")),
        "public_facts": safe_facts,
        "private_commitments": safe_commitments,
    }


def _public_subject_ref(event: SystemEvent) -> str:
    payload = event.payload_json or {}
    if payload.get("schema") != PUBLIC_LEDGER_SCHEMA:
        return ""
    try:
        validate_public_ledger_payload(payload)
    except ValueError:
        return ""
    return str((payload.get("subject") or {}).get("ref", "")).strip()


def public_system_event_row(event: SystemEvent) -> dict[str, Any]:
    return {
        "seq": event.seq,
        "event_type": event.event_type,
        "event_type_display": event.get_event_type_display(),
        "aggregate_type": event.aggregate_type,
        "subject_ref": _public_subject_ref(event),
        "actor_label": _actor_label(event),
        "occurred_at": event.occurred_at,
        "event_hash_short": _short_hash(event.event_hash),
        "detail_url": f"/observer/event-ledger/{event.seq}/",
        "detail_name": "observer-event-ledger-detail",
    }


def public_system_event_detail(event: SystemEvent) -> dict[str, Any]:
    chain = system_event_chain_check(event)
    return {
        "seq": event.seq,
        "event_type": event.event_type,
        "event_type_display": event.get_event_type_display(),
        "aggregate_type": event.aggregate_type,
        "subject_ref": _public_subject_ref(event),
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
    """Single-event hash-chain verification (v2-aware)."""
    payload_hash_valid = hash_json(event.payload_json or {}) == event.payload_hash

    prev = SystemEvent.objects.filter(seq=event.seq - 1).first()
    has_prev_event = prev is not None
    if has_prev_event:
        prev_hash_valid = event.prev_hash == prev.event_hash
    else:
        prev_hash_valid = event.prev_hash == ""

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
    event_hash_valid = event.event_hash == expected_event_hash

    return {
        "payload_hash_valid": payload_hash_valid,
        "prev_hash_valid": prev_hash_valid,
        "event_hash_valid": event_hash_valid,
        "chain_valid": payload_hash_valid and prev_hash_valid and event_hash_valid,
        "has_prev_event": has_prev_event,
    }
