"""Shared helpers for domain service modules."""

from __future__ import annotations

from .member_roles import actor_type_for_current_world
from .models import Member


def actor_ref(member: Member) -> dict[str, str]:
    """Build the ActorRef shape used in service metadata and events."""

    return {
        "actor_id": member.member_no,
        "actor_type": actor_type_for_current_world(),
        "display_name": str(member.display_name or member.profile.get("display_name") or member.member_no),
    }
