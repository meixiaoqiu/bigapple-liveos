"""Access-control helpers for core governance principals."""

from __future__ import annotations

from .governance_setup import GOVERNANCE_VIEW_ADMIN_PERMISSION
from .finance_setup import FINANCE_PAY_PERMISSION, FINANCE_REVIEW_PERMISSION
from .models import Member, Resource
from .permission_services import member_has_permission


def member_for_user(user) -> Member | None:
    if not user or not getattr(user, "is_authenticated", False):
        return None
    linked_member = Member.objects.filter(user=user).first()
    if linked_member is not None:
        return linked_member
    username = str(user.get_username() or "").strip()
    if not username:
        return None
    return Member.objects.filter(member_no=username).first()


def is_staff_principal(user) -> bool:
    return bool(user and getattr(user, "is_authenticated", False) and (user.is_staff or user.is_superuser))


def is_superuser_principal(user) -> bool:
    return bool(user and getattr(user, "is_authenticated", False) and user.is_superuser)


def user_has_governance_permission(
    user,
    permission_code: str,
    resource: Resource | None = None,
    at_time=None,
) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    # Superuser remains a technical root/rescue account. Ordinary is_staff only
    # opens Django Admin; business governance permissions still come from Member
    # role assignments and role permissions.
    if is_superuser_principal(user):
        return True
    member = member_for_user(user)
    if member is not None and member_has_permission(member, permission_code, resource=resource, at_time=at_time):
        return True
    return False


def is_governance_principal(
    user_or_member,
    permission_code: str = GOVERNANCE_VIEW_ADMIN_PERMISSION,
) -> bool:
    if isinstance(user_or_member, Member):
        return member_has_permission(user_or_member, permission_code)
    return user_has_governance_permission(user_or_member, permission_code)


def is_finance_reviewer(member: Member) -> bool:
    """Return True when *member* can review expense claims."""
    return member_has_permission(member, FINANCE_REVIEW_PERMISSION)


def is_finance_payer(member: Member) -> bool:
    """Return True when *member* can record finance payments."""
    return member_has_permission(member, FINANCE_PAY_PERMISSION)
