"""User-facing error pages for fixed-world runtime sites."""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


def render_runtime_error(
    request: HttpRequest,
    *,
    status_code: int,
    title: str,
    message: str,
    detail: str = "",
) -> HttpResponse:
    context: dict[str, Any] = {
        "status_code": status_code,
        "title": title,
        "message": message,
        "detail": detail,
        "home_url": "/",
        "workspace_url": "/workspace/",
        "login_url": "/login/?next=/workspace/",
        "register_url": "/register/",
    }
    return render(request, "errors/runtime_error.html", context, status=status_code)


def bad_request(request: HttpRequest, exception: Exception) -> HttpResponse:
    return render_runtime_error(
        request,
        status_code=400,
        title="请求无法处理",
        message="这个请求格式不正确，系统无法继续处理。",
        detail="请返回上一页重新操作，或从首页重新进入。",
    )


def permission_denied(request: HttpRequest, exception: Exception) -> HttpResponse:
    return render_runtime_error(
        request,
        status_code=403,
        title="无权访问",
        message="当前账号没有访问这个页面或执行这个操作的权限。",
        detail="如果你认为这是误判，请通过治理流程或维护入口处理权限问题。",
    )


def page_not_found(request: HttpRequest, exception: Exception) -> HttpResponse:
    return render_runtime_error(
        request,
        status_code=404,
        title="页面不存在",
        message="你访问的页面不存在，可能是链接已变更，或对应事项已经不在当前世界中。",
        detail="可以返回首页查看当前公开事件流，或进入 Workspace 查看自己的状态。",
    )


def server_error(request: HttpRequest) -> HttpResponse:
    return render_runtime_error(
        request,
        status_code=500,
        title="系统暂时无法完成请求",
        message="系统处理请求时出现异常。",
        detail="请稍后重试；如果问题持续出现，请记录当前页面地址并联系维护者。",
    )


def method_not_allowed(request: HttpRequest, allowed_methods: str = "") -> HttpResponse:
    detail = "这个操作不能通过直接访问链接完成。"
    if request.path == "/logout/":
        detail = "退出登录需要从页面上的“退出”按钮提交，不能通过地址栏直接访问。"
    if allowed_methods:
        detail = f"{detail} 允许的请求方式：{allowed_methods}。"
    return render_runtime_error(
        request,
        status_code=405,
        title="请求方式不正确",
        message="当前页面收到了不支持的请求方式。",
        detail=detail,
    )
