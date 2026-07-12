"""Baseline governance permissions and roles."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.utils import timezone

from .models import Organization, Permission, Role, RolePermission


GOVERNANCE_VIEW_ADMIN_PERMISSION = "governance.view_admin"

BASE_GOVERNANCE_PERMISSIONS = (
    {
        "code": GOVERNANCE_VIEW_ADMIN_PERMISSION,
        "name": "查看治理后台",
        "category": "governance",
        "description": "允许访问治理和运营维护入口。",
    },
    {
        "code": "governance.manage_people",
        "name": "管理成员",
        "category": "governance",
        "description": "允许维护 Member 成员和治理责任主体。",
    },
    {
        "code": "governance.manage_organizations",
        "name": "管理组织",
        "category": "governance",
        "description": "允许维护治理组织容器。",
    },
    {
        "code": "governance.manage_roles",
        "name": "管理角色",
        "category": "governance",
        "description": "允许维护组织内角色和任命。",
    },
    {
        "code": "governance.manage_permissions",
        "name": "管理权限",
        "category": "governance",
        "description": "允许维护治理权限定义和角色权限绑定。",
    },
    {
        "code": "governance.view_event_ledger",
        "name": "查看统一事件账本",
        "category": "governance",
        "description": "允许查看只追加统一事件账本。",
    },
)

GOVERNANCE_ADMIN_ORGANIZATION_NAME = "大苹果治理组"
GOVERNANCE_ADMIN_ROLE_NAME = "治理管理员"
DEFAULT_ROLE_ASSIGNMENT_DAYS = 36500


def default_role_assignment_end_at(start_at=None):
    return (start_at or timezone.now()) + timedelta(days=DEFAULT_ROLE_ASSIGNMENT_DAYS)


def ensure_governance_admin_role() -> dict[str, Any]:
    """Ensure baseline governance permissions and the governance-admin role exist."""

    created_permissions = 0
    for item in BASE_GOVERNANCE_PERMISSIONS:
        _permission, created = Permission.objects.get_or_create(
            code=item["code"],
            defaults={
                "name": item["name"],
                "category": item["category"],
                "description": item["description"],
            },
        )
        created_permissions += int(created)

    organization, organization_created = Organization.objects.get_or_create(
        name=GOVERNANCE_ADMIN_ORGANIZATION_NAME,
        defaults={
            "status": Organization.Status.ACTIVE,
        },
    )
    if organization.status != Organization.Status.ACTIVE:
        organization.status = Organization.Status.ACTIVE
        organization.save(update_fields=["status", "updated_at"])

    role, role_created = Role.objects.get_or_create(
        organization=organization,
        name=GOVERNANCE_ADMIN_ROLE_NAME,
        defaults={
            "description": "拥有基础治理后台和治理内核维护权限的管理员角色。",
            "status": Role.Status.ACTIVE,
        },
    )
    if role.status != Role.Status.ACTIVE:
        role.status = Role.Status.ACTIVE
        role.save(update_fields=["status", "updated_at"])

    created_bindings = 0
    permission_codes = [item["code"] for item in BASE_GOVERNANCE_PERMISSIONS]
    for permission in Permission.objects.filter(code__in=permission_codes):
        _binding, created = RolePermission.objects.get_or_create(
            role=role,
            permission=permission,
            scope="global",
            defaults={"constraints_json": {}},
        )
        created_bindings += int(created)

    return {
        "permissions_created": created_permissions,
        "organization": organization,
        "organization_created": organization_created,
        "role": role,
        "role_created": role_created,
        "role_permissions_created": created_bindings,
    }
