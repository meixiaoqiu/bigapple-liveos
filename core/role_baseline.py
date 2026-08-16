"""仿真世界角色与权限基线的重置、装载服务。"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from .deliberator_exam_services import start_deliberator_exam, submit_deliberator_exam
from .governance_setup import ensure_administrator_role
from .member_roles import ROLE_COVENANTER, ensure_catalog_role
from .models import (
    Member,
    MemberProfessionalQualification,
    Role,
    RoleAssignment,
    RolePermission,
    SystemEvent,
    DeliberatorExamAttempt,
    DeliberatorExamPolicy,
    DeliberatorExamQuestion,
)
from .professional_qualification_services import (
    ensure_professional_domain,
    record_external_professional_qualification,
)
from .role_assignment_services import bootstrap_initial_administrator, create_role_assignment
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
        DeliberatorExamAttempt.objects.all().delete()
        DeliberatorExamPolicy.objects.all().delete()
        DeliberatorExamQuestion.objects.all().delete()
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
    ensure_administrator_role()
    domains = {
        code: ensure_professional_domain(code=code, name=name, description=description)
        for code, name, description in BASELINE_DOMAINS
    }

    contributor = _ensure_baseline_member("role-baseline-contributor", "基线贡献者")
    covenanter = _ensure_baseline_member("role-baseline-covenanter", "基线守约者")
    deliberator = _ensure_baseline_member("role-baseline-deliberator", "基线执衡者")
    administrator = _ensure_baseline_member("role-baseline-administrator", "基线管理员")
    qualified_deliberator = _ensure_baseline_member("role-baseline-finance", "基线财务执衡者")

    covenanter_role = ensure_catalog_role(ROLE_COVENANTER)
    create_role_assignment(member=covenanter, role=covenanter_role, start_at=now)
    create_role_assignment(member=deliberator, role=covenanter_role, start_at=now)
    bootstrap_initial_administrator(administrator)
    create_role_assignment(member=qualified_deliberator, role=covenanter_role, start_at=now)
    _ensure_baseline_exam()
    _pass_baseline_exam(deliberator, at_time=now)
    _pass_baseline_exam(qualified_deliberator, at_time=now)
    if not MemberProfessionalQualification.objects.filter(
        member=qualified_deliberator,
        domain=domains["finance"],
        status=MemberProfessionalQualification.Status.ACTIVE,
    ).exists():
        record_external_professional_qualification(
            member=qualified_deliberator,
            domain=domains["finance"],
            confirmed_by=administrator,
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


def _ensure_baseline_exam() -> None:
    DeliberatorExamQuestion.objects.get_or_create(
        question_id="delib-question-governance-baseline", version=1,
        defaults={
            "prompt": "谁可以参与守约者准入申请的表决？",
            "options_json": [
                {"id": "a", "text": "同时具有有效守约者资格和执衡者任期的成员"},
                {"id": "b", "text": "任何已注册账号"},
            ],
            "correct_option_id": "a", "points": 1,
            "status": DeliberatorExamQuestion.Status.PUBLISHED,
            "published_at": timezone.now(),
        },
    )
    DeliberatorExamPolicy.objects.get_or_create(
        version=1,
        defaults={
            "question_count": 1, "passing_percent": 100,
            "status": DeliberatorExamPolicy.Status.ACTIVE,
            "published_at": timezone.now(),
        },
    )


def _pass_baseline_exam(member: Member, *, at_time) -> None:
    attempt = start_deliberator_exam(member=member)
    submit_deliberator_exam(member=member, attempt=attempt, answers={"q1": "a"}, at_time=at_time)
