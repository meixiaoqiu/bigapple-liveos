"""Baseline finance permissions and roles."""

from __future__ import annotations

from typing import Any

from .models import Organization, Permission, Role, RolePermission


FINANCE_REVIEW_PERMISSION = "finance.review"
FINANCE_PAY_PERMISSION = "finance.pay"
FINANCE_VIEW_PRIVATE_PERMISSION = "finance.view_private"

FINANCE_ORGANIZATION_NAME = "大苹果财务组"
FINANCE_REVIEW_ROLE_NAME = "财务审核员"
FINANCE_PAY_ROLE_NAME = "财务付款员"

BASE_FINANCE_PERMISSIONS = (
    {
        "code": FINANCE_REVIEW_PERMISSION,
        "name": "审核财务申请",
        "category": "finance",
        "description": "允许审核成员提交的报销申请。",
    },
    {
        "code": FINANCE_PAY_PERMISSION,
        "name": "记录财务付款",
        "category": "finance",
        "description": "允许将已批准的报销申请标记为已付款并生成财务流水。",
    },
    {
        "code": FINANCE_VIEW_PRIVATE_PERMISSION,
        "name": "查看私密财务材料",
        "category": "finance",
        "description": "预留权限：允许查看非公开财务凭证或隐私材料。",
    },
)


def ensure_finance_roles() -> dict[str, Any]:
    """Ensure baseline finance permissions and finance roles exist."""

    created_permissions = 0
    permissions: dict[str, Permission] = {}
    for item in BASE_FINANCE_PERMISSIONS:
        permission, created = Permission.objects.get_or_create(
            code=item["code"],
            defaults={
                "name": item["name"],
                "category": item["category"],
                "description": item["description"],
            },
        )
        created_permissions += int(created)
        permissions[item["code"]] = permission

    organization, organization_created = Organization.objects.get_or_create(
        name=FINANCE_ORGANIZATION_NAME,
        defaults={"status": Organization.Status.ACTIVE},
    )
    if organization.status != Organization.Status.ACTIVE:
        organization.status = Organization.Status.ACTIVE
        organization.save(update_fields=["status", "updated_at"])

    review_role, review_role_created = Role.objects.get_or_create(
        organization=organization,
        name=FINANCE_REVIEW_ROLE_NAME,
        defaults={
            "description": "负责审核成员报销申请的财务治理角色。",
            "status": Role.Status.ACTIVE,
        },
    )
    pay_role, pay_role_created = Role.objects.get_or_create(
        organization=organization,
        name=FINANCE_PAY_ROLE_NAME,
        defaults={
            "description": "负责记录已批准报销付款的财务治理角色。",
            "status": Role.Status.ACTIVE,
        },
    )
    for role in (review_role, pay_role):
        if role.status != Role.Status.ACTIVE:
            role.status = Role.Status.ACTIVE
            role.save(update_fields=["status", "updated_at"])

    created_bindings = 0
    for permission_code in (FINANCE_REVIEW_PERMISSION, FINANCE_VIEW_PRIVATE_PERMISSION):
        _binding, created = RolePermission.objects.get_or_create(
            role=review_role,
            permission=permissions[permission_code],
            scope="global",
            defaults={"constraints_json": {}},
        )
        created_bindings += int(created)
    for permission_code in (FINANCE_PAY_PERMISSION, FINANCE_VIEW_PRIVATE_PERMISSION):
        _binding, created = RolePermission.objects.get_or_create(
            role=pay_role,
            permission=permissions[permission_code],
            scope="global",
            defaults={"constraints_json": {}},
        )
        created_bindings += int(created)

    return {
        "permissions_created": created_permissions,
        "organization": organization,
        "organization_created": organization_created,
        "review_role": review_role,
        "review_role_created": review_role_created,
        "pay_role": pay_role,
        "pay_role_created": pay_role_created,
        "role_permissions_created": created_bindings,
    }
