"""Member role helpers.

Roles are the unified identity and capability unit for members. A member can
hold multiple active roles through ``RoleAssignment`` records; there is no
single ``Member.role`` field.
"""

from __future__ import annotations

from django.conf import settings
from django.db.models import Q
from django.utils import timezone


MEMBER_ROLE_ORGANIZATION_NAME = "基础角色"

ROLE_BIG_APPLE_MEMBER = "大苹果成员"
ROLE_OBSERVER = "观察者"
ROLE_CONTRIBUTOR = "贡献者"
ROLE_CANDIDATE = "预备成员"
ROLE_FORMAL_MEMBER = "正式成员"
ROLE_GOVERNANCE_MEMBER = "治理成员"

ASSIGNABLE_MEMBER_ROLE_NAMES = (
    ROLE_BIG_APPLE_MEMBER,
    ROLE_CONTRIBUTOR,
    ROLE_FORMAL_MEMBER,
)

WORLD_INSTANCE_SIMULATION = "simulation"
WORLD_INSTANCE_REAL = "real"
DEFAULT_ROLE_ASSIGNMENT_DAYS = 36500


def current_world_instance_type() -> str:
    return getattr(settings, "WORLD_INSTANCE_TYPE", WORLD_INSTANCE_SIMULATION)


def world_is_simulation_instance() -> bool:
    return current_world_instance_type() == WORLD_INSTANCE_SIMULATION


def actor_type_for_current_world() -> str:
    return "virtual_member" if world_is_simulation_instance() else "human_member"


def member_role_filter(*role_names: str) -> Q:
    checked_at = timezone.now()
    return Q(
        role_assignments__role__organization__name=MEMBER_ROLE_ORGANIZATION_NAME,
        role_assignments__role__name__in=role_names,
        role_assignments__status="active",
        role_assignments__role__status="active",
        role_assignments__start_at__lte=checked_at,
        role_assignments__end_at__gte=checked_at,
    )


def active_member_role_names(member: object) -> tuple[str, ...]:
    assignments = getattr(member, "role_assignments", None)
    if assignments is None:
        return ()
    return tuple(
        assignments.filter(
            status="active",
            role__status="active",
            role__organization__name=MEMBER_ROLE_ORGANIZATION_NAME,
            start_at__lte=timezone.now(),
            end_at__gte=timezone.now(),
        ).values_list("role__name", flat=True)
    )


def member_has_role(member: object, *role_names: str) -> bool:
    if not role_names:
        return False
    return bool(set(active_member_role_names(member)).intersection(role_names))


def ensure_member_role_organization():
    from .models import Organization

    organization, _ = Organization.objects.get_or_create(
        name=MEMBER_ROLE_ORGANIZATION_NAME,
        defaults={
            "status": Organization.Status.ACTIVE,
        },
    )
    return organization


def ensure_member_role(role_name: str, description: str = ""):
    from .models import Role

    organization = ensure_member_role_organization()
    role, _ = Role.objects.get_or_create(
        organization=organization,
        name=role_name,
        defaults={"description": description, "status": Role.Status.ACTIVE},
    )
    return role


def ensure_member_roles() -> dict[str, object]:
    descriptions = {
        ROLE_BIG_APPLE_MEMBER: "所有成员默认拥有的基础角色。",
        ROLE_OBSERVER: "只观察系统运行的成员角色。",
        ROLE_CONTRIBUTOR: "可参与任务贡献的成员角色。",
        ROLE_CANDIDATE: "处于准入流程中的预备成员角色。",
        ROLE_FORMAL_MEMBER: "已接纳的正式成员角色。",
        ROLE_GOVERNANCE_MEMBER: "参与治理审核和管理的成员角色；具体权限仍来自角色权限绑定。",
    }
    return {role_name: ensure_member_role(role_name, description) for role_name, description in descriptions.items()}


def ensure_role_assignment(member, role, *, granted_by=None, start_at=None):
    from .models import RoleAssignment
    from .role_assignment_services import create_role_assignment

    return create_role_assignment(
        member=member,
        role=role,
        granted_by=granted_by,
        start_at=start_at,
        source_type=RoleAssignment.SourceType.INITIALIZATION,
    )
