"""仿真世界角色与权限基线的重置、装载服务。"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from .deliberation_services import apply_for_deliberator_term
from .electorate_rules import ensure_electorate_rule_baseline
from .governance_setup import ensure_maintainer_role
from .member_roles import ROLE_COVENANTER, ensure_catalog_role
from .models import (
    Member,
    MemberProfessionalQualification,
    ElectorateRuleTemplate,
    ElectorateRuleVersion,
    Proposal,
    ProposalTypeElectorateRule,
    ProposalExecution,
    ProposalVote,
    Role,
    RoleAssignment,
    RolePermission,
    SystemEvent,
)
from .professional_qualification_services import (
    ensure_professional_domain,
    record_external_professional_qualification,
)
from .role_assignment_services import bootstrap_initial_maintainer, create_role_assignment
from .role_catalog import ensure_catalog_roles


BASELINE_DOMAINS = (
    ("finance", "财务", "涉及预算、报销和资金使用的专业领域。"),
    ("construction", "建设", "涉及场地、工程和设施建设的专业领域。"),
    ("operations", "运营", "涉及日常运营安排的专业领域。"),
)


def clear_role_permission_baseline() -> dict[str, int]:
    """清除当前 world 的角色、任命、资格和提案选民事实。

    调用方必须先绑定明确的 simulation world。该操作不会删除 Member，因而可让
    测试账号保留；但会移除它们的所有业务角色、专业资格和相关授权投影来源。
    """

    with transaction.atomic():
        ProposalVote.objects.all().delete()
        ProposalExecution.objects.all().delete()
        Proposal.objects.all().delete()
        ProposalTypeElectorateRule.objects.all().delete()
        ElectorateRuleVersion.objects.all().delete()
        ElectorateRuleTemplate.objects.all().delete()
        qualification_count, _ = MemberProfessionalQualification.objects.all().delete()
        role_event_count, _ = SystemEvent.objects.filter(
            event_type__in=(SystemEvent.EventType.ROLE_ASSIGNED, SystemEvent.EventType.ROLE_REVOKED)
        ).delete()
        assignment_count, _ = RoleAssignment.objects.all().delete()
        binding_count, _ = RolePermission.objects.all().delete()
        Role.objects.update(appointment_electorate_role=None)
        role_count, _ = Role.objects.all().delete()

    return {
        "role_assignments": assignment_count,
        "role_permissions": binding_count,
        "roles": role_count,
        "professional_qualifications": qualification_count,
        "role_events": role_event_count,
    }


def load_role_permission_baseline() -> dict[str, int]:
    """为当前 world 装载新制度最小验证数据，不创建旧角色或个人专属权限。"""

    now = timezone.now()
    ensure_catalog_roles()
    ensure_electorate_rule_baseline()
    ensure_maintainer_role()
    domains = {
        code: ensure_professional_domain(code=code, name=name, description=description)
        for code, name, description in BASELINE_DOMAINS
    }

    contributor = _ensure_baseline_member("role-baseline-contributor", "基线贡献者")
    covenanter = _ensure_baseline_member("role-baseline-covenanter", "基线守约者")
    deliberator = _ensure_baseline_member("role-baseline-deliberator", "基线执衡者")
    maintainer = _ensure_baseline_member("role-baseline-maintainer", "基线典守者")
    qualified_deliberator = _ensure_baseline_member("role-baseline-finance", "基线财务执衡者")

    covenanter_role = ensure_catalog_role(ROLE_COVENANTER)
    create_role_assignment(member=covenanter, role=covenanter_role, start_at=now)
    create_role_assignment(member=deliberator, role=covenanter_role, start_at=now)
    bootstrap_initial_maintainer(maintainer)
    create_role_assignment(member=qualified_deliberator, role=covenanter_role, start_at=now)
    apply_for_deliberator_term(member=deliberator, at_time=now)
    apply_for_deliberator_term(member=qualified_deliberator, at_time=now)
    if not MemberProfessionalQualification.objects.filter(
        member=qualified_deliberator,
        domain=domains["finance"],
        status=MemberProfessionalQualification.Status.ACTIVE,
    ).exists():
        record_external_professional_qualification(
            member=qualified_deliberator,
            domain=domains["finance"],
            confirmed_by=maintainer,
            external_confirmation_source="仿真基线外部确认",
            valid_from=now,
        )

    return {
        "members": 5,
        "contributor_members": 1 if contributor else 0,
        "professional_domains": len(domains),
        "roles": Role.objects.count(),
        "role_assignments": RoleAssignment.objects.count(),
        "professional_qualifications": MemberProfessionalQualification.objects.count(),
    }


def _ensure_baseline_member(member_no: str, display_name: str) -> Member:
    member, _created = Member.objects.get_or_create(
        member_no=member_no,
        defaults={
            "display_name": display_name,
            "status": Member.Status.ACTIVE,
            "batch_id": "role-permission-baseline",
            "joined_simulation_day": 1,
            "credit_floor": -100,
            "profile": {},
            "created_at": timezone.now(),
        },
    )
    return member
