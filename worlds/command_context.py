from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from django.conf import settings
from django.core.management.base import CommandError

from .context import WorldContext, context_from_registry
from .lifecycle import get_world_or_error
from .models import WorldRegistry
from .state import get_current_world, reset_current_world, set_current_world


@contextmanager
def command_world_context(world_id: str | None, *, command_name: str) -> Iterator[WorldContext | None]:
    """Bind a management command to an explicit world when routing is active."""

    requested_world_id = str(world_id or "").strip()
    current_world = get_current_world()
    token = None

    if requested_world_id:
        world = get_world_or_error(requested_world_id)
        if world.status != WorldRegistry.Status.ACTIVE:
            raise CommandError(f"World is not active: {world.world_id} ({world.status})")
        world_context = context_from_registry(world)
        if current_world is not None and current_world.world_id != world_context.world_id:
            raise CommandError(
                f"{command_name} is already bound to world {current_world.world_id}; "
                f"cannot also bind {world_context.world_id}."
            )
        if current_world is None:
            token = set_current_world(world_context)
        try:
            yield current_world or world_context
        finally:
            if token is not None:
                reset_current_world(token)
        return

    if current_world is not None:
        yield current_world
        return

    if getattr(settings, "WORLD_DATABASE_ROUTING_ENABLED", True):
        raise CommandError(f"{command_name} requires --world-id when no world context is active.")

    yield None


def command_world_label(world: WorldContext | None) -> str:
    return world.world_id if world is not None else "default"
