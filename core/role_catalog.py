"""新制度的成员资格、职责与权限目录。

目录只定义需要单独记录并参与授权的事实。界面上的参与状态由这些事实
推导，不能反向成为 ``RoleAssignment`` 或 OpenFGA tuple。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


ROLE_CATALOG_ORGANIZATION_NAME = "成员资格与职责"
ROLE_CATALOG_ORGANIZATION_KEY = "member-role-catalog"

ROLE_FORMAL_MEMBER = "正式成员"
ROLE_DELIBERATOR = "议事者"
ROLE_MAINTAINER = "维护者"


class RoleDimension(str, Enum):
    """角色事实所属的业务维度。"""

    MEMBER_QUALIFICATION = "member_qualification"
    DELIBERATION_DUTY = "deliberation_duty"
    MAINTENANCE_DUTY = "maintenance_duty"


class TermRule(str, Enum):
    """角色任命的期限规则。"""

    APPOINTMENT_DEFINED = "appointment_defined"
    ONE_YEAR_SELF_APPLICATION = "one_year_self_application"


@dataclass(frozen=True)
class RoleDefinition:
    """一项可直接写入 ``RoleAssignment`` 的规范化事实。"""

    code: str
    display_name: str
    description: str
    dimension: RoleDimension
    direct_assignable: bool
    requires_formal_member: bool
    term_rule: TermRule
    openfga_relation: str


@dataclass(frozen=True)
class DerivedConceptDefinition:
    """不能创建角色任命的派生概念。"""

    code: str
    display_name: str
    description: str


ROLE_DEFINITIONS: tuple[RoleDefinition, ...] = (
    RoleDefinition(
        code="formal_member",
        display_name=ROLE_FORMAL_MEMBER,
        description="通过正式成员准入后取得的成员资格。",
        dimension=RoleDimension.MEMBER_QUALIFICATION,
        direct_assignable=True,
        requires_formal_member=False,
        term_rule=TermRule.APPOINTMENT_DEFINED,
        openfga_relation="formal_member",
    ),
    RoleDefinition(
        code="deliberator",
        display_name=ROLE_DELIBERATOR,
        description="正式成员主动申请、承担参与义务的一年期议事职责。",
        dimension=RoleDimension.DELIBERATION_DUTY,
        direct_assignable=True,
        requires_formal_member=True,
        term_rule=TermRule.ONE_YEAR_SELF_APPLICATION,
        openfga_relation="deliberator",
    ),
    RoleDefinition(
        code="maintainer",
        display_name=ROLE_MAINTAINER,
        description="通过正常程序取得、只包含明确维护权限的独立职责。",
        dimension=RoleDimension.MAINTENANCE_DUTY,
        direct_assignable=True,
        requires_formal_member=True,
        term_rule=TermRule.APPOINTMENT_DEFINED,
        openfga_relation="maintainer",
    ),
)

DERIVED_CONCEPT_DEFINITIONS: tuple[DerivedConceptDefinition, ...] = (
    DerivedConceptDefinition(
        code="contributor",
        display_name="贡献者",
        description="已注册且没有当前有效正式成员资格的参与状态。",
    ),
    DerivedConceptDefinition(
        code="anonymous_observation",
        display_name="匿名观察",
        description="未注册用户访问公开内容时的行为，不是身份或角色。",
    ),
    DerivedConceptDefinition(
        code="formal_member_application",
        display_name="正式成员申请",
        description="申请流程状态，不是身份或角色。",
    ),
)

# 初始化维护者时可复用的具体权限。角色目录只说明初始集合；实际授权仍由
# ``RolePermission`` 和 ``AuthorizationService`` 决定。
MAINTAINER_PERMISSION_CODES: tuple[str, ...] = (
    "governance.view_admin",
    "governance.manage_people",
    "governance.manage_organizations",
    "governance.manage_roles",
    "governance.manage_permissions",
    "governance.manage_professional_qualifications",
    "governance.view_event_ledger",
)


def role_definition_for_name(name: str) -> RoleDefinition | None:
    """返回规范角色定义；未知或派生概念一律返回 ``None``。"""

    return next((item for item in ROLE_DEFINITIONS if item.display_name == name), None)


def catalog_role_definition_for_role(role: object) -> RoleDefinition | None:
    """仅在角色属于唯一规范目录时返回其内置角色定义。"""

    definition = role_definition_for_name(str(getattr(role, "name", "")))
    organization_id = getattr(role, "organization_id", None)
    if definition is None or organization_id is None:
        return None

    from .models import Organization

    is_catalog_organization = Organization.objects.filter(
        pk=organization_id,
        role_catalog_key=ROLE_CATALOG_ORGANIZATION_KEY,
        name=ROLE_CATALOG_ORGANIZATION_NAME,
        status=Organization.Status.ACTIVE,
    ).exists()
    return definition if is_catalog_organization else None


def role_definition_for_code(code: str) -> RoleDefinition | None:
    """按稳定代码查询规范角色定义。"""

    return next((item for item in ROLE_DEFINITIONS if item.code == code), None)


def derived_concept_for_code(code: str) -> DerivedConceptDefinition | None:
    """按稳定代码查询派生概念。"""

    return next((item for item in DERIVED_CONCEPT_DEFINITIONS if item.code == code), None)


def validate_role_catalog() -> list[str]:
    """返回目录自身的配置错误，供测试和项目检查使用。"""

    errors: list[str] = []
    role_codes = [item.code for item in ROLE_DEFINITIONS]
    role_names = [item.display_name for item in ROLE_DEFINITIONS]
    role_relations = [item.openfga_relation for item in ROLE_DEFINITIONS]
    derived_codes = [item.code for item in DERIVED_CONCEPT_DEFINITIONS]
    derived_names = [item.display_name for item in DERIVED_CONCEPT_DEFINITIONS]

    for label, values in (
        ("角色稳定代码", role_codes),
        ("角色显示名称", role_names),
        ("OpenFGA 关系", role_relations),
        ("派生概念稳定代码", derived_codes),
        ("派生概念显示名称", derived_names),
    ):
        if len(values) != len(set(values)):
            errors.append(f"角色目录存在重复{label}。")

    direct_dimensions = [item.dimension for item in ROLE_DEFINITIONS if item.direct_assignable]
    if len(direct_dimensions) != len(set(direct_dimensions)):
        errors.append("每个角色维度只能有一个内置直接事实。")

    formal_member = role_definition_for_name(ROLE_FORMAL_MEMBER)
    if formal_member is None or formal_member.requires_formal_member:
        errors.append("正式成员资格必须是无需既有正式成员资格的直接事实。")

    for definition in ROLE_DEFINITIONS:
        if definition.display_name == ROLE_FORMAL_MEMBER:
            continue
        if not definition.requires_formal_member:
            errors.append(f"{definition.display_name}必须以前有效正式成员资格为前置条件。")

    if set(role_codes).intersection(derived_codes):
        errors.append("派生概念不能与直接角色共用稳定代码。")
    if set(role_names).intersection(derived_names):
        errors.append("派生概念不能与直接角色共用显示名称。")
    if not MAINTAINER_PERMISSION_CODES:
        errors.append("维护者必须至少具有一项初始化维护权限。")
    return errors


def ensure_catalog_roles() -> dict[str, object]:
    """幂等创建新制度目录中的直接角色。

    本函数只创建目录允许的三项角色，不为派生概念创建 ``Role`` 或
    ``RoleAssignment``。调用方仍必须通过角色任命服务写入成员事实。
    """

    from .models import Organization, Role

    organization, _ = Organization.objects.get_or_create(
        role_catalog_key=ROLE_CATALOG_ORGANIZATION_KEY,
        defaults={
            "name": ROLE_CATALOG_ORGANIZATION_NAME,
            "status": Organization.Status.ACTIVE,
        },
    )
    changed_fields: list[str] = []
    if organization.name != ROLE_CATALOG_ORGANIZATION_NAME:
        organization.name = ROLE_CATALOG_ORGANIZATION_NAME
        changed_fields.append("name")
    if organization.status != Organization.Status.ACTIVE:
        organization.status = Organization.Status.ACTIVE
        changed_fields.append("status")
    if changed_fields:
        organization.save(update_fields=[*changed_fields, "updated_at"])

    roles: dict[str, Role] = {}
    for definition in ROLE_DEFINITIONS:
        role, _ = Role.objects.get_or_create(
            organization=organization,
            name=definition.display_name,
            defaults={
                "description": definition.description,
                "status": Role.Status.ACTIVE,
            },
        )
        if role.status != Role.Status.ACTIVE or role.description != definition.description:
            role.status = Role.Status.ACTIVE
            role.description = definition.description
            role.save(update_fields=["status", "description", "updated_at"])
        roles[definition.code] = role
    return roles
