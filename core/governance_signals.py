"""Signal handlers that append governance events to the unified event ledger."""

from __future__ import annotations

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from .event_ledger import append_event
from .event_payloads import role_assignment_payload
from .models import RoleAssignment, SystemEvent


@receiver(pre_save, sender=RoleAssignment)
def cache_previous_role_assignment_status(sender, instance: RoleAssignment, raw: bool = False, **kwargs) -> None:
    if raw or not instance.pk:
        instance._previous_status = None
        return
    instance._previous_status = sender.objects.filter(pk=instance.pk).values_list("status", flat=True).first()


@receiver(post_save, sender=RoleAssignment)
def append_role_assignment_event(
    sender,
    instance: RoleAssignment,
    created: bool,
    raw: bool = False,
    **kwargs,
) -> None:
    if raw:
        return
    if created:
        append_event(
            event_type=SystemEvent.EventType.ROLE_ASSIGNED,
            aggregate_type="RoleAssignment",
            aggregate_id=str(instance.pk),
            actor_member=instance.granted_by,
            payload_json=role_assignment_payload(instance),
            occurred_at=instance.start_at,
        )
        return
    previous_status = getattr(instance, "_previous_status", None)
    if previous_status == RoleAssignment.Status.ACTIVE and instance.status == RoleAssignment.Status.REVOKED:
        append_event(
            event_type=SystemEvent.EventType.ROLE_REVOKED,
            aggregate_type="RoleAssignment",
            aggregate_id=str(instance.pk),
            actor_member=instance.revoked_by,
            payload_json=role_assignment_payload(instance),
            occurred_at=instance.end_at or timezone.now(),
        )
