"""Middleware for runtime user experience concerns."""

from __future__ import annotations

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from .error_handlers import method_not_allowed, page_not_found, permission_denied


class FriendlyErrorPageMiddleware:
    """Render user-facing HTML for page-level 4xx responses.

    API and admin routes keep their original response shape.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        if request.path.startswith(("/api/", "/admin/", "/static/")):
            return response

        if response.status_code == 403:
            return permission_denied(request, Exception("Forbidden"))

        if response.status_code == 404:
            return page_not_found(request, Exception("Not found"))

        if response.status_code != 405:
            return response

        allow_header = response.get("Allow", "")
        rendered = method_not_allowed(request, allowed_methods=allow_header)
        if allow_header:
            rendered["Allow"] = allow_header
        return rendered
