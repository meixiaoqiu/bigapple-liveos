"""典守者的基础维护权限初始化。"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.utils import timezone

from .models import Permission, Role, RolePermission
from .role_catalog import MAINTAINER_PERMISSION_CODES, ROLE_CATALOG_ORGANIZATION_KEY, ROLE_MAINTAINER
from .member_roles import ensure_catalog_role


MAINTENANCE_VIEW_ADMIN_PERMISSION = "governance.view_admin"
PROFESSIONAL_QUALIFICATION_MANAGE_PERMISSION = "governance.manage_professional_qualifications"
DEFAULT_ROLE_ASSIGNMENT_DAYS = 36500

BASE_MAINTENANCE_PERMISSIONS = (
    {
        "code": MAINTENANCE_VIEW_ADMIN_PERMISSION,
        "name": "查看维护后台",
        "category": "governance",
        "description": "允许访问治理和运营维护入口。",
    },
    {
        "code": "governance.manage_people",
        "name": "维护成员",
        "category": "governance",
        "description": "允许维护 Member 成员和责任主体。",
    },
    {
        "code": "governance.manage_organizations",
        "name": "维护组织",
        "category": "governance",
        "description": "允许维护组织容器。",
    },
    {
        "code": "governance.manage_roles",
        "name": "维护角色",
        "category": "governance",
        "description": "允许维护角色和任命。",
    },
    {
        "code": "governance.manage_permissions",
        "name": "维护权限",
        "category": "governance",
        "description": "允许维护权限定义和角色权限绑定。",
    },
    {
        "code": PROFESSIONAL_QUALIFICATION_MANAGE_PERMISSION,
        "name": "维护专业资格",
        "category": "governance",
        "description": "允许录入或撤销成员的专业资格权威事实。",
    },
    {
        "code": "governance.view_event_ledger",
        "name": "查看统一事件账本",
        "category": "governance",
        "description": "允许查看只追加统一事件账本。",
    },
)


def default_role_assignment_end_at(start_at=None):
    return (start_at or timezone.now()) + timedelta(days=DEFAULT_ROLE_ASSIGNMENT_DAYS)


def ensure_maintainer_role() -> dict[str, Any]:
    """幂等初始化典守者及其明确的通用维护权限。"""

    created_permissions = 0
    for item in BASE_MAINTENANCE_PERMISSIONS:
        _permission, created = Permission.objects.get_or_create(
            code=item["code"],
            defaults={
                "name": item["name"],
                "category": item["category"],
                "description": item["description"],
            },
        )
        created_permissions += int(created)

    role_exists = Role.objects.filter(
        organization__role_catalog_key=ROLE_CATALOG_ORGANIZATION_KEY,
        name=ROLE_MAINTAINER,
    ).exists()
    role = ensure_catalog_role(ROLE_MAINTAINER)
    created_bindings = 0
    for permission in Permission.objects.filter(code__in=MAINTAINER_PERMISSION_CODES):
        _binding, created = RolePermission.objects.get_or_create(
            role=role,
            permission=permission,
            scope="global",
            defaults={"constraints_json": {}},
        )
        created_bindings += int(created)

    return {
        "permissions_created": created_permissions,
        "role": role,
        "role_created": not role_exists,
        "role_permissions_created": created_bindings,
    }
