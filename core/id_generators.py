"""Stable id allocators for core domain records."""

from __future__ import annotations

from uuid import uuid4

from .exceptions import DomainError
from .models import Dispute, Event, ResourceTransaction, Task


def generate_dispute_id() -> str:
    """Allocate a user-created dispute id without relying on database sequences."""

    for _ in range(5):
        dispute_id = f"dispute-{uuid4().hex[:12]}"
        if not Dispute.objects.filter(dispute_id=dispute_id).exists():
            return dispute_id
    raise DomainError("无法生成申诉 ID，请重试。")


def generate_dispute_event_id() -> str:
    """Allocate a dispute event id without relying on database sequences."""

    for _ in range(5):
        event_id = f"event-dispute-{uuid4().hex[:12]}"
        if not Event.objects.filter(event_id=event_id).exists():
            return event_id
    raise DomainError("无法生成申诉事件 ID，请重试。")


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
