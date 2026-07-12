"""Task review and accepted-labor settlement services."""

from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

from core.db import atomic_for_model
from core.event_ledger import append_event
from core.event_payloads import actor_member_from_ref, task_event_payload
from core.exceptions import DomainError
from core.ledger_services import create_ledger_entry
from core.models import Event, LedgerEntry, SystemEvent, Task


@atomic_for_model(Task)
def review_task(*, task: Task, reviewer: dict, accepted: bool, reason: str) -> tuple[Task, list[LedgerEntry]]:
    """Review submitted labor and optionally create an append-only ledger entry."""

    task = Task.objects.select_for_update().select_related("assignee_member").get(task_id=task.task_id)
    if task.status != Task.Status.PENDING_REVIEW:
        raise DomainError("Only tasks pending review can be reviewed.")
    if task.assignee_member is None:
        raise DomainError("Cannot review a task without an assignee.")
    event_id = f"event-task-{task.task_id}"
    ledger_entry_id = f"ledger-task-{task.task_id}"
    if accepted:
        if Event.objects.filter(event_id=event_id).exists():
            raise DomainError("Task review event already exists.")
        if LedgerEntry.objects.filter(ledger_entry_id=ledger_entry_id).exists():
            raise DomainError("Task review ledger entry already exists.")
        if LedgerEntry.objects.filter(
            related_task=task,
            entry_type=LedgerEntry.EntryType.CONTRIBUTION,
            status=LedgerEntry.Status.POSTED,
        ).exists():
            raise DomainError("Task already has a posted contribution ledger entry.")

    previous_status = task.status
    now = timezone.now()
    task.status = Task.Status.ACCEPTED if accepted else Task.Status.REJECTED
    task.reviewed_at = now
    task.metadata = {**task.metadata, "review_reason": reason}
    task.save(update_fields=["status", "reviewed_at", "metadata"])
    append_event(
        event_type=SystemEvent.EventType.TASK_REVIEWED,
        aggregate_type="Task",
        aggregate_id=task.pk,
        actor_member=actor_member_from_ref(reviewer),
        payload_json=task_event_payload(
            task,
            action="review",
            actor=reviewer,
            previous_status=previous_status,
            extra={"accepted": accepted, "reason": reason},
        ),
        occurred_at=now,
    )

    entries: list[LedgerEntry] = []
    if accepted:
        amount = int((Decimal(task.base_points) * task.role_coefficient).to_integral_value())
        event = Event.objects.create(
            event_id=event_id,
            event_type=Event.EventType.TASK,
            simulation_day=int(task.metadata.get("simulation_day", 1)),
            severity=Event.Severity.INFO,
            title="Task accepted",
            summary=f"Task {task.task_id} was accepted by a reviewer.",
            involved_member_ids=[task.assignee_member.member_no],
            related_task=task,
            occurred_at=now,
            generated_by=Event.GeneratedBy.LIVE_OS,
            visibility=Event.Visibility.PUBLIC,
            payload={"points_awarded": amount, "reason": reason},
        )
        entry = create_ledger_entry(
            ledger_entry_id=ledger_entry_id,
            member=task.assignee_member,
            amount=amount,
            entry_type=LedgerEntry.EntryType.CONTRIBUTION,
            reason=reason,
            related_task=task,
            related_event_id=event.event_id,
            rule_version=task.rule_version,
            created_at=now,
            created_by=reviewer,
            reviewer=reviewer,
            status=LedgerEntry.Status.POSTED,
        )
        entries.append(entry)

    return task, entries
