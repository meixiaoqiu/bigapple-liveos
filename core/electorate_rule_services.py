"""版本化选民规则的验证、发布、快照和实时资格评估。"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .authorization_services import AuthorizationService
from .exceptions import DomainError
from .member_roles import member_allows_role_facts, participation_status
from .models import (
    ApprovalProposal,
    ElectorateRuleTemplate,
    ElectorateRuleVersion,
    Member,
    MemberProfessionalQualification,
    ProfessionalDomain,
    ProposalElectorSnapshot,
)
from .role_catalog import role_definition_for_code


MANAGE_PROPOSAL_POLICIES_PERMISSION = "governance.manage_proposal_policies"
SUPPORTED_PARTICIPATION_STATUSES = frozenset({"contributor"})
MAX_SELECTOR_DEPTH = 8


@dataclass(frozen=True)
class ElectorateEligibility:
    allowed: bool
    reason_code: str
    message: str
    evidence: dict


def _validate_selector_node(node: object, *, depth: int = 0) -> None:
    if depth > MAX_SELECTOR_DEPTH:
        raise DomainError("选民规则嵌套层级过深。")
    if not isinstance(node, dict) or len(node) != 1:
        raise DomainError("每个选民选择器必须是只含一种条件的对象。")
    key, value = next(iter(node.items()))
    if key in {"all", "any"}:
        if not isinstance(value, list) or not value:
            raise DomainError(f"{key} 条件必须包含至少一个子条件。")
        for child in value:
            _validate_selector_node(child, depth=depth + 1)
        return
    if key == "not":
        _validate_selector_node(value, depth=depth + 1)
        return
    if key == "role_code":
        if not isinstance(value, str) or role_definition_for_code(value) is None:
            raise DomainError("选民规则引用了未知规范角色代码。")
        return
    if key == "participation_status":
        if value not in SUPPORTED_PARTICIPATION_STATUSES:
            raise DomainError("选民规则引用了未知派生参与状态。")
        return
    if key == "professional_domain":
        if not isinstance(value, str) or not ProfessionalDomain.objects.filter(
            code=value, status=ProfessionalDomain.Status.ACTIVE,
        ).exists():
            raise DomainError("选民规则引用了未知或已归档的专业领域。")
        return
    raise DomainError("选民规则包含不受支持的条件类型。")


def validate_selector_config(selector_config: object) -> dict:
    """校验并返回可持久化的选择器配置，拒绝任意查询或代码。"""

    _validate_selector_node(selector_config)
    return dict(selector_config)


def _active_professional_domain_codes(member: Member, *, checked_at) -> set[str]:
    return set(
        MemberProfessionalQualification.objects.filter(
            member=member,
            status=MemberProfessionalQualification.Status.ACTIVE,
            valid_from__lte=checked_at,
        )
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gt=checked_at))
        .values_list("domain__code", flat=True)
    )


def _evaluate_selector_node(node: dict, *, member: Member, checked_at, evidence: list[dict]) -> bool:
    key, value = next(iter(node.items()))
    if key == "all":
        return all(
            _evaluate_selector_node(child, member=member, checked_at=checked_at, evidence=evidence)
            for child in value
        )
    if key == "any":
        return any(
            _evaluate_selector_node(child, member=member, checked_at=checked_at, evidence=evidence)
            for child in value
        )
    if key == "not":
        return not _evaluate_selector_node(value, member=member, checked_at=checked_at, evidence=evidence)
    if key == "role_code":
        definition = role_definition_for_code(value)
        matched = bool(
            definition
            and AuthorizationService().member_has_platform_role(member, value, at_time=checked_at)
        )
    elif key == "participation_status":
        matched = participation_status(member, checked_at=checked_at) == value
    elif key == "professional_domain":
        matched = value in _active_professional_domain_codes(member, checked_at=checked_at)
    else:  # 配置在持久化前已经验证；运行时仍失败关闭。
        raise DomainError("选民规则包含无法评估的条件。")
    evidence.append({"condition": key, "value": value, "matched": matched})
    return matched


def evaluate_rule_for_member(
    *,
    rule_version: ElectorateRuleVersion,
    member: Member,
    checked_at=None,
    excluded_member_id: object | None = None,
) -> ElectorateEligibility:
    """根据不可变规则版本计算成员当前资格并返回可解释结果。"""

    moment = checked_at or timezone.now()
    AuthorizationService().ensure_authorization_available(member)
    if excluded_member_id is not None and str(member.pk) == str(excluded_member_id):
        return ElectorateEligibility(False, "excluded_source_actor", "申请人不能参与自己的准入决定。", {})
    if not member_allows_role_facts(member):
        return ElectorateEligibility(False, "member_inactive", "当前成员或登录账号不可参与。", {})
    validate_selector_config(rule_version.selector_config)
    evidence: list[dict] = []
    allowed = _evaluate_selector_node(
        rule_version.selector_config,
        member=member,
        checked_at=moment,
        evidence=evidence,
    )
    if not allowed:
        return ElectorateEligibility(False, "rule_not_satisfied", "你当前不满足该提案的选民规则。", {"conditions": evidence})
    return ElectorateEligibility(True, "eligible", "你属于本提案冻结的选民范围，并且当前资格有效。", {"conditions": evidence})


@transaction.atomic
def create_electorate_rule_template(
    *, proposal_type: str, rule_code: str, name: str, created_by: Member, description: str = "",
) -> ElectorateRuleTemplate:
    """创建选民规则模板；调用者必须具有提案政策维护权限。"""

    if not AuthorizationService().member_has_permission(created_by, MANAGE_PROPOSAL_POLICIES_PERMISSION):
        raise DomainError("你无权维护提案政策。")
    if not rule_code or not proposal_type:
        raise DomainError("规则代码和适用提案类型不能为空。")
    template, created = ElectorateRuleTemplate.objects.get_or_create(
        rule_code=rule_code,
        defaults={
            "proposal_type": proposal_type,
            "name": name,
            "description": description,
            "created_by": created_by,
            "created_at": timezone.now(),
            "updated_at": timezone.now(),
        },
    )
    if not created and template.proposal_type != proposal_type:
        raise DomainError("规则代码已经属于其他提案类型。")
    return template


@transaction.atomic
def publish_electorate_rule_version(
    *,
    template: ElectorateRuleTemplate,
    selector_config: object,
    approve_threshold: int,
    reject_threshold: int,
    minimum_participation: int,
    voting_duration_hours: int,
    unresolved_outcome: str,
    published_by: Member,
) -> ElectorateRuleVersion:
    """发布不可变规则版本；已发布行只能由后续版本取代。"""

    if not AuthorizationService().member_has_permission(published_by, MANAGE_PROPOSAL_POLICIES_PERMISSION):
        raise DomainError("你无权发布提案政策。")
    locked = ElectorateRuleTemplate.objects.select_for_update().get(pk=template.pk)
    if not locked.is_active:
        raise DomainError("该选民规则模板已停止发布。")
    validated = validate_selector_config(selector_config)
    if min(approve_threshold, reject_threshold, voting_duration_hours) < 1 or minimum_participation < 0:
        raise DomainError("阈值和表决期限必须使用有效正整数。")
    if unresolved_outcome not in {value for value, _ in ElectorateRuleVersion.UnresolvedOutcome.choices}:
        raise DomainError("未决处理方式无效。")
    previous = locked.versions.order_by("-version").first()
    version = 1 if previous is None else previous.version + 1
    rule_version = ElectorateRuleVersion.objects.create(
        rule_version_id=f"rule-version-{uuid4().hex[:16]}",
        template=locked,
        version=version,
        selector_config=validated,
        approve_threshold=approve_threshold,
        reject_threshold=reject_threshold,
        minimum_participation=minimum_participation,
        voting_duration_hours=voting_duration_hours,
        unresolved_outcome=unresolved_outcome,
        published_by=published_by,
        published_at=timezone.now(),
    )
    from .event_ledger import append_event
    from .event_payloads import electorate_rule_payload
    from .models import SystemEvent

    append_event(
        event_type=SystemEvent.EventType.ELECTORATE_RULE_PUBLISHED,
        aggregate_type="ElectorateRuleVersion",
        aggregate_id=rule_version.rule_version_id,
        actor_member=published_by,
        payload_json=electorate_rule_payload(rule_version, actor=published_by),
        occurred_at=rule_version.published_at,
    )
    return rule_version


def latest_published_rule_for_proposal_type(proposal_type: str) -> ElectorateRuleVersion | None:
    """返回提案类型当前最新的已发布规则版本。"""

    return (
        ElectorateRuleVersion.objects.select_related("template")
        .filter(template__proposal_type=proposal_type, template__is_active=True)
        .order_by("-published_at", "-version")
        .first()
    )


@transaction.atomic
def generate_elector_snapshot(
    *, proposal: ApprovalProposal, excluded_member_id: object | None = None,
) -> int:
    """为表决提案幂等生成选民快照，只写入满足冻结规则的成员。"""

    locked = ApprovalProposal.objects.select_for_update().select_related("electorate_rule_version").get(pk=proposal.pk)
    if locked.electorate_rule_version_id is None:
        raise DomainError("提案没有已发布的选民规则版本。")
    if locked.elector_snapshots.exists():
        return locked.elector_snapshots.count()
    moment = locked.voting_started_at or timezone.now()
    snapshots = []
    for member in Member.objects.select_related("user").all().order_by("pk"):
        decision = evaluate_rule_for_member(
            rule_version=locked.electorate_rule_version,
            member=member,
            checked_at=moment,
            excluded_member_id=excluded_member_id,
        )
        if decision.allowed:
            snapshots.append(ProposalElectorSnapshot(
                proposal=locked,
                member=member,
                rule_version=locked.electorate_rule_version,
                qualification_evidence=decision.evidence,
                snapshotted_at=moment,
            ))
    ProposalElectorSnapshot.objects.bulk_create(snapshots)
    return len(snapshots)


def electorate_eligibility_for_proposal(
    *, proposal: ApprovalProposal, member: Member, excluded_member_id: object | None = None,
) -> ElectorateEligibility:
    """同时检查冻结快照和成员当前资格。"""

    if proposal.electorate_rule_version_id is None:
        return ElectorateEligibility(False, "policy_missing", "该提案尚未配置可用选民政策。", {})
    if not ProposalElectorSnapshot.objects.filter(proposal=proposal, member=member).exists():
        return ElectorateEligibility(False, "not_in_snapshot", "你不在本次表决开始时冻结的选民范围内。", {})
    return evaluate_rule_for_member(
        rule_version=proposal.electorate_rule_version,
        member=member,
        excluded_member_id=excluded_member_id,
    )
