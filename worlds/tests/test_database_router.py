from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from core.models import Member, SimulationRunDisposition, SimulationSnapshot, SimulationSnapshotItem
from worlds.context import WorldContext
from worlds.db import WorldDatabaseRouter
from worlds.models import WorldRegistry
from worlds.state import reset_current_world, set_current_world


@override_settings(
    WORLD_DATABASE_ROUTING_ENABLED=True,
    DEFAULT_WORLD_DATABASE_ALIAS="realworld",
    WORLD_DATABASE_ALIASES=("realworld", "simulation0001"),
)
class WorldDatabaseRouterTests(SimpleTestCase):
    def setUp(self) -> None:
        self.router = WorldDatabaseRouter()

    def test_control_models_route_to_default(self) -> None:
        self.assertEqual(self.router.db_for_read(WorldRegistry), "default")
        self.assertEqual(self.router.db_for_write(WorldRegistry), "default")

    def test_core_models_default_to_realworld_without_request_context(self) -> None:
        self.assertEqual(self.router.db_for_read(Member), "realworld")

    def test_core_archive_models_route_to_control_database(self) -> None:
        for model in (SimulationSnapshot, SimulationSnapshotItem, SimulationRunDisposition):
            with self.subTest(model=model.__name__):
                self.assertEqual(self.router.db_for_read(model), "default")
                self.assertEqual(self.router.db_for_write(model), "default")

    def test_core_and_auth_models_use_current_world_context(self) -> None:
        token = set_current_world(
            WorldContext(
                world_id="simulation0001",
                world_type=WorldRegistry.WorldType.SIMULATION,
                database_alias="simulation0001",
                database_name="dev_big_sim0001",
            )
        )
        try:
            self.assertEqual(self.router.db_for_read(Member), "simulation0001")
            self.assertEqual(self.router.db_for_read(get_user_model()), "simulation0001")
        finally:
            reset_current_world(token)

    def test_auth_models_use_control_database_without_world_context(self) -> None:
        self.assertEqual(self.router.db_for_read(get_user_model()), "default")

    def test_sessions_read_write_route_to_default(self) -> None:
        self.assertEqual(self.router.db_for_read(Session), "default")
        self.assertEqual(self.router.db_for_write(Session), "default")

    def test_missing_current_world_alias_fails_closed(self) -> None:
        token = set_current_world(
            WorldContext(
                world_id="simulation-missing",
                world_type=WorldRegistry.WorldType.SIMULATION,
                database_alias="missing",
                database_name="dev_big_missing",
            )
        )
        try:
            with self.assertRaisesMessage(ImproperlyConfigured, "not configured"):
                self.router.db_for_read(Member)
        finally:
            reset_current_world(token)

    def test_default_alias_is_not_valid_for_world_business_data(self) -> None:
        token = set_current_world(
            WorldContext(
                world_id="bad-world",
                world_type=WorldRegistry.WorldType.SIMULATION,
                database_alias="default",
                database_name="dev_big_control",
            )
        )
        try:
            with self.assertRaisesMessage(ImproperlyConfigured, "control database alias"):
                self.router.db_for_write(Member)
        finally:
            reset_current_world(token)

    def test_migration_boundaries(self) -> None:
        self.assertTrue(self.router.allow_migrate("default", "worlds"))
        self.assertFalse(self.router.allow_migrate("realworld", "worlds"))
        self.assertFalse(self.router.allow_migrate("default", "core"))
        self.assertTrue(self.router.allow_migrate("default", "core", model_name="simulationrundisposition"))
        self.assertFalse(self.router.allow_migrate("realworld", "core", model_name="simulationrundisposition"))
        self.assertTrue(self.router.allow_migrate("realworld", "core"))
        self.assertTrue(self.router.allow_migrate("simulation0001", "core"))
        self.assertTrue(self.router.allow_migrate("default", "auth"))
        self.assertTrue(self.router.allow_migrate("realworld", "auth"))
        self.assertTrue(self.router.allow_migrate("default", "sessions"))
        self.assertTrue(self.router.allow_migrate("realworld", "sessions"))
        self.assertTrue(self.router.allow_migrate("simulation0001", "sessions"))
