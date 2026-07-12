from __future__ import annotations

from django.conf import settings

from .database_aliases import require_configured_world_database_alias
from .state import get_current_world


class WorldDatabaseRouter:
    """Route control data and world business data to separate databases."""

    control_only_apps = {"worlds", "admin", "sessions"}
    world_apps = {"core"}
    world_context_apps = {"auth", "contenttypes"}
    control_core_models = {"simulationsnapshot", "simulationsnapshotitem", "simulationrundisposition"}
    # Split runtime settings use one world database as default and no routers,
    # so each world database needs a django_session table for login.
    world_migrated_control_apps = {"sessions"}

    def _routing_enabled(self) -> bool:
        return bool(getattr(settings, "WORLD_DATABASE_ROUTING_ENABLED", True))

    def _world_aliases(self) -> set[str]:
        return set(getattr(settings, "WORLD_DATABASE_ALIASES", ()))

    def _configured_world_alias(self, alias: str) -> str:
        return require_configured_world_database_alias(alias)

    def _current_world_alias(self) -> str | None:
        world = get_current_world()
        if world is None:
            return None
        return self._configured_world_alias(world.database_alias)

    def _default_world_alias(self) -> str:
        alias = getattr(settings, "DEFAULT_WORLD_DATABASE_ALIAS", "realworld")
        return self._configured_world_alias(alias)

    def db_for_read(self, model, **hints):
        return self._db_for_model(model)

    def db_for_write(self, model, **hints):
        return self._db_for_model(model)

    def _db_for_model(self, model):
        if not self._routing_enabled():
            return "default"

        app_label = model._meta.app_label
        if app_label == "core" and model._meta.model_name in self.control_core_models:
            return "default"
        if app_label in self.control_only_apps:
            return "default"
        if app_label in self.world_apps:
            return self._current_world_alias() or self._default_world_alias()
        if app_label in self.world_context_apps:
            return self._current_world_alias() or "default"
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if not self._routing_enabled():
            return db == "default"

        world_aliases = self._world_aliases()
        if app_label in self.control_only_apps:
            if app_label in self.world_migrated_control_apps:
                return db == "default" or db in world_aliases
            return db == "default"
        if app_label == "core" and model_name in self.control_core_models:
            return db == "default"
        if app_label in self.world_apps:
            return db in world_aliases
        if app_label in self.world_context_apps:
            return db == "default" or db in world_aliases
        return None
