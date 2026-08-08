"""执衡者任期的自助申请服务。"""

from __future__ import annotations

from django.utils import timezone

from .db import atomic_for_model
from .exceptions import DomainError
from .member_roles import ROLE_DELIBERATOR, ROLE_COVENANTER, ensure_catalog_role, member_has_role
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
    """Reject the legacy direct path; members must pass the qualification exam."""
    raise DomainError("请通过成员工作台参加执衡者资格考试。")
