"""成员资格与职责事实的查询辅助函数。"""

from __future__ import annotations

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from .models.identity import Member
from .role_catalog import (
    ROLE_DEFINITIONS,
    ROLE_CATALOG_ORGANIZATION_KEY,
    ROLE_CATALOG_ORGANIZATION_NAME,
    ROLE_DELIBERATOR,
    ROLE_FORMAL_MEMBER,
    ROLE_MAINTAINER,
    ensure_catalog_roles,
    role_definition_for_name,
)


WORLD_INSTANCE_SIMULATION = "simulation"
WORLD_INSTANCE_REAL = "real"
MEMBER_ROLE_FACT_STATUSES = frozenset({"active", "admitted"})


def current_world_instance_type() -> str:
    return getattr(settings, "WORLD_INSTANCE_TYPE", WORLD_INSTANCE_SIMULATION)


def world_is_simulation_instance() -> bool:
    return current_world_instance_type() == WORLD_INSTANCE_SIMULATION


def actor_type_for_current_world() -> str:
    return "virtual_member" if world_is_simulation_instance() else "human_member"


def _current_catalog_role_filter(*role_names: str, checked_at=None) -> Q:
    moment = checked_at or timezone.now()
    return (
        Q(status__in=MEMBER_ROLE_FACT_STATUSES)
        & (Q(user__isnull=True) | Q(user__is_active=True))
        & Q(
        role_assignments__role__organization__role_catalog_key=ROLE_CATALOG_ORGANIZATION_KEY,
        role_assignments__role__name__in=role_names,
        role_assignments__status="active",
        role_assignments__role__status="active",
        role_assignments__start_at__lte=moment,
        role_assignments__end_at__gt=moment,
        )
    )


def member_role_filter(*role_names: str, checked_at=None) -> Q:
    """返回查询当前有效规范角色事实所需的 ``Q`` 条件。"""

    if not role_names or any(role_definition_for_name(name) is None for name in role_names):
        return Q(pk__in=[])
    condition = _current_catalog_role_filter(*role_names, checked_at=checked_at)
    if any(role_definition_for_name(name).requires_formal_member for name in role_names):
        formal_members = Member.objects.filter(
            _current_catalog_role_filter(ROLE_FORMAL_MEMBER, checked_at=checked_at)
        ).values("pk")
        condition &= Q(pk__in=formal_members)
    return condition


def active_member_role_names(member: object, *, checked_at=None) -> tuple[str, ...]:
    """返回成员当前有效的规范角色名称，不包含派生状态。"""

    member_id = getattr(member, "pk", None)
    if member_id is None or not member_allows_role_facts(member):
        return ()
    return tuple(
        role_name
        for role_name in sorted(
            (definition.display_name for definition in ROLE_DEFINITIONS),
        )
        if Member.objects.filter(pk=member_id)
        .filter(member_role_filter(role_name, checked_at=checked_at))
        .exists()
    )


def member_has_role(member: object, *role_names: str, checked_at=None) -> bool:
    """判断成员是否具有当前有效的规范角色事实。"""

    if not role_names or any(role_definition_for_name(name) is None for name in role_names):
        return False
    return bool(set(active_member_role_names(member, checked_at=checked_at)).intersection(role_names))


def member_allows_role_facts(member: object) -> bool:
    """判断成员生命周期和登录账号是否允许当前职责生效。"""

    status = str(getattr(member, "status", ""))
    if status not in MEMBER_ROLE_FACT_STATUSES:
        return False
    user_id = getattr(member, "user_id", None)
    if not user_id:
        return True
    user = getattr(member, "user", None)
    return bool(user is not None and user.is_active)


def participation_status(member: object, *, checked_at=None) -> str | None:
    """返回仅用于展示的参与状态；该状态不对应角色任命。"""

    if not member_allows_role_facts(member):
        return None
    if not member_has_role(member, ROLE_FORMAL_MEMBER, checked_at=checked_at):
        return "contributor"
    return None


def ensure_catalog_role(role_name: str):
    """返回目录允许的直接角色，拒绝派生或未知概念。"""

    definition = role_definition_for_name(role_name)
    if definition is None:
        raise ValueError(f"不是可直接授予的规范角色：{role_name}")
    return ensure_catalog_roles()[definition.code]


def ensure_catalog_role_assignments() -> dict[str, object]:
    """幂等创建全部规范角色定义，供初始化和测试使用。"""

    return ensure_catalog_roles()


def ensure_role_assignment(member, role, *, granted_by=None, start_at=None, end_at=None):
    """通过服务创建规范角色任命。"""

    from .models import RoleAssignment
    from .role_assignment_services import create_role_assignment

    return create_role_assignment(
        member=member,
        role=role,
        granted_by=granted_by,
        start_at=start_at,
        end_at=end_at,
        source_type=RoleAssignment.SourceType.INITIALIZATION,
    )


__all__ = [
    "ROLE_DELIBERATOR",
    "ROLE_FORMAL_MEMBER",
    "ROLE_MAINTAINER",
    "ROLE_CATALOG_ORGANIZATION_NAME",
    "active_member_role_names",
    "actor_type_for_current_world",
    "current_world_instance_type",
    "ensure_catalog_role",
    "ensure_catalog_role_assignments",
    "ensure_role_assignment",
    "member_has_role",
    "member_allows_role_facts",
    "member_role_filter",
    "participation_status",
    "world_is_simulation_instance",
]
