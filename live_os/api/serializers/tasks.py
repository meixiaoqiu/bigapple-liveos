"""Task contract serializers."""

from __future__ import annotations

from typing import Any

from core.models import Task

from .base import drop_none, encode_value


def task_to_contract(task: Task) -> dict[str, Any]:
    return drop_none(
        {
            "task_id": task.task_id,
            "title": task.title,
            "task_type": task.task_type,
            "status": task.status,
            "standard_hours": encode_value(task.standard_hours),
            "base_points": task.base_points,
            "role_coefficient": encode_value(task.role_coefficient),
            "physical_load": encode_value(task.physical_load),
            "dirty_level": encode_value(task.dirty_level),
            "psychological_load": encode_value(task.psychological_load),
            "urgency": encode_value(task.urgency),
            "can_be_delayed": task.can_be_delayed,
            "requires_review": task.requires_review,
            "failure_consequence": task.failure_consequence,
            "assignee_member_no": task.assignee_member.member_no if task.assignee_member_id else None,
            "rule_version": task.rule_version,
            "created_at": encode_value(task.created_at),
            "due_at": encode_value(task.due_at),
            "submitted_at": encode_value(task.submitted_at),
            "reviewed_at": encode_value(task.reviewed_at),
            "metadata": task.metadata,
        }
    )


def public_task_to_contract(task: Task) -> dict[str, Any]:
    return drop_none(
        {
            "task_id": task.task_id,
            "title": task.title,
            "task_type": task.task_type,
            "status": task.status,
            "standard_hours": encode_value(task.standard_hours),
            "base_points": task.base_points,
            "role_coefficient": encode_value(task.role_coefficient),
            "physical_load": encode_value(task.physical_load),
            "dirty_level": encode_value(task.dirty_level),
            "psychological_load": encode_value(task.psychological_load),
            "urgency": encode_value(task.urgency),
            "can_be_delayed": task.can_be_delayed,
            "requires_review": task.requires_review,
            "failure_consequence": task.failure_consequence,
            "rule_version": task.rule_version,
            "created_at": encode_value(task.created_at),
            "due_at": encode_value(task.due_at),
        }
    )
