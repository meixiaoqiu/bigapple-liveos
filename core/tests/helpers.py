from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from core.member_roles import (
    ROLE_BIG_APPLE_MEMBER,
    ROLE_FORMAL_MEMBER,
    ROLE_GOVERNANCE_MEMBER,
    ensure_member_role,
    ensure_role_assignment,
)
from core.models import Member


def grant_governance_admin_role(member: Member):
    from core.role_assignment_services import create_role_assignment

    setup = _ensure_gov_admin_setup()
    return create_role_assignment(
        member=member,
        role=setup["role"],
        source_type="direct",
    )


def _ensure_gov_admin_setup():
    from core.governance_setup import ensure_governance_admin_role

    return ensure_governance_admin_role()


def create_governance_admin_member(member_no: str, **overrides) -> Member:
    """Create a member with ROLE_BIG_APPLE_MEMBER → ROLE_FORMAL_MEMBER → ROLE_GOVERNANCE_MEMBER → governance-admin."""
    from core.role_assignment_services import bootstrap_first_governance_member

    member = create_member(member_no, role_name=ROLE_FORMAL_MEMBER, skip_role_validation=True, **overrides)
    # Use bootstrap to grant the full chain (already has BIG_APPLE + FORMAL from create_member)
    bootstrap_first_governance_member(member)
    return member


def create_member(
    member_no: str,
    *,
    role_name: str = ROLE_BIG_APPLE_MEMBER,
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
    create_role_assignment(
        member=member,
        role=ensure_member_role(ROLE_BIG_APPLE_MEMBER),
        source_type="system",
        skip_validation=skip_role_validation,
    )
    if role_name and role_name != ROLE_BIG_APPLE_MEMBER:
        create_role_assignment(
            member=member,
            role=ensure_member_role(role_name),
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
