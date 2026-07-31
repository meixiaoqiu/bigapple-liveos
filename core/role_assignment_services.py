"""角色任命生命周期服务。"""

from __future__ import annotations

from typing import Any

from django.utils import timezone

from .db import atomic_for_model
from .exceptions import DomainError
from .governance_setup import default_role_assignment_end_at, ensure_maintainer_role
from .member_roles import (
    ROLE_FORMAL_MEMBER,
    ROLE_MAINTAINER,
    ensure_catalog_role,
    member_has_role,
)
from .models import Member, Role, RoleAssignment
from .role_catalog import catalog_role_definition_for_role, role_definition_for_name


def _role_requires_formal_member(role: Role) -> bool:
    """判断角色的明确前置条件是否要求当前正式成员资格。"""

    definition = catalog_role_definition_for_role(role)
    if definition is not None:
        return definition.requires_formal_member
    return any(
        str(role_permission.permission.code).startswith(("governance.", "finance."))
        for role_permission in role.role_permissions.select_related("permission")
    )


def validate_role_assignment_prerequisites(member: Member, role: Role) -> None:
    """校验成员是否可被授予角色，不把派生状态写入任命。"""

    if member.status in {Member.Status.SUSPENDED, Member.Status.EXITED}:
        raise DomainError("成员状态已停用，不能授予新角色。")
    if member.user_id and not member.user.is_active:
        raise DomainError("登录账号已停用，不能授予新角色。")

    definition = catalog_role_definition_for_role(role)
    if definition is not None:
        if definition.requires_formal_member and not member_has_role(member, ROLE_FORMAL_MEMBER):
            raise DomainError(f"授予{definition.display_name}前必须具有当前有效正式成员资格。")
        return

    if role_definition_for_name(role.name) is not None:
        raise DomainError("内置角色只能从规范成员资格与职责目录授予。")

    if _role_requires_formal_member(role) and not member_has_role(member, ROLE_FORMAL_MEMBER):
        raise DomainError("授予该角色前必须具有当前有效正式成员资格。")


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
    """创建或复用当前角色任命；不隐式创建其他职责或资格。"""

    if role_definition_for_name(role.name) is not None and catalog_role_definition_for_role(role) is None:
        raise DomainError("内置角色只能从规范成员资格与职责目录授予。")
    if not skip_validation:
        validate_role_assignment_prerequisites(member, role)
    starts_at = start_at or timezone.now()
    effective_end_at = end_at or default_role_assignment_end_at(starts_at)
    RoleAssignment.objects.filter(
        member=member,
        role=role,
        status=RoleAssignment.Status.ACTIVE,
        end_at__lte=starts_at,
    ).update(status=RoleAssignment.Status.EXPIRED)
    assignment = (
        RoleAssignment.objects.filter(
            member=member,
            role=role,
            status=RoleAssignment.Status.ACTIVE,
            end_at__gt=starts_at,
        )
        .order_by("-start_at", "-pk")
        .first()
    )
    if assignment is None:
        assignment = RoleAssignment.objects.create(
            member=member,
            role=role,
            status=RoleAssignment.Status.ACTIVE,
            start_at=starts_at,
            end_at=effective_end_at,
            granted_by=granted_by,
            source_type=source_type,
            source_proposal=source_proposal,
            source_proposal_execution=source_proposal_execution,
        )
    definition = catalog_role_definition_for_role(role)
    if definition is not None and definition.display_name == ROLE_FORMAL_MEMBER:
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
    """撤销一项角色任命而不删除其事实记录。"""

    assignment.status = RoleAssignment.Status.REVOKED
    assignment.revoked_by = revoked_by
    assignment.end_at = end_at or timezone.now()
    assignment.save(update_fields=["status", "revoked_by", "end_at", "updated_at"])
    return assignment


@atomic_for_model(RoleAssignment)
def bootstrap_initial_maintainer(
    member: Member,
    *,
    granted_by: Member | None = None,
) -> dict[str, Any]:
    """初始化一个通用维护者，不创建议事者任期或个人专属授权。"""

    assignments: dict[str, RoleAssignment] = {}
    assignments["formal_member"] = create_role_assignment(
        member=member,
        role=ensure_catalog_role(ROLE_FORMAL_MEMBER),
        granted_by=granted_by,
        source_type=RoleAssignment.SourceType.INITIALIZATION,
    )
    assignments["maintainer"] = create_role_assignment(
        member=member,
        role=ensure_maintainer_role()["role"],
        granted_by=granted_by,
        source_type=RoleAssignment.SourceType.INITIALIZATION,
    )
    return assignments
