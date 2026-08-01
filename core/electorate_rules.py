"""可配置选民规则的封闭验证、初始化与集合计算。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from django.core.exceptions import ValidationError
from django.db.models import QuerySet
from django.utils import timezone

from .member_roles import MEMBER_ROLE_FACT_STATUSES, member_role_filter
from .models import (
    ElectorateRuleTemplate,
    ElectorateRuleVersion,
    Member,
    ProfessionalDomain,
    Proposal,
    ProposalTypeElectorateRule,
)
from .professional_qualification_services import members_with_current_professional_qualification
from .role_catalog import ROLE_COVENANTER, ROLE_DELIBERATOR, ROLE_MAINTAINER, role_definition_for_code


TEMPLATE_COMMUNITY = "community_deliberation"
TEMPLATE_COVENANTER = "covenanter_matter"
TEMPLATE_PROFESSIONAL = "professional_matter"
TEMPLATE_MAINTAINER = "maintainer_matter"

SELECTOR_TYPES = frozenset(
    {"registered_member", "derived_status", "catalog_role", "professional_qualification"}
)
COMPOSITE_OPERATORS = frozenset({"ALL", "ANY", "NOT"})


def _active_members() -> QuerySet[Member]:
    return Member.objects.filter(status__in=MEMBER_ROLE_FACT_STATUSES).filter(
        user__isnull=True
    ) | Member.objects.filter(status__in=MEMBER_ROLE_FACT_STATUSES, user__is_active=True)


def validate_condition_tree(condition: Any) -> dict[str, Any]:
    """规范化封闭条件树；未知字段、选择器和对象全部失败关闭。"""

    if not isinstance(condition, dict):
        raise ValidationError("选民规则节点必须是对象。")
    operator = condition.get("op")
    if operator == "SELECTOR":
        if set(condition) - {"op", "selector", "value"}:
            raise ValidationError("选民选择器包含不允许的字段。")
        selector = condition.get("selector")
        value = condition.get("value")
        if selector not in SELECTOR_TYPES:
            raise ValidationError("选民规则引用了未注册的选择器。")
        if selector == "registered_member":
            if value not in (None, True):
                raise ValidationError("registered_member 不接受自定义值。")
            return {"op": "SELECTOR", "selector": selector}
        if not isinstance(value, str) or not value.strip():
            raise ValidationError("选民选择器必须引用非空稳定标识。")
        value = value.strip()
        if selector == "derived_status" and value != "contributor":
            raise ValidationError("选民规则引用了未知派生状态。")
        if selector == "catalog_role":
            definition = role_definition_for_code(value)
            if definition is None or not definition.electorate_selectable:
                raise ValidationError("选民规则引用了不可选择的目录角色。")
        if selector == "professional_qualification" and value != "$professional_domain":
            if not ProfessionalDomain.objects.filter(code=value, status=ProfessionalDomain.Status.ACTIVE).exists():
                raise ValidationError("选民规则引用了不存在或停用的专业领域。")
        return {"op": "SELECTOR", "selector": selector, "value": value}
    if operator not in COMPOSITE_OPERATORS:
        raise ValidationError("选民规则只允许 ALL、ANY、NOT 和 SELECTOR。")
    if set(condition) != {"op", "conditions"}:
        raise ValidationError("组合条件只允许 op 和 conditions 字段。")
    children = condition.get("conditions")
    if not isinstance(children, list) or not children:
        raise ValidationError("组合条件必须包含至少一个子条件。")
    if operator == "NOT" and len(children) != 1:
        raise ValidationError("NOT 必须且只能包含一个子条件。")
    return {"op": operator, "conditions": [validate_condition_tree(item) for item in children]}


def bind_rule_parameters(condition: dict[str, Any], parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    """只替换模板显式开放的专业领域参数。"""

    normalized = validate_condition_tree(condition)
    parameters = dict(parameters or {})
    if set(parameters) - {"professional_domain"}:
        raise ValidationError("选民规则包含未开放参数。")
    used_parameters: set[str] = set()

    def bind(node: dict[str, Any]) -> dict[str, Any]:
        if node["op"] == "SELECTOR":
            if node.get("selector") == "professional_qualification" and node.get("value") == "$professional_domain":
                used_parameters.add("professional_domain")
                domain_code = parameters.get("professional_domain")
                if not isinstance(domain_code, str) or not ProfessionalDomain.objects.filter(
                    code=domain_code,
                    status=ProfessionalDomain.Status.ACTIVE,
                ).exists():
                    raise ValidationError("专业事务必须指定启用中的专业领域。")
                return {**node, "value": domain_code}
            return node
        return {"op": node["op"], "conditions": [bind(item) for item in node["conditions"]]}

    bound = bind(normalized)
    if set(parameters) - used_parameters:
        raise ValidationError("选民规则提交了模板未开放的参数。")
    if "$professional_domain" in str(bound):
        raise ValidationError("选民规则仍包含未绑定参数。")
    return validate_condition_tree(bound)


def _selector_member_ids(node: dict[str, Any], *, at_time) -> set[int]:
    selector = node["selector"]
    value = node.get("value")
    active = _active_members().distinct()
    if selector == "registered_member":
        return set(active.values_list("pk", flat=True))
    if selector == "derived_status":
        covenanters = Member.objects.filter(member_role_filter(ROLE_COVENANTER, checked_at=at_time)).values("pk")
        return set(active.exclude(pk__in=covenanters).values_list("pk", flat=True))
    if selector == "catalog_role":
        definition = role_definition_for_code(value)
        if definition is None:
            raise ValidationError("选民规则引用了未知目录角色。")
        return set(active.filter(member_role_filter(definition.display_name, checked_at=at_time)).values_list("pk", flat=True))
    if selector == "professional_qualification":
        domain = ProfessionalDomain.objects.filter(code=value, status=ProfessionalDomain.Status.ACTIVE).first()
        if domain is None:
            raise ValidationError("选民规则引用了不存在或停用的专业领域。")
        qualified = members_with_current_professional_qualification(domain=domain, at_time=at_time)
        return set(active.filter(pk__in=qualified.values("pk")).values_list("pk", flat=True))
    raise ValidationError("选民规则引用了未注册的选择器。")


def evaluate_condition_tree(condition: dict[str, Any], *, at_time=None) -> QuerySet[Member]:
    """以集合运算计算选民，提案流程无需感知具体角色或专业领域。"""

    checked_at = at_time or timezone.now()
    normalized = validate_condition_tree(condition)
    universe = set(_active_members().values_list("pk", flat=True))

    def evaluate(node: dict[str, Any]) -> set[int]:
        if node["op"] == "SELECTOR":
            return _selector_member_ids(node, at_time=checked_at)
        values = [evaluate(item) for item in node["conditions"]]
        if node["op"] == "ALL":
            return set.intersection(*values)
        if node["op"] == "ANY":
            return set.union(*values)
        return universe - values[0]

    return Member.objects.filter(pk__in=evaluate(normalized)).order_by("member_no")


def ensure_electorate_rule_baseline() -> dict[str, ElectorateRuleVersion]:
    """幂等建立四类制度规则模板与当前版本，不改写既有版本内容。"""

    selector = lambda kind, value=None: {
        "op": "SELECTOR",
        "selector": kind,
        **({"value": value} if value is not None else {}),
    }
    definitions = {
        TEMPLATE_COMMUNITY: (
            "社区共议",
            {"op": "ANY", "conditions": [
                selector("derived_status", "contributor"),
                selector("catalog_role", "covenanter"),
                selector("catalog_role", "maintainer"),
                selector("catalog_role", "deliberator"),
            ]},
            {},
        ),
        TEMPLATE_COVENANTER: (
            "守约事务",
            {"op": "ALL", "conditions": [selector("catalog_role", "covenanter"), selector("catalog_role", "deliberator")]},
            {},
        ),
        TEMPLATE_PROFESSIONAL: (
            "专业事务",
            {"op": "ALL", "conditions": [
                selector("catalog_role", "covenanter"),
                selector("catalog_role", "deliberator"),
                selector("professional_qualification", "$professional_domain"),
            ]},
            {"professional_domain": {"type": "professional_domain", "required": True}},
        ),
        TEMPLATE_MAINTAINER: (
            "典守事务",
            selector("catalog_role", "maintainer"),
            {},
        ),
    }
    versions: dict[str, ElectorateRuleVersion] = {}
    for code, (name, condition, parameter_schema) in definitions.items():
        template, _ = ElectorateRuleTemplate.objects.update_or_create(
            code=code,
            defaults={"name": name, "status": ElectorateRuleTemplate.Status.ACTIVE},
        )
        normalized = validate_condition_tree(condition)
        version, created = ElectorateRuleVersion.objects.get_or_create(
            template=template,
            version=1,
            defaults={"condition_json": normalized, "parameter_schema_json": parameter_schema},
        )
        if not created and (version.condition_json != normalized or version.parameter_schema_json != parameter_schema):
            raise ValidationError(f"选民规则 {code} v1 已存在且内容不一致；不可原地改写版本。")
        versions[code] = version

    covenanter_types = {
        Proposal.ProposalType.MEMBER_ADMISSION,
        Proposal.ProposalType.ROLE_APPOINTMENT,
        Proposal.ProposalType.ROLE_REVOCATION,
        Proposal.ProposalType.RULE,
        Proposal.ProposalType.POLICY,
    }
    for proposal_type in covenanter_types:
        ProposalTypeElectorateRule.objects.get_or_create(
            proposal_type=proposal_type,
            template=versions[TEMPLATE_COVENANTER].template,
        )
    for proposal_type, template_code in (
        (Proposal.ProposalType.COMMUNITY, TEMPLATE_COMMUNITY),
        (Proposal.ProposalType.BUDGET, TEMPLATE_PROFESSIONAL),
        (Proposal.ProposalType.MAINTENANCE, TEMPLATE_MAINTAINER),
    ):
        ProposalTypeElectorateRule.objects.get_or_create(
            proposal_type=proposal_type,
            template=versions[template_code].template,
        )
    return versions


def current_electorate_rule_version(code: str) -> ElectorateRuleVersion:
    """返回当前启用模板的最新版本；缺失时建立规范基线。"""

    ensure_electorate_rule_baseline()
    version = (
        ElectorateRuleVersion.objects.filter(
            template__code=code,
            template__status=ElectorateRuleTemplate.Status.ACTIVE,
        )
        .select_related("template")
        .order_by("-version")
        .first()
    )
    if version is None:
        raise ValidationError("选民规则模板不存在或未启用。")
    return version


def publish_electorate_rule_version(
    *,
    actor_member: Member,
    template: ElectorateRuleTemplate,
    condition: dict[str, Any],
    parameter_schema: dict[str, Any] | None = None,
) -> ElectorateRuleVersion:
    """由具备制度维护权限的成员发布不可变规则新版本。"""

    from .authorization_services import AuthorizationService

    if not AuthorizationService().member_can_maintain(
        member=actor_member,
        permission_code="governance.manage_roles",
    ):
        raise ValidationError("只有具备制度维护权限的典守者可以发布选民规则版本。")
    normalized = validate_condition_tree(condition)
    latest = template.versions.order_by("-version").first()
    return ElectorateRuleVersion.objects.create(
        template=template,
        version=(latest.version + 1) if latest else 1,
        condition_json=normalized,
        parameter_schema_json=dict(parameter_schema or {}),
    )


def rule_snapshot_for_proposal(
    *,
    proposal_type: str,
    rule_version: ElectorateRuleVersion,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """验证提案类型边界并生成不可变、可审计的规范化规则快照。"""

    binding = ProposalTypeElectorateRule.objects.filter(
        proposal_type=proposal_type,
        template=rule_version.template,
    ).first()
    if binding is None or rule_version.template.status != ElectorateRuleTemplate.Status.ACTIVE:
        raise ValidationError("该提案类型不允许使用所选选民规则。")
    condition = bind_rule_parameters(deepcopy(rule_version.condition_json), parameters)
    if binding.minimum_condition_json:
        minimum = validate_condition_tree(binding.minimum_condition_json)
        condition = validate_condition_tree({"op": "ALL", "conditions": [minimum, condition]})
    return {
        "template_code": rule_version.template.code,
        "template_name": rule_version.template.name,
        "version": rule_version.version,
        "condition": condition,
        "parameters": dict(parameters or {}),
    }
