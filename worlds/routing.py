from __future__ import annotations

from functools import wraps
from typing import Callable, ParamSpec, TypeVar

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

from .context import bind_default_world_context, bind_world_context, world_context_for_request
from .state import reset_current_world, set_current_world


P = ParamSpec("P")
R = TypeVar("R", bound=HttpResponse)


def world_scoped_view(view_func: Callable[P, R]) -> Callable[..., R]:
    @wraps(view_func)
    def wrapper(request: HttpRequest, *args, world_id: str | None = None, **kwargs):
        existing_world = world_context_for_request(request)
        if existing_world is not None and (world_id is None or existing_world.world_id == world_id):
            return view_func(request, *args, **kwargs)

        world = bind_world_context(request, world_id) if world_id else bind_default_world_context(request)
        token = set_current_world(world)
        try:
            return view_func(request, *args, **kwargs)
        finally:
            reset_current_world(token)

    return wrapper


def world_reverse(request: HttpRequest, viewname: str, *args: object) -> str:
    if viewname.endswith("-for-world"):
        viewname = viewname.removesuffix("-for-world")
    return reverse(viewname, args=args)


def world_redirect(request: HttpRequest, viewname: str, *args: object):
    return redirect(world_reverse(request, viewname, *args))
