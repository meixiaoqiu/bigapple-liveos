from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from core.member_roles import ROLE_BIG_APPLE_MEMBER, ensure_member_role, ensure_role_assignment
from core.models import Member


def grant_governance_admin_role(member: Member):
    from core.governance_setup import ensure_governance_admin_role

    setup = ensure_governance_admin_role()
    return ensure_role_assignment(member, setup["role"])


def create_governance_admin_member(member_no: str, **overrides) -> Member:
    from core.member_roles import ROLE_FORMAL_MEMBER, ROLE_GOVERNANCE_MEMBER

    member = create_member(member_no, role_name=ROLE_GOVERNANCE_MEMBER, **overrides)
    # Governance members are implicitly formal members — full workspace
    # access is gated by ROLE_FORMAL_MEMBER, not by Member.status.
    from core.member_roles import ensure_member_role, ensure_role_assignment
    ensure_role_assignment(member, ensure_member_role(ROLE_FORMAL_MEMBER))
    grant_governance_admin_role(member)
    return member


def create_member(member_no: str, *, role_name: str = ROLE_BIG_APPLE_MEMBER, **overrides) -> Member:
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
    ensure_role_assignment(member, ensure_member_role(ROLE_BIG_APPLE_MEMBER))
    if role_name != ROLE_BIG_APPLE_MEMBER:
        ensure_role_assignment(member, ensure_member_role(role_name))
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
