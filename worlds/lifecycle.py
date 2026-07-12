from __future__ import annotations

import re

from django.conf import settings
from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone

from .context import DEFAULT_REALWORLD_ID
from .models import WorldRegistry


WORLD_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def validate_world_id(world_id: str) -> str:
    checked = str(world_id or "").strip()
    if not checked:
        raise CommandError("world_id cannot be empty.")
    if not WORLD_ID_PATTERN.fullmatch(checked):
        raise CommandError("world_id must use lowercase letters, numbers, underscore or hyphen.")
    return checked


def configured_world_aliases() -> set[str]:
    return set(getattr(settings, "WORLD_DATABASE_ALIASES", ()))


def validate_world_database_alias(alias: str) -> str:
    checked = str(alias or "").strip()
    if not checked:
        raise CommandError("database alias cannot be empty.")
    if checked not in settings.DATABASES:
        raise CommandError(f"database alias is not configured in settings.DATABASES: {checked}")
    if checked not in configured_world_aliases():
        raise CommandError(f"database alias is not listed in WORLD_DATABASE_ALIASES: {checked}")
    return checked


def database_name_for_alias(alias: str) -> str:
    return str(settings.DATABASES.get(alias, {}).get("NAME") or "")


def get_world_or_error(world_id: str) -> WorldRegistry:
    checked = validate_world_id(world_id)
    try:
        return WorldRegistry.objects.using("default").get(world_id=checked)
    except WorldRegistry.DoesNotExist as exc:
        raise CommandError(f"World not found: {checked}") from exc


def ensure_not_realworld(world: WorldRegistry, action: str) -> None:
    if world.world_id == DEFAULT_REALWORLD_ID or world.world_type == WorldRegistry.WorldType.REAL:
        raise CommandError(f"Refusing to {action} real world: {world.world_id}")


def create_world_registry(
    *,
    world_id: str,
    name: str,
    world_type: str,
    database_alias: str,
    database_name: str = "",
) -> tuple[WorldRegistry, bool]:
    checked_world_id = validate_world_id(world_id)
    checked_alias = validate_world_database_alias(database_alias)
    checked_name = str(name or checked_world_id).strip() or checked_world_id
    checked_database_name = str(database_name or database_name_for_alias(checked_alias)).strip()

    valid_types = {value for value, _label in WorldRegistry.WorldType.choices}
    if world_type not in valid_types:
        raise CommandError(f"Invalid world type: {world_type}")

    existing_alias_owner = (
        WorldRegistry.objects.using("default")
        .filter(database_alias=checked_alias)
        .exclude(world_id=checked_world_id)
        .exclude(status=WorldRegistry.Status.DELETED)
        .first()
    )
    if existing_alias_owner is not None:
        raise CommandError(
            f"database alias {checked_alias} is already used by world {existing_alias_owner.world_id}."
        )

    with transaction.atomic(using="default"):
        world, created = WorldRegistry.objects.using("default").get_or_create(
            world_id=checked_world_id,
            defaults={
                "name": checked_name,
                "world_type": world_type,
                "database_alias": checked_alias,
                "database_name": checked_database_name,
                "status": WorldRegistry.Status.ACTIVE,
            },
        )
        if not created:
            changed_fields = []
            desired = {
                "name": checked_name,
                "world_type": world_type,
                "database_alias": checked_alias,
                "database_name": checked_database_name,
                "status": WorldRegistry.Status.ACTIVE,
                "archived_at": None,
            }
            for field, value in desired.items():
                if getattr(world, field) != value:
                    setattr(world, field, value)
                    changed_fields.append(field)
            if changed_fields:
                changed_fields.append("updated_at")
                world.save(using="default", update_fields=changed_fields)
    return world, created


def archive_world_registry(world_id: str) -> tuple[WorldRegistry, bool]:
    with transaction.atomic(using="default"):
        checked_world_id = validate_world_id(world_id)
        try:
            world = WorldRegistry.objects.using("default").select_for_update().get(world_id=checked_world_id)
        except WorldRegistry.DoesNotExist as exc:
            raise CommandError(f"World not found: {checked_world_id}") from exc
        ensure_not_realworld(world, "archive")
        if world.status == WorldRegistry.Status.DELETED:
            raise CommandError(f"Cannot archive deleted world: {world.world_id}")
        if world.status == WorldRegistry.Status.ARCHIVED:
            return world, False
        world.status = WorldRegistry.Status.ARCHIVED
        world.archived_at = timezone.now()
        world.save(using="default", update_fields=["status", "archived_at", "updated_at"])
        return world, True


def delete_world_registry(world_id: str) -> tuple[WorldRegistry, bool]:
    with transaction.atomic(using="default"):
        checked_world_id = validate_world_id(world_id)
        try:
            world = WorldRegistry.objects.using("default").select_for_update().get(world_id=checked_world_id)
        except WorldRegistry.DoesNotExist as exc:
            raise CommandError(f"World not found: {checked_world_id}") from exc
        ensure_not_realworld(world, "delete")
        if world.status == WorldRegistry.Status.DELETED:
            return world, False
        if world.status != WorldRegistry.Status.ARCHIVED:
            raise CommandError(
                f"World must be archived before deletion: {world.world_id}. Run archive_world first."
            )
        world.status = WorldRegistry.Status.DELETED
        if world.archived_at is None:
            world.archived_at = timezone.now()
        world.save(using="default", update_fields=["status", "archived_at", "updated_at"])
        return world, True
