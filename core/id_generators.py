"""Stable id allocators for core domain records."""

from __future__ import annotations

from uuid import uuid4

from .exceptions import DomainError
from .models import Event, EventFeedback, ResourceTransaction, Task


def generate_event_feedback_id() -> str:
    """Allocate an event-feedback id without relying on database sequences."""

    for _ in range(5):
        feedback_id = f"feedback-{uuid4().hex[:12]}"
        if not EventFeedback.objects.filter(feedback_id=feedback_id).exists():
            return feedback_id
    raise DomainError("无法生成事件反馈 ID，请重试。")


def generate_event_feedback_event_id() -> str:
    """Allocate an event-feedback Event id without relying on database sequences."""

    for _ in range(5):
        event_id = f"event-feedback-{uuid4().hex[:12]}"
        if not Event.objects.filter(event_id=event_id).exists():
            return event_id
    raise DomainError("无法生成事件反馈事件 ID，请重试。")


def generate_task_id() -> str:
    """Allocate an operator-created task id without relying on database sequences."""

    for _ in range(5):
        task_id = f"task-{uuid4().hex[:12]}"
        if not Task.objects.filter(task_id=task_id).exists():
            return task_id
    raise DomainError("无法生成任务 ID，请重试。")


def generate_resource_event_id() -> str:
    """Allocate a resource event id without relying on database sequences."""

    for _ in range(5):
        event_id = f"event-resource-{uuid4().hex[:12]}"
        if not Event.objects.filter(event_id=event_id).exists():
            return event_id
    raise DomainError("无法生成资源事件 ID，请重试。")


def generate_resource_transaction_id() -> str:
    """Allocate an append-only resource transaction id."""

    for _ in range(5):
        transaction_id = f"res-tx-{uuid4().hex[:12]}"
        if not ResourceTransaction.objects.filter(transaction_id=transaction_id).exists():
            return transaction_id
    raise DomainError("无法生成库存流水 ID，请重试。")
