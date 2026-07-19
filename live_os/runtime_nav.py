"""Unified runtime nav builder for all user-facing pages.

Produces a ``runtime_nav`` dict consumed by
``templates/partials/runtime_header.html``.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest

from live_os.access import is_authenticated, member_for_request


def build_runtime_nav(request: HttpRequest) -> dict[str, Any]:
    """Return unified nav context for the current request."""
    items: list[dict[str, Any]] = []
    brand_label = "大苹果社区动态"
    home_url = "/"

    if is_authenticated(request):
        member = member_for_request(request)
        items.append({"label": "首页", "url": "/", "method": "get"})
        items.append({"label": "事件流", "url": "/events/", "method": "get"})
        if member is not None:
            items.append({"label": "我的主页", "url": f"/u/{member.member_no}/", "method": "get"})
        items.append({"label": "Workspace", "url": "/workspace/", "method": "get"})
        items.append({"label": "退出", "url": "/logout/", "method": "post"})
    else:
        items.append({"label": "首页", "url": "/", "method": "get"})
        items.append({"label": "事件流", "url": "/events/", "method": "get"})
        items.append({"label": "注册", "url": "/register/", "method": "get"})
        items.append({"label": "登录", "url": "/login/?next=/workspace/", "method": "get"})
        items.append({"label": "Workspace", "url": "/workspace/", "method": "get"})

    return {
        "brand_label": brand_label,
        "home_url": home_url,
        "items": items,
    }
