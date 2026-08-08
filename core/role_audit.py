"""只读角色、权限与任命路径盘点。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Any

from django.utils import timezone

from .models import Member, Role, RoleAssignment
from .role_catalog import (
    ROLE_CATALOG_ORGANIZATION_KEY,
    ROLE_CATALOG_ORGANIZATION_NAME,
    ROLE_DEFINITIONS,
    ROLE_COVENANTER,
    catalog_role_definition_for_role,
)


ROLE_ASSIGNMENT_CREATION_PATHS: tuple[dict[str, Any], ...] = (
    {
        "id": "member-registration",
        "entry_points": (
            "core.identity_services.register_member",
            "core.identity_services.ensure_basic_member_for_user",
            "core.identity_services.register_participant_account",
        ),
        "category": "注册",
        "direct_role_facts": (),
        "assessment": "注册只创建 User 和 Member；贡献者状态由成员存在与守约者资格派生。",
        "follow_up_task": "6.2",
    },
    {
        "id": "member-application-submission",
        "entry_points": ("core.application_services.submit_member_application",),
        "category": "守约者申请",
        "direct_role_facts": (),
        "assessment": "申请进度由 MemberApplication 状态表达，不创建角色任命。",
        "follow_up_task": "6.2",
    },
    {
        "id": "member-admission-proposal",
        "entry_points": (
            "core.application_services.admit_member_application_from_proposal",
            "core.proposals.execution.execute_proposal",
        ),
        "category": "守约者准入",
        "direct_role_facts": ("守约者",),
        "assessment": "准入提案执行后只创建守约者资格。",
        "follow_up_task": "4.2",
    },
    {
        "id": "deliberator-self-application",
        "entry_points": (
            "core.deliberator_exam_services._assert_exam_candidate",
            "core.deliberator_exam_services.submit_deliberator_exam",
            "workspace.deliberator_exam_views.deliberator_exam_home",
        ),
        "category": "执衡者申请",
        "direct_role_facts": ("执衡者",),
        "assessment": "有效守约者通过资格考试后创建独立一年期职责；旧直接申请入口已关闭。",
        "follow_up_task": "3.1",
    },
    {
        "id": "initial-maintainer-bootstrap",
        "entry_points": (
            "core.role_assignment_services.bootstrap_initial_maintainer",
            "worlds.management.commands.bootstrap_world",
        ),
        "category": "世界初始化",
        "direct_role_facts": ("守约者", "典守者"),
        "assessment": "初始化只使用可复用的守约者和典守者事实，不创建执衡者任期。",
        "follow_up_task": "3.3",
    },
    {
        "id": "generic-role-appointment-proposal",
        "entry_points": ("core.proposals.execution.execute_proposal",),
        "category": "提案执行",
        "direct_role_facts": ("提案指定角色",),
        "assessment": "通用任命必须经角色目录前置条件与授权边界校验。",
        "follow_up_task": "3.3",
    },
)

ROLE_PRESENTATION_SURFACES: tuple[dict[str, str | bool], ...] = (
    {
        "id": "workspace-permission-gates",
        "surface": "工作台",
        "entry_points": "workspace 的具体权限检查。",
        "current_behavior": "访问控制不读取身份显示结果。",
        "change_target": "6.1",
        "requires_contract_update": False,
    },
    {
        "id": "workspace-member-summary",
        "surface": "工作台",
        "entry_points": "workspace 的成员身份摘要。",
        "current_behavior": "需统一改为读取身份显示服务。",
        "change_target": "6.3",
        "requires_contract_update": False,
    },
    {
        "id": "observer-identity-badges",
        "surface": "公开观察页",
        "entry_points": "observer.member_profiles 的身份徽章。",
        "current_behavior": "需统一改为读取身份显示服务。",
        "change_target": "6.3",
        "requires_contract_update": False,
    },
    {
        "id": "django-admin-member-roles",
        "surface": "Django Admin",
        "entry_points": "core.admin_identity 的只读任命信息。",
        "current_behavior": "需统一改为读取身份显示服务。",
        "change_target": "6.3",
        "requires_contract_update": False,
    },
    {
        "id": "api-member-payload",
        "surface": "公开 API",
        "entry_points": "live_os.api 的成员和提案载荷。",
        "current_behavior": "改变公开字段或值前必须先更新 technical contract。",
        "change_target": "4.1、6.3",
        "requires_contract_update": True,
    },
)

_ASSIGNMENT_STATUSES = tuple(RoleAssignment.Status.values)
_ASSIGNMENT_SOURCES = tuple(RoleAssignment.SourceType.values)


def build_role_inventory(*, world: object | None, checked_at=None) -> dict[str, Any]:
    """构建当前 world 的只读角色、权限与任命盘点报告。"""

    moment = checked_at or timezone.now()
    roles = list(
        Role.objects.select_related("organization")
        .prefetch_related("role_permissions__permission")
        .order_by("organization__name", "name", "pk")
    )
    assignments = list(
        RoleAssignment.objects.select_related("member", "member__user", "role", "role__organization").order_by("pk")
    )
    assignments_by_role = _group_assignments(assignments)
    catalog_roles_by_name = {
        role.name: role for role in roles if catalog_role_definition_for_role(role) is not None
    }
    unclassified_roles = [role for role in roles if catalog_role_definition_for_role(role) is None]
    role_entries: list[dict[str, Any]] = []

    for definition in ROLE_DEFINITIONS:
        role = catalog_roles_by_name.get(definition.display_name)
        role_entries.append(
            _role_entry(
                role=role,
                assignments=assignments_by_role.get(role.pk, ()) if role is not None else (),
                all_assignments=assignments,
                checked_at=moment,
                catalog={
                    "builtin": True,
                    "stable_code": definition.code,
                    "expected_catalog_key": ROLE_CATALOG_ORGANIZATION_KEY,
                    "expected_organization": ROLE_CATALOG_ORGANIZATION_NAME,
                    "expected_name": definition.display_name,
                    "dimension": definition.dimension.value,
                    "direct_assignable": definition.direct_assignable,
                    "requires_covenanter": definition.requires_covenanter,
                    "term_rule": definition.term_rule.value,
                    "openfga_relation": definition.openfga_relation,
                },
            )
        )

    for role in unclassified_roles:
        role_entries.append(
            _role_entry(
                role=role,
                assignments=assignments_by_role.get(role.pk, ()),
                all_assignments=assignments,
                checked_at=moment,
                catalog={
                    "builtin": False,
                    "stable_code": "",
                    "expected_catalog_key": "",
                    "expected_organization": "",
                    "expected_name": "",
                    "dimension": "unclassified",
                    "direct_assignable": False,
                    "requires_covenanter": _role_requires_covenanter(role),
                    "term_rule": "unclassified",
                    "openfga_relation": "",
                },
            )
        )

    return {
        "scope": _scope_payload(world),
        "checked_at": moment.isoformat(),
        "summary": {
            "builtin_role_definitions": len(ROLE_DEFINITIONS),
            "database_roles": len(roles),
            "reported_roles": len(role_entries),
            "role_assignments": len(assignments),
            "active_role_assignments": sum(
                assignment.status == RoleAssignment.Status.ACTIVE for assignment in assignments
            ),
        },
        "assignment_creation_paths": [
            {**path, "entry_points": list(path["entry_points"]), "direct_role_facts": list(path["direct_role_facts"])}
            for path in ROLE_ASSIGNMENT_CREATION_PATHS
        ],
        "presentation_surfaces": [dict(surface) for surface in ROLE_PRESENTATION_SURFACES],
        "roles": role_entries,
    }


def _role_entry(
    *,
    role: Role | None,
    assignments: Iterable[RoleAssignment],
    all_assignments: Iterable[RoleAssignment],
    checked_at,
    catalog: dict[str, Any],
) -> dict[str, Any]:
    role_assignments = list(assignments) if role is not None else []
    effective_assignments = [
        assignment
        for assignment in role_assignments
        if assignment.status == RoleAssignment.Status.ACTIVE
        and assignment.role.status == Role.Status.ACTIVE
        and assignment.start_at <= checked_at < assignment.end_at
    ]
    status_counts = Counter(assignment.status for assignment in role_assignments)
    source_counts = Counter(assignment.source_type for assignment in role_assignments)
    return {
        "role": {
            "id": role.pk if role is not None else None,
            "exists": role is not None,
            "organization": role.organization.name if role is not None else catalog["expected_organization"],
            "name": role.name if role is not None else catalog["expected_name"],
            "status": role.status if role is not None else "missing",
            "description": role.description if role is not None else "",
        },
        "catalog": catalog,
        "assignment_counts": {
            "total": len(role_assignments),
            "currently_effective": len(effective_assignments),
            "by_status": {status: status_counts[status] for status in _ASSIGNMENT_STATUSES},
            "by_source": {source: source_counts[source] for source in _ASSIGNMENT_SOURCES},
        },
        "prerequisite_compliance": _prerequisite_compliance(
            assignments=effective_assignments,
            all_assignments=all_assignments,
            requires_covenanter=bool(catalog["requires_covenanter"]),
            checked_at=checked_at,
        ),
        "permission_bindings": _permission_bindings(role),
    }


def _group_assignments(assignments: Iterable[RoleAssignment]) -> dict[int, list[RoleAssignment]]:
    grouped: dict[int, list[RoleAssignment]] = {}
    for assignment in assignments:
        grouped.setdefault(assignment.role_id, []).append(assignment)
    return grouped


def _permission_bindings(role: Role | None) -> list[dict[str, Any]]:
    if role is None:
        return []
    return [
        {
            "permission_code": item.permission.code,
            "permission_name": item.permission.name,
            "category": item.permission.category,
            "scope": item.scope,
            "constraints": item.constraints_json or {},
        }
        for item in sorted(role.role_permissions.all(), key=lambda item: (item.permission.code, item.scope, item.pk))
    ]


def _role_requires_covenanter(role: Role) -> bool:
    definition = catalog_role_definition_for_role(role)
    if definition is not None:
        return definition.requires_covenanter
    return any(
        item.permission.code.startswith(("governance.", "finance.")) for item in role.role_permissions.all()
    )


def _prerequisite_compliance(
    *,
    assignments: Iterable[RoleAssignment],
    all_assignments: Iterable[RoleAssignment],
    requires_covenanter: bool,
    checked_at,
) -> dict[str, Any]:
    current_assignments = list(assignments)
    if not requires_covenanter:
        return {"requires_covenanter": False, "checked_effective_assignments": len(current_assignments), "missing_covenanter": 0, "disabled_member": 0, "inactive_user": 0}

    qualified_member_ids = {
        assignment.member_id
        for assignment in all_assignments
        if catalog_role_definition_for_role(assignment.role) is not None
        and assignment.role.name == ROLE_COVENANTER
        and assignment.status == RoleAssignment.Status.ACTIVE
        and assignment.role.status == Role.Status.ACTIVE
        and assignment.start_at <= checked_at < assignment.end_at
    }
    disabled_statuses = {Member.Status.SUSPENDED, Member.Status.EXITED}
    return {
        "requires_covenanter": True,
        "checked_effective_assignments": len(current_assignments),
        "missing_covenanter": sum(item.member_id not in qualified_member_ids for item in current_assignments),
        "disabled_member": sum(item.member.status in disabled_statuses for item in current_assignments),
        "inactive_user": sum(bool(item.member.user_id and not item.member.user.is_active) for item in current_assignments),
    }


def _scope_payload(world: object | None) -> dict[str, str]:
    if world is None:
        return {"world_id": "default", "world_type": "default", "database_alias": "default"}
    return {
        "world_id": str(getattr(world, "world_id", "")),
        "world_type": str(getattr(world, "world_type", "")),
        "database_alias": str(getattr(world, "database_alias", "")),
    }
