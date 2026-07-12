"""Dispute lifecycle services."""

from __future__ import annotations

from django.utils import timezone

from .db import atomic_for_model
from .event_ledger import append_event
from .event_payloads import actor_member_from_ref, dispute_event_payload
from .exceptions import DomainError
from .id_generators import generate_dispute_event_id, generate_dispute_id
from .models import Dispute, Event, Member, SystemEvent, Task
from .service_utils import actor_ref


@atomic_for_model(Dispute)
def submit_dispute(
    *,
    claimant: Member,
    dispute_type: str,
    facts: str,
    evidence_refs: list[str],
    related_task: Task | None = None,
) -> Dispute:
    """Create a real-name member dispute in submitted state."""

    cleaned_facts = facts.strip()
    valid_dispute_types = {value for value, _label in Dispute.DisputeType.choices}
    if dispute_type not in valid_dispute_types:
        raise DomainError("申诉类型无效。")
    if not cleaned_facts:
        raise DomainError("申诉事实不能为空。")
    now = timezone.now()
    dispute = Dispute.objects.create(
        dispute_id=generate_dispute_id(),
        dispute_type=dispute_type,
        status=Dispute.Status.SUBMITTED,
        claimant_member=claimant,
        respondent_member=None,
        related_task=related_task,
        related_ledger_entry=None,
        facts=cleaned_facts,
        evidence_refs=evidence_refs,
        handler={},
        reviewer={},
        resolution="",
        appeal_path="workspace-dispute",
        submitted_at=now,
        resolved_at=None,
        metadata={"source": "workspace"},
    )
    actor = actor_ref(claimant)
    append_event(
        event_type=SystemEvent.EventType.DISPUTE_CREATED,
        aggregate_type="Dispute",
        aggregate_id=dispute.pk,
        actor_member=claimant,
        payload_json=dispute_event_payload(dispute, action="submit", actor=actor),
        occurred_at=now,
    )
    return dispute


def dispute_involved_member_ids(dispute: Dispute) -> list[str]:
    """Return stable member numbers related to a dispute event."""

    member_ids = [dispute.claimant_member.member_no]
    if dispute.respondent_member_id:
        member_ids.append(dispute.respondent_member.member_no)
    return member_ids


@atomic_for_model(Dispute)
def start_dispute_review(*, dispute: Dispute, handler: dict, note: str = "") -> tuple[Dispute, Event]:
    """Move a submitted dispute into review and append an internal dispute event."""

    if dispute.status != Dispute.Status.SUBMITTED:
        raise DomainError("只有已提交申诉可以受理。")

    previous_status = dispute.status
    now = timezone.now()
    cleaned_note = note.strip()
    dispute.status = Dispute.Status.IN_REVIEW
    dispute.handler = handler
    dispute.metadata = {
        **dispute.metadata,
        "review_started_at": now.isoformat(),
        "review_started_note": cleaned_note,
    }
    dispute.save(update_fields=["status", "handler", "metadata"])

    event = Event.objects.create(
        event_id=generate_dispute_event_id(),
        event_type=Event.EventType.DISPUTE,
        simulation_day=int(dispute.metadata.get("simulation_day", 1)),
        severity=Event.Severity.INFO,
        title="申诉已受理",
        summary=f"申诉 {dispute.dispute_id} 已由 {handler.get('display_name', handler.get('actor_id', '治理成员'))} 受理。",
        involved_member_ids=dispute_involved_member_ids(dispute),
        related_task=dispute.related_task,
        related_dispute_id=dispute.dispute_id,
        occurred_at=now,
        generated_by=Event.GeneratedBy.HUMAN_OPERATOR,
        visibility=Event.Visibility.INTERNAL,
        payload={
            "action": "start_review",
            "dispute_id": dispute.dispute_id,
            "handler": handler,
            "note": cleaned_note,
        },
    )
    append_event(
        event_type=SystemEvent.EventType.DISPUTE_REVIEW_STARTED,
        aggregate_type="Dispute",
        aggregate_id=dispute.pk,
        actor_member=actor_member_from_ref(handler),
        payload_json=dispute_event_payload(
            dispute,
            action="start_review",
            actor=handler,
            previous_status=previous_status,
            extra={"note": cleaned_note, "business_event_id": event.pk},
        ),
        occurred_at=now,
    )
    return dispute, event


@atomic_for_model(Dispute)
def resolve_dispute(*, dispute: Dispute, reviewer: dict, decision: str, resolution: str) -> tuple[Dispute, Event]:
    """Close an in-review dispute with a resolved or rejected decision."""

    cleaned_resolution = resolution.strip()
    if dispute.status != Dispute.Status.IN_REVIEW:
        raise DomainError("只有处理中的申诉可以记录处理结果。")
    if decision not in {"resolved", "rejected"}:
        raise DomainError("申诉处理结果无效。")
    if not cleaned_resolution:
        raise DomainError("处理结果不能为空。")

    previous_status = dispute.status
    now = timezone.now()
    dispute.status = Dispute.Status.RESOLVED if decision == "resolved" else Dispute.Status.REJECTED
    dispute.reviewer = reviewer
    dispute.resolution = cleaned_resolution
    dispute.resolved_at = now
    dispute.metadata = {
        **dispute.metadata,
        "resolved_by": reviewer,
        "resolved_at": now.isoformat(),
        "decision": decision,
    }
    dispute.save(update_fields=["status", "reviewer", "resolution", "resolved_at", "metadata"])

    event = Event.objects.create(
        event_id=generate_dispute_event_id(),
        event_type=Event.EventType.DISPUTE,
        simulation_day=int(dispute.metadata.get("simulation_day", 1)),
        severity=Event.Severity.INFO if decision == "resolved" else Event.Severity.WARNING,
        title="申诉处理完成" if decision == "resolved" else "申诉已驳回",
        summary=f"申诉 {dispute.dispute_id} 已记录处理结果：{cleaned_resolution}",
        involved_member_ids=dispute_involved_member_ids(dispute),
        related_task=dispute.related_task,
        related_dispute_id=dispute.dispute_id,
        occurred_at=now,
        generated_by=Event.GeneratedBy.HUMAN_OPERATOR,
        visibility=Event.Visibility.INTERNAL,
        payload={
            "action": "resolve",
            "decision": decision,
            "dispute_id": dispute.dispute_id,
            "reviewer": reviewer,
            "resolution": cleaned_resolution,
        },
    )
    append_event(
        event_type=SystemEvent.EventType.DISPUTE_RESOLVED,
        aggregate_type="Dispute",
        aggregate_id=dispute.pk,
        actor_member=actor_member_from_ref(reviewer),
        payload_json=dispute_event_payload(
            dispute,
            action="resolve",
            actor=reviewer,
            previous_status=previous_status,
            extra={"decision": decision, "business_event_id": event.pk},
        ),
        occurred_at=now,
    )
    return dispute, event
