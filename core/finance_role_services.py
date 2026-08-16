"""统一提案系统迁移期间的财务职责任命边界。"""

from __future__ import annotations

from .authorization_services import AuthorizationService
from .finance_setup import ensure_finance_roles
from .governance_setup import MANAGE_ROLES_PERMISSION
from .models import Member, Role
from .proposal_migration import raise_proposal_flow_unavailable


def member_can_manage_finance_roles(member: Member) -> bool:
    """返回成员是否拥有财务职责任命管理权限；此判断不开放任命写操作。"""

    return AuthorizationService().member_has_permission(member, MANAGE_ROLES_PERMISSION)


def finance_review_role() -> Role:
    """返回规范财务审核角色，用于只读展示。"""

    return ensure_finance_roles()["review_role"]


def finance_review_appointment_proposals():
    """禁止继续读取旧提案列表。"""

    raise_proposal_flow_unavailable()


def nominate_finance_reviewer(*, actor: Member, target_member: Member, reason: str = ""):
    """关闭尚未迁移的财务职责任命，不得直接授予角色。"""

    raise_proposal_flow_unavailable()


def vote_on_finance_reviewer_appointment(*, actor: Member, proposal, choice: str, reason: str = ""):
    """关闭尚未迁移的财务职责表决。"""

    raise_proposal_flow_unavailable()


def execute_finance_reviewer_appointment(*, actor: Member, proposal):
    """关闭尚未迁移的财务职责任命执行。"""

    raise_proposal_flow_unavailable()
