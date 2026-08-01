"""Permission checks derived from the configured authorization backend."""

from __future__ import annotations

from django.db.models import Q
from django.utils import timezone

from .member_roles import ROLE_COVENANTER, member_allows_role_facts, member_has_role, member_role_filter
from .models import Member, Resource, Role, RoleAssignment, RolePermission


MEMBER_PERMISSION_STATUSES = {Member.Status.ACTIVE, Member.Status.ADMITTED}
GUARDED_PERMISSION_PREFIXES = ("governance.", "finance.")


def _time_window_filter(at_time):
    return Q(start_at__lte=at_time, end_at__gt=at_time)


def _role_permission_applies_to_resource(role_permission: RolePermission, resource: Resource | None) -> bool:
    if resource is None:
        return True
    constraints = role_permission.constraints_json or {}
    resource_id = str(resource.pk)
    constrained_id = constraints.get("resource_id")
    constrained_ids = constraints.get("resource_ids")
    if constrained_id:
        return str(constrained_id) == resource_id
    if constrained_ids:
        return resource_id in {str(item) for item in constrained_ids}
    return role_permission.scope in {"", "global", "all"}


def permission_requires_covenanter(permission_code: str) -> bool:
    return str(permission_code).startswith(GUARDED_PERMISSION_PREFIXES)


def legacy_member_has_permission(
    member: Member,
    permission_code: str,
    resource: Resource | None = None,
    at_time=None,
) -> bool:
    """Check permissions derived from active Django role assignments."""

    checked_at = at_time or timezone.now()
    if not member_allows_role_facts(member):
        return False
    if permission_requires_covenanter(permission_code) and not member_has_role(
        member, ROLE_COVENANTER, checked_at=checked_at
    ):
        return False

    assignments = RoleAssignment.objects.filter(
        member=member,
        status=RoleAssignment.Status.ACTIVE,
        role__status=Role.Status.ACTIVE,
    ).filter(_time_window_filter(checked_at))

    role_permissions = (
        RolePermission.objects.select_related("permission")
        .filter(role__in=assignments.values("role_id"), permission__code=permission_code)
    )
    for role_permission in role_permissions:
        if _role_permission_applies_to_resource(role_permission, resource):
            return True
    return False


def member_has_permission(
    member: Member,
    permission_code: str,
    resource: Resource | None = None,
    at_time=None,
) -> bool:
    """Check whether *member* can use *permission_code* on *resource*."""

    from .authorization_services import AuthorizationService

    return AuthorizationService().member_has_permission(
        member,
        permission_code,
        resource=resource,
        at_time=at_time,
    )


def members_with_permission(permission_code: str, at_time=None):
    checked_at = at_time or timezone.now()
    queryset = Member.objects.filter(
        status__in=MEMBER_PERMISSION_STATUSES,
    ).filter(Q(user__isnull=True) | Q(user__is_active=True))
    if permission_requires_covenanter(permission_code):
        queryset = queryset.filter(member_role_filter(ROLE_COVENANTER))
    return (
        queryset.filter(
            role_assignments__status=RoleAssignment.Status.ACTIVE,
            role_assignments__role__status=Role.Status.ACTIVE,
            role_assignments__start_at__lte=checked_at,
            role_assignments__end_at__gt=checked_at,
            role_assignments__role__role_permissions__permission__code=permission_code,
        )
        .distinct()
    )
