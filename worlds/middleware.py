from __future__ import annotations

from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpRequest

from .context import bind_default_world_context, bind_world_context
from .state import reset_current_world, set_current_world
from .views import SESSION_WORLD_ID


def world_id_from_path(path_info: str) -> str:
    parts = path_info.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "world":
        return parts[1]
    return ""


class WorldContextMiddleware:
    """Bind world-scoped or fixed-world requests to a database world context."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest):
        world_id = world_id_from_path(request.path_info)
        if not world_id:
            if getattr(request, "world", None) is not None:
                return self.get_response(request)
            if getattr(settings, "SITE_FIXED_WORLD", False):
                world = bind_default_world_context(request)
                token = set_current_world(world)
                try:
                    return self.get_response(request)
                finally:
                    reset_current_world(token)
            return self.get_response(request)

        world = bind_world_context(request, world_id)
        token = set_current_world(world)
        try:
            return self.get_response(request)
        finally:
            reset_current_world(token)


class WorldSessionBoundaryMiddleware:
    """Prevent one authenticated session from silently crossing worlds."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest):
        world = getattr(request, "world", None)
        user = getattr(request, "user", None)
        if world is not None and user is not None and user.is_authenticated:
            session_world_id = request.session.get(SESSION_WORLD_ID)
            if session_world_id and session_world_id != world.world_id:
                logout(request)
        return self.get_response(request)
