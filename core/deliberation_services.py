"""议事者任期的自助申请服务。"""

from __future__ import annotations

from django.utils import timezone

from .db import atomic_for_model
from .exceptions import DomainError
from .member_roles import ROLE_DELIBERATOR, ROLE_FORMAL_MEMBER, ensure_catalog_role, member_has_role
from .models import Member, RoleAssignment
from .role_assignment_services import create_role_assignment


def deliberator_term_end_at(start_at):
    """返回从开始时刻起满一年的任期终点；闰日按次年二月二十八日处理。"""

    try:
        return start_at.replace(year=start_at.year + 1)
    except ValueError:
        return start_at.replace(year=start_at.year + 1, month=2, day=28)


@atomic_for_model(RoleAssignment)
def apply_for_deliberator_term(*, member: Member, at_time=None) -> RoleAssignment:
    """为有效正式成员立即创建一段一年期议事职责。

    本服务不经过审核，也不会续任或延长既有任期。当前任期存在时拒绝重复申请；
    已到期的记录会保留并标记为已过期，再申请时创建新的任命记录。
    """

    starts_at = at_time or timezone.now()
    if not member_has_role(member, ROLE_FORMAL_MEMBER, checked_at=starts_at):
        raise DomainError("只有当前有效的正式成员可以申请议事者任期。")

    role = ensure_catalog_role(ROLE_DELIBERATOR)
    active_assignment = (
        RoleAssignment.objects.filter(
            member=member,
            role=role,
            status=RoleAssignment.Status.ACTIVE,
            start_at__lte=starts_at,
            end_at__gt=starts_at,
        )
        .order_by("-start_at", "-pk")
        .first()
    )
    if active_assignment is not None:
        raise DomainError("当前议事者任期尚未结束，不能重复申请。")

    return create_role_assignment(
        member=member,
        role=role,
        start_at=starts_at,
        end_at=deliberator_term_end_at(starts_at),
        source_type=RoleAssignment.SourceType.SELF_APPLICATION,
    )
