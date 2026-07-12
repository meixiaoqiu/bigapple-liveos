"""Operator-managed task creation, publication, assignment, and closure."""

from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

from core.db import atomic_for_model
from core.event_ledger import append_event
from core.event_payloads import actor_member_from_ref, task_event_payload
from core.exceptions import DomainError
from core.id_generators import generate_task_id
from core.models import Member, SystemEvent, Task


@atomic_for_model(Task)
def create_task_draft(
    *,
    title: str,
    task_type: str,
    standard_hours: Decimal,
    base_points: int,
    role_coefficient: Decimal,
    failure_consequence: str,
    can_be_delayed: bool,
    requires_review: bool,
    rule_version: str,
    created_by: dict,
    due_at=None,
    source_type: str = Task.SourceType.DIRECT,
    source_proposal=None,
    source_proposal_execution=None,
) -> Task:
    """Create an operator-managed draft task before it is opened for claiming."""

    cleaned_title = title.strip()
    valid_task_types = {value for value, _label in Task.TaskType.choices}
    valid_consequences = {value for value, _label in Task.FailureConsequence.choices}
    if not cleaned_title:
        raise DomainError("任务标题不能为空。")
    if task_type not in valid_task_types:
        raise DomainError("任务类型无效。")
    if standard_hours <= 0:
        raise DomainError("标准工时必须大于 0。")
    if base_points <= 0:
        raise DomainError("基础积分必须大于 0。")
    if role_coefficient <= 0:
        raise DomainError("岗位系数必须大于 0。")
    if failure_consequence and failure_consequence not in valid_consequences:
        raise DomainError("失败后果无效。")
    if not rule_version:
        raise DomainError("缺少规则版本。")
    now = timezone.now()
    task = Task.objects.create(
        task_id=generate_task_id(),
        title=cleaned_title,
        task_type=task_type,
        status=Task.Status.DRAFT,
        standard_hours=standard_hours,
        base_points=base_points,
        role_coefficient=role_coefficient,
        can_be_delayed=can_be_delayed,
        requires_review=requires_review,
        failure_consequence=failure_consequence,
        rule_version=rule_version,
        created_at=now,
        due_at=due_at,
        source_type=source_type,
        source_proposal=source_proposal,
        source_proposal_execution=source_proposal_execution,
        metadata={"source": "control_task_authoring", "created_by": created_by},
    )
    append_event(
        event_type=SystemEvent.EventType.TASK_CREATED,
        aggregate_type="Task",
        aggregate_id=task.pk,
        actor_member=actor_member_from_ref(created_by),
        payload_json=task_event_payload(task, action="create", actor=created_by),
        occurred_at=now,
    )
    return task


@atomic_for_model(Task)
def publish_task(*, task: Task, publisher: dict) -> Task:
    """Open a draft task so members can claim it."""

    task = Task.objects.select_for_update().get(task_id=task.task_id)
    if task.status != Task.Status.DRAFT:
        raise DomainError("只有草稿任务可以发布。")
    if task.assignee_member_id:
        raise DomainError("已分配成员的任务不能发布为开放领取。")
    previous_status = task.status
    now = timezone.now()
    task.status = Task.Status.OPEN
    task.metadata = {**task.metadata, "published_by": publisher, "published_at": now.isoformat()}
    task.save(update_fields=["status", "metadata"])
    append_event(
        event_type=SystemEvent.EventType.TASK_PUBLISHED,
        aggregate_type="Task",
        aggregate_id=task.pk,
        actor_member=actor_member_from_ref(publisher),
        payload_json=task_event_payload(task, action="publish", actor=publisher, previous_status=previous_status),
        occurred_at=now,
    )
    return task


@atomic_for_model(Task)
def assign_task(*, task: Task, member: Member, operator: dict) -> Task:
    """Assign an open task to a member through the operator workflow."""

    task = Task.objects.select_for_update().get(task_id=task.task_id)
    if task.status != Task.Status.OPEN:
        raise DomainError("只有开放领取任务可以被指派。")
    if task.assignee_member_id:
        raise DomainError("任务已经有负责人。")
    if member.status not in {Member.Status.ADMITTED, Member.Status.ACTIVE}:
        raise DomainError("只能指派给已接纳或活跃成员。")
    previous_status = task.status
    now = timezone.now()
    task.assignee_member = member
    task.status = Task.Status.CLAIMED
    task.metadata = {
        **task.metadata,
        "assigned_by": operator,
        "assigned_at": now.isoformat(),
    }
    task.save(update_fields=["assignee_member", "status", "metadata"])
    append_event(
        event_type=SystemEvent.EventType.TASK_ASSIGNED,
        aggregate_type="Task",
        aggregate_id=task.pk,
        actor_member=actor_member_from_ref(operator),
        payload_json=task_event_payload(
            task,
            action="assign",
            actor=operator,
            previous_status=previous_status,
            extra={"assigned_member_no": member.member_no, "assigned_member_display_name": str(member.display_name)},
        ),
        occurred_at=now,
    )
    return task


@atomic_for_model(Task)
def close_task(*, task: Task, operator: dict, reason: str) -> Task:
    """Close a draft or open task before it enters member labor execution."""

    cleaned_reason = reason.strip()
    if not cleaned_reason:
        raise DomainError("关闭原因不能为空。")
    task = Task.objects.select_for_update().get(task_id=task.task_id)
    if task.status not in {Task.Status.DRAFT, Task.Status.OPEN}:
        raise DomainError("只有草稿或开放领取任务可以关闭。")
    if task.assignee_member_id:
        raise DomainError("已经指派给成员的任务不能在发布管理页关闭。")
    previous_status = task.status
    now = timezone.now()
    task.status = Task.Status.CLOSED
    task.metadata = {
        **task.metadata,
        "closed_by": operator,
        "closed_at": now.isoformat(),
        "close_reason": cleaned_reason,
    }
    task.save(update_fields=["status", "metadata"])
    append_event(
        event_type=SystemEvent.EventType.TASK_CLOSED,
        aggregate_type="Task",
        aggregate_id=task.pk,
        actor_member=actor_member_from_ref(operator),
        payload_json=task_event_payload(
            task,
            action="close",
            actor=operator,
            previous_status=previous_status,
            extra={"reason": cleaned_reason},
        ),
        occurred_at=now,
    )
    return task
