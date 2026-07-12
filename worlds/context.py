from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.http import Http404, HttpRequest

from .database_aliases import require_configured_world_database_alias
from .models import WorldRegistry


DEFAULT_REALWORLD_ID = "realworld"


@dataclass(frozen=True)
class WorldContext:
    world_id: str
    world_type: str
    database_alias: str
    database_name: str

    @property
    def is_realworld(self) -> bool:
        return self.world_type == WorldRegistry.WorldType.REAL

    @property
    def member_root(self) -> str:
        return "/workspace/"


def get_world_registry(world_id: str) -> WorldRegistry:
    try:
        return WorldRegistry.objects.get(world_id=world_id, status=WorldRegistry.Status.ACTIVE)
    except WorldRegistry.DoesNotExist as exc:
        raise Http404(f"World not found: {world_id}") from exc


def context_from_registry(world: WorldRegistry) -> WorldContext:
    database_alias = require_configured_world_database_alias(world.database_alias)
    return WorldContext(
        world_id=world.world_id,
        world_type=world.world_type,
        database_alias=database_alias,
        database_name=world.database_name,
    )


def fixed_world_context_from_settings() -> WorldContext | None:
    world_id = str(getattr(settings, "SITE_WORLD_ID", "") or "").strip()
    if not world_id:
        return None
    database_alias = str(getattr(settings, "SITE_WORLD_DATABASE_ALIAS", "default") or "default").strip()
    database_name = str(getattr(settings, "SITE_WORLD_DATABASE_NAME", "") or "").strip()
    if not database_name:
        database_name = str(settings.DATABASES.get(database_alias, {}).get("NAME", ""))
    return WorldContext(
        world_id=world_id,
        world_type=str(getattr(settings, "SITE_WORLD_TYPE", WorldRegistry.WorldType.REAL)),
        database_alias=database_alias,
        database_name=database_name,
    )


def bind_world_context(request: HttpRequest, world_id: str) -> WorldContext:
    fixed_context = fixed_world_context_from_settings()
    if fixed_context is not None and fixed_context.world_id == world_id:
        context = fixed_context
    else:
        context = context_from_registry(get_world_registry(world_id))
    request.world = context
    request.world_id = context.world_id
    request.world_db_alias = context.database_alias
    return context


def bind_default_world_context(request: HttpRequest) -> WorldContext:
    fixed_context = fixed_world_context_from_settings()
    if fixed_context is not None:
        context = fixed_context
    else:
        context = context_from_registry(get_world_registry(DEFAULT_REALWORLD_ID))
    request.world = context
    request.world_id = context.world_id
    request.world_db_alias = context.database_alias
    return context


def world_context_for_request(request: HttpRequest) -> WorldContext | None:
    world = getattr(request, "world", None)
    return world if isinstance(world, WorldContext) else None
