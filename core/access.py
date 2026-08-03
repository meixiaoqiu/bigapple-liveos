"""基于具体业务能力的访问控制辅助函数。"""

from __future__ import annotations

from .governance_setup import MAINTENANCE_VIEW_ADMIN_PERMISSION
from .finance_setup import (
    FINANCE_PAY_PERMISSION,
    FINANCE_PUBLISH_PUBLIC_ATTACHMENTS_PERMISSION,
    FINANCE_REVIEW_PERMISSION,
)
from .models import Member, Resource
from .authorization_services import AuthorizationService


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


def user_has_permission(
    user,
    permission_code: str,
    resource: Resource | None = None,
    at_time=None,
) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    member = member_for_user(user)
    if member is not None and AuthorizationService().member_has_permission(
        member,
        permission_code,
        resource=resource,
        at_time=at_time,
    ):
        return True
    return False


def member_can_maintain(
    member: Member,
    permission_code: str = MAINTENANCE_VIEW_ADMIN_PERMISSION,
) -> bool:
    """判断成员是否具备一项明确的维护能力。"""

    return AuthorizationService().member_can_maintain(
        member=member,
        permission_code=permission_code,
    )


def user_can_maintain(
    user,
    permission_code: str = MAINTENANCE_VIEW_ADMIN_PERMISSION,
) -> bool:
    """判断已登录用户绑定的成员是否具备一项明确的维护能力。"""

    if not user or not getattr(user, "is_authenticated", False):
        return False
    member = member_for_user(user)
    return bool(member and member_can_maintain(member, permission_code))


def is_finance_reviewer(member: Member) -> bool:
    """Return True when *member* can review expense claims."""
    return AuthorizationService().member_has_permission(member, FINANCE_REVIEW_PERMISSION)


def is_finance_payer(member: Member) -> bool:
    """Return True when *member* can record finance payments."""
    return AuthorizationService().member_has_permission(member, FINANCE_PAY_PERMISSION)


def is_finance_public_attachment_publisher(member: Member) -> bool:
    """Return True when *member* can publish public finance derivatives."""
    return AuthorizationService().member_has_permission(
        member, FINANCE_PUBLISH_PUBLIC_ATTACHMENTS_PERMISSION,
    )
