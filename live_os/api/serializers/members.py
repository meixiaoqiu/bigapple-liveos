"""Member contract serializers."""

from __future__ import annotations

from typing import Any

from django.utils import timezone

from core.models import Member

from .base import drop_none, encode_value


def member_to_contract(member: Member) -> dict[str, Any]:
    checked_at = timezone.now()
    active_assignments = list(
        member.role_assignments.filter(
            status="active",
            role__status="active",
            start_at__lte=checked_at,
            end_at__gte=checked_at,
        ).select_related("role", "role__organization")
    )
    roles = [
        {
            "role_assignment_id": assignment.pk,
            "role_id": assignment.role_id,
            "role": str(assignment.role),
            "role_name": assignment.role.name,
            "organization_name": assignment.role.organization.name,
        }
        for assignment in active_assignments
    ]
    role_names = [role["role_name"] for role in roles]
    return drop_none(
        {
            "member_no": member.member_no,
            "display_name": member.display_name,
            "role_names": role_names,
            "roles": roles,
            "role_name": "、".join(role_names),
            "status": member.status,
            "batch_id": member.batch_id,
            "joined_simulation_day": member.joined_simulation_day,
            "credit_floor": member.credit_floor,
            "profile": member.profile,
            "created_at": encode_value(member.created_at),
            "metadata": member.metadata,
        }
    )
