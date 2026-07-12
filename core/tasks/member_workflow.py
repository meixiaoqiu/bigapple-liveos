"""Member task claim and labor-submission services."""

from __future__ import annotations

from django.utils import timezone

from core.db import atomic_for_model
from core.event_ledger import append_event
from core.event_payloads import task_event_payload
from core.exceptions import DomainError
from core.models import Member, SystemEvent, Task
from core.service_utils import actor_ref


@atomic_for_model(Task)
def claim_task(*, task: Task, member: Member) -> Task:
    """Claim an open task for a member.

    The Simulation Engine must call the HTTP endpoint that uses this service;
    direct database updates would bypass Live OS authority.
    """

    task = Task.objects.select_for_update().get(task_id=task.task_id)
    if task.status != Task.Status.OPEN:
        raise DomainError("Only open tasks can be claimed.")
    if task.assignee_member_id:
        raise DomainError("Task already has an assignee.")
    previous_status = task.status
    now = timezone.now()
    actor = actor_ref(member)
    task.assignee_member = member
    task.status = Task.Status.CLAIMED
    task.save(update_fields=["assignee_member", "status"])
    append_event(
        event_type=SystemEvent.EventType.TASK_CLAIMED,
        aggregate_type="Task",
        aggregate_id=task.pk,
        actor_member=member,
        payload_json=task_event_payload(task, action="claim", actor=actor, previous_status=previous_status),
        occurred_at=now,
    )
    return task


@atomic_for_model(Task)
def submit_labor(*, task: Task, member: Member, labor_note: str, evidence_refs: list[str]) -> Task:
    """Submit member labor for review."""

    task = Task.objects.select_for_update().get(task_id=task.task_id)
    if task.assignee_member_id != member.pk:
        raise DomainError("Only the assigned member can submit this task.")
    if task.status not in {Task.Status.CLAIMED, Task.Status.IN_PROGRESS}:
        raise DomainError("Task must be claimed or in progress before submission.")
    previous_status = task.status
    actor = actor_ref(member)
    task.status = Task.Status.PENDING_REVIEW
    task.submitted_at = timezone.now()
    task.metadata = {
        **task.metadata,
        "labor_note": labor_note,
        "evidence_refs": evidence_refs,
    }
    task.save(update_fields=["status", "submitted_at", "metadata"])
    append_event(
        event_type=SystemEvent.EventType.TASK_SUBMITTED,
        aggregate_type="Task",
        aggregate_id=task.pk,
        actor_member=member,
        payload_json=task_event_payload(
            task,
            action="submit_labor",
            actor=actor,
            previous_status=previous_status,
            extra={"labor_note": labor_note, "evidence_refs": evidence_refs},
        ),
        occurred_at=task.submitted_at,
    )
    return task
