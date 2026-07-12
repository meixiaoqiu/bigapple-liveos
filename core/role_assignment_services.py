"""Role assignment lifecycle services."""

from __future__ import annotations

from django.utils import timezone

from .governance_setup import default_role_assignment_end_at
from .models import Member, Role, RoleAssignment


def revoke_role_assignment(
    *,
    assignment: RoleAssignment,
    revoked_by: Member | None = None,
    end_at=None,
) -> RoleAssignment:
    assignment.status = RoleAssignment.Status.REVOKED
    assignment.revoked_by = revoked_by
    assignment.end_at = end_at or timezone.now()
    assignment.save(update_fields=["status", "revoked_by", "end_at", "updated_at"])
    return assignment


def create_role_assignment(
    *,
    member: Member,
    role: Role,
    granted_by: Member | None = None,
    start_at=None,
    end_at=None,
    source_type: str = RoleAssignment.SourceType.DIRECT,
    source_proposal=None,
    source_proposal_execution=None,
) -> RoleAssignment:
    starts_at = start_at or timezone.now()
    assignment, _created = RoleAssignment.objects.get_or_create(
        member=member,
        role=role,
        status=RoleAssignment.Status.ACTIVE,
        defaults={
            "start_at": starts_at,
            "end_at": end_at or default_role_assignment_end_at(starts_at),
            "granted_by": granted_by,
            "source_type": source_type,
            "source_proposal": source_proposal,
            "source_proposal_execution": source_proposal_execution,
        },
    )
    return assignment
