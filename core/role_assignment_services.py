"""Role assignment lifecycle services."""

from __future__ import annotations

from typing import Any

from django.utils import timezone

from .db import atomic_for_model
from .exceptions import DomainError
from .governance_setup import default_role_assignment_end_at
from .member_roles import (
    MEMBER_ROLE_ORGANIZATION_NAME,
    ROLE_BIG_APPLE_MEMBER,
    ROLE_FORMAL_MEMBER,
    ROLE_GOVERNANCE_MEMBER,
    ensure_member_role,
    member_has_role,
)
from .models import Member, Role, RoleAssignment


def _role_requires_formal_member(role: Role) -> bool:
    """Return True if granting *role* requires the member to have ROLE_FORMAL_MEMBER."""
    if role.organization.name == MEMBER_ROLE_ORGANIZATION_NAME:
        if role.name in {
            ROLE_FORMAL_MEMBER,
            ROLE_GOVERNANCE_MEMBER,
        }:
            return True
    for rp in role.role_permissions.select_related("permission"):
        code = getattr(rp.permission, "code", "")
        if code and str(code).startswith("governance."):
            return True
    return False


def validate_role_assignment_prerequisites(member: Member, role: Role) -> None:
    """Raise DomainError if *member* does not satisfy the prerequisites for *role*."""
    if member.status in {Member.Status.SUSPENDED, Member.Status.EXITED}:
        raise DomainError("成员状态已停用，不能授予新角色。")

    if role.organization.name == MEMBER_ROLE_ORGANIZATION_NAME:
        if role.name == ROLE_BIG_APPLE_MEMBER:
            return  # no prerequisite
        if role.name == ROLE_FORMAL_MEMBER:
            if not member_has_role(member, ROLE_BIG_APPLE_MEMBER):
                raise DomainError("授予正式成员角色前必须先拥有基础成员角色。")
            return
        if role.name == ROLE_GOVERNANCE_MEMBER:
            if not member_has_role(member, ROLE_FORMAL_MEMBER):
                raise DomainError("授予治理成员角色前必须先拥有正式成员角色。")
            return

    if _role_requires_formal_member(role):
        if not member_has_role(member, ROLE_FORMAL_MEMBER):
            raise DomainError("授予该角色前必须先拥有正式成员角色。")
        return

    if not member_has_role(member, ROLE_BIG_APPLE_MEMBER):
        raise DomainError("授予该角色前必须先拥有基础成员角色。")


@atomic_for_model(RoleAssignment)
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
    skip_validation: bool = False,
) -> RoleAssignment:
    if not skip_validation:
        validate_role_assignment_prerequisites(member, role)
    starts_at = start_at or timezone.now()
    assignment, created = RoleAssignment.objects.get_or_create(
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
    # Auto-issue formal member number when ROLE_FORMAL_MEMBER is first granted.
    if role.organization.name == MEMBER_ROLE_ORGANIZATION_NAME and role.name == ROLE_FORMAL_MEMBER:
        from .credential_services import issue_formal_member_number

        issue_formal_member_number(
            member,
            source_proposal=source_proposal,
            source_proposal_execution=source_proposal_execution,
            issued_by=granted_by,
        )
    return assignment


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


@atomic_for_model(RoleAssignment)
def bootstrap_first_governance_member(
    member: Member,
    *,
    granted_by: Member | None = None,
) -> dict[str, Any]:
    """Grant the full governance chain to the first world administrator.

    Order: ROLE_BIG_APPLE_MEMBER → ROLE_FORMAL_MEMBER →
    ROLE_GOVERNANCE_MEMBER → governance admin role.

    Each step calls ``create_role_assignment`` without ``skip_validation``
    so the normal prerequisite checks apply.  The function is wrapped in
    ``@atomic_for_model(RoleAssignment)`` — if any step fails the entire
    chain is rolled back.

    Raises DomainError for SUSPENDED / EXITED members.
    """
    assignments: dict[str, RoleAssignment] = {}

    # Step 1: baseline (no prerequisite)
    assignments["big_apple"] = create_role_assignment(
        member=member,
        role=ensure_member_role(ROLE_BIG_APPLE_MEMBER),
        source_type=RoleAssignment.SourceType.INITIALIZATION,
    )

    # Step 2: formal (prerequisite: big_apple)
    assignments["formal"] = create_role_assignment(
        member=member,
        role=ensure_member_role(ROLE_FORMAL_MEMBER),
        source_type=RoleAssignment.SourceType.INITIALIZATION,
    )

    # Step 3: governance (prerequisite: formal)
    assignments["governance"] = create_role_assignment(
        member=member,
        role=ensure_member_role(ROLE_GOVERNANCE_MEMBER),
        source_type=RoleAssignment.SourceType.INITIALIZATION,
    )

    # Step 4: governance admin (prerequisite: formal via _role_requires_formal_member)
    from .governance_setup import ensure_governance_admin_role

    setup = ensure_governance_admin_role()
    assignments["admin"] = create_role_assignment(
        member=member,
        role=setup["role"],
        source_type=RoleAssignment.SourceType.INITIALIZATION,
    )

    return assignments
