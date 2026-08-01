"""HTTP access-control helpers for Live OS views and JSON APIs."""

from __future__ import annotations

from functools import wraps
from typing import Callable, ParamSpec, TypeVar

from django.contrib.auth.views import redirect_to_login
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, JsonResponse

from core.access import member_for_user, user_can_maintain
from core.service_utils import actor_ref


P = ParamSpec("P")
R = TypeVar("R", bound=HttpResponse)


def request_user(request: HttpRequest):
    return getattr(request, "user", None)


def is_authenticated(request: HttpRequest) -> bool:
    user = request_user(request)
    return bool(user and getattr(user, "is_authenticated", False))


def member_for_request(request: HttpRequest):
    return member_for_user(request_user(request))


def can_access_member(request: HttpRequest, member_no: str) -> bool:
    user = request_user(request)
    if user_can_maintain(user):
        return True
    member = member_for_request(request)
    return bool(member and member.member_no == member_no)


def actor_ref_for_request(request: HttpRequest) -> dict[str, str]:
    member = member_for_request(request)
    if member is not None:
        return actor_ref(member)

    user = request_user(request)
    username = str(user.get_username() or "authenticated-user") if user else "authenticated-user"
    display_name = str(user.get_full_name() or username) if user else username
    return {
        "actor_id": username,
        "actor_type": "human_member",
        "display_name": display_name,
    }


def json_auth_required() -> JsonResponse:
    return JsonResponse({"code": "authentication_required", "message": "Authentication is required."}, status=401)


def json_forbidden(message: str = "Permission denied.") -> JsonResponse:
    return JsonResponse({"code": "permission_denied", "message": message}, status=403)


def page_forbidden(message: str = "需要登录并具备相应权限。") -> HttpResponseForbidden:
    response = HttpResponseForbidden(message)
    response.big_apple_error_message = message
    return response


def world_login_url_for_request(request: HttpRequest) -> str:
    return "/login/"


def require_maintainer_page(view_func: Callable[P, R]) -> Callable[P, R | HttpResponse]:
    @wraps(view_func)
    def wrapper(request: HttpRequest, *args: P.args, **kwargs: P.kwargs):
        if not is_authenticated(request):
            return redirect_to_login(request.get_full_path(), login_url=world_login_url_for_request(request))
        if not user_can_maintain(request_user(request)):
            return page_forbidden("需要典守者权限。")
        return view_func(request, *args, **kwargs)

    return wrapper


def require_maintainer_json(request: HttpRequest) -> JsonResponse | None:
    if not is_authenticated(request):
        return json_auth_required()
    if not user_can_maintain(request_user(request)):
        return json_forbidden("Governance permission is required.")
    return None


def require_member_json(request: HttpRequest, member_no: str) -> JsonResponse | None:
    if not is_authenticated(request):
        return json_auth_required()
    if not can_access_member(request, member_no):
        return json_forbidden("Member access is required.")
    return None


def _full_workspace_member_denial(member) -> JsonResponse | None:
    from core.authorization_services import AuthorizationService

    decision = AuthorizationService().full_workspace_access_decision(member)
    if decision.allowed:
        return None
    if decision.reason == "authorization_unavailable":
        return json_forbidden("Authorization service is unavailable.")
    return json_forbidden("Full workspace access is required.")


def require_current_full_workspace_member_json(request: HttpRequest):
    if not is_authenticated(request):
        return json_auth_required()
    member = member_for_request(request)
    if member is None:
        return json_forbidden("Member access is required.")
    denied = _full_workspace_member_denial(member)
    if denied:
        return denied
    return member


def require_full_workspace_member_json(request: HttpRequest, member_no: str) -> JsonResponse | None:
    denied = require_member_json(request, member_no)
    if denied:
        return denied

    from core.models import Member

    member = Member.objects.filter(member_no=member_no).first()
    if member is None:
        return json_forbidden("Member access is required.")

    return _full_workspace_member_denial(member)


def require_member_page(request: HttpRequest, member_no: str) -> HttpResponseForbidden | None:
    if not is_authenticated(request) or not can_access_member(request, member_no):
        return page_forbidden("需要当前成员或典守者权限。")
    return None
