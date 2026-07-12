"""Theme switching support for observer pages."""

from __future__ import annotations

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .theme import set_active_theme, set_request_theme_override
from worlds.routing import world_reverse


def apply_theme_query_override(request: HttpRequest) -> None:
    """Allow a safe, request-only theme query override for manual verification."""

    requested_theme = str(request.GET.get("theme") or "").strip()
    if requested_theme:
        set_request_theme_override(request, requested_theme)


@require_POST
def switch_theme(request: HttpRequest, **_kwargs):
    theme_name = request.POST.get("theme", "")
    if set_active_theme(request, theme_name):
        messages.success(request, f"已切换主题：{theme_name}")
    else:
        messages.error(request, "请求的主题不存在。")

    fallback_url = world_reverse(request, "observer-page")
    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or fallback_url
    if not url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        next_url = fallback_url

    if getattr(request, "htmx", False):
        response = HttpResponse(status=204)
        response["HX-Redirect"] = next_url
        return response
    return redirect(next_url)
