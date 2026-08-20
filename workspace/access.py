"""Shared access gates for member workspace views."""

from __future__ import annotations

from django.http import HttpRequest, HttpResponseForbidden

from core.models import Member
from live_os.access import is_authenticated, member_for_request, page_forbidden

from .context import workspace_access_decision


AUTHORIZATION_UNAVAILABLE_MESSAGE = "权限服务暂时不可用，无法确认当前成员权限。请稍后重试。"
FULL_WORKSPACE_REQUIRED_MESSAGE = "守约者以上才能访问此功能。"


def full_workspace_denial_message(reason: str) -> str:
    if reason == "authorization_unavailable":
        return AUTHORIZATION_UNAVAILABLE_MESSAGE
    return FULL_WORKSPACE_REQUIRED_MESSAGE


def require_full_workspace_member(request: HttpRequest) -> Member | HttpResponseForbidden:
    if not is_authenticated(request):
        return page_forbidden("需要登录。")
    member = member_for_request(request)
    if member is None:
        return page_forbidden("需要绑定成员身份。")
    decision = workspace_access_decision(member)
    if not decision.allowed:
        return page_forbidden(full_workspace_denial_message(decision.reason))
    return member


def require_workspace_member(request: HttpRequest) -> Member | HttpResponseForbidden:
    """要求登录账号绑定有效 Member，但不要求守约者资格。"""

    if not is_authenticated(request):
        return page_forbidden("需要登录。")
    member = member_for_request(request)
    if member is None:
        return page_forbidden("需要绑定成员身份。")
    return member
