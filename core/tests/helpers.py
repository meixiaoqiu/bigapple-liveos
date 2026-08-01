from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from core.member_roles import (
    ROLE_COVENANTER,
    ensure_catalog_role,
    ensure_role_assignment,
)
from core.models import Member


def electorate_rule_fields(proposal_type: str, *, template_code: str = "covenanter_matter", parameters=None) -> dict:
    """返回直接创建 Proposal 的规范规则字段。"""

    from core.electorate_rules import current_electorate_rule_version, ensure_electorate_rule_baseline, rule_snapshot_for_proposal

    ensure_electorate_rule_baseline()
    version = current_electorate_rule_version(template_code)
    snapshot = rule_snapshot_for_proposal(
        proposal_type=proposal_type,
        rule_version=version,
        parameters=parameters,
    )
    return {"electorate_rule_version": version, "electorate_rule_snapshot_json": snapshot}


def grant_maintainer_role(member: Member):
    from core.role_assignment_services import create_role_assignment

    setup = _ensure_maintainer_setup()
    return create_role_assignment(
        member=member,
        role=setup["role"],
        source_type="direct",
    )


def _ensure_maintainer_setup():
    from core.governance_setup import ensure_maintainer_role

    return ensure_maintainer_role()


def create_maintainer_member(member_no: str, **overrides) -> Member:
    """创建一名守约者并授予独立典守者职责。"""
    from core.role_assignment_services import bootstrap_initial_maintainer

    member = create_member(member_no, role_name=ROLE_COVENANTER, **overrides)
    bootstrap_initial_maintainer(member)
    return member


def create_member(
    member_no: str,
    *,
    role_name: str = "",
    skip_role_validation: bool = False,
    **overrides,
) -> Member:
    from core.role_assignment_services import create_role_assignment

    defaults = {
        "display_name": str(overrides.get("profile", {}).get("display_name") or member_no),
        "status": Member.Status.ACTIVE,
        "batch_id": "batch-test",
        "joined_simulation_day": 1,
        "credit_floor": -100,
        "profile": {},
        "created_at": timezone.now(),
    }
    defaults.update(overrides)
    member = Member.objects.create(member_no=member_no, **defaults)
    if role_name:
        create_role_assignment(
            member=member,
            role=ensure_catalog_role(role_name),
            source_type="system",
            skip_validation=skip_role_validation,
        )
    return member


def ensure_login_user_for_member(member: Member, *, is_staff: bool = False):
    user_model = get_user_model()
    user, _created = user_model.objects.get_or_create(username=member.member_no)
    user.set_password("test-password")
    user.is_active = True
    user.is_staff = is_staff
    user.save(update_fields=["password", "is_active", "is_staff"])
    if member.user_id != user.pk:
        member.user = user
        member.save(update_fields=["user"])
    return user


def login_as_member(client: Client, member: Member, *, is_staff: bool = False):
    user = ensure_login_user_for_member(member, is_staff=is_staff)
    client.force_login(user)
    return user
