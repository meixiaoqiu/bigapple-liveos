from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.http import Http404
from django.test import TestCase, override_settings

from worlds.context import get_world_registry
from worlds.models import WorldRegistry


@override_settings(
    WORLD_DATABASE_ROUTING_ENABLED=False,
    DEFAULT_WORLD_DATABASE_ALIAS="default",
    WORLD_DATABASE_ALIASES=("default",),
)
class WorldLifecycleCommandTests(TestCase):
    def test_create_world_registers_configured_world_alias(self) -> None:
        output = StringIO()

        call_command(
            "create_world",
            "simulation_test",
            "--name",
            "Simulation Test",
            "--database-alias",
            "default",
            stdout=output,
        )

        world = WorldRegistry.objects.get(world_id="simulation_test")
        self.assertEqual(world.name, "Simulation Test")
        self.assertEqual(world.world_type, WorldRegistry.WorldType.SIMULATION)
        self.assertEqual(world.database_alias, "default")
        self.assertEqual(world.status, WorldRegistry.Status.ACTIVE)
        self.assertIn("created", output.getvalue())

    def test_create_world_rejects_unconfigured_world_alias(self) -> None:
        with self.assertRaises(CommandError) as captured:
            call_command("create_world", "simulation_bad", "--database-alias", "missing")

        self.assertIn("not configured", str(captured.exception))

    def test_archive_world_protects_realworld(self) -> None:
        with self.assertRaises(CommandError) as captured:
            call_command("archive_world", "realworld")

        self.assertIn("Refusing to archive real world", str(captured.exception))

    def test_delete_world_protects_realworld(self) -> None:
        with self.assertRaises(CommandError) as captured:
            call_command("delete_world", "realworld")

        self.assertIn("Refusing to delete real world", str(captured.exception))

    def test_archive_then_delete_simulation_world(self) -> None:
        archive_output = StringIO()
        delete_output = StringIO()

        call_command("archive_world", "simulation0001", stdout=archive_output)
        archived = WorldRegistry.objects.get(world_id="simulation0001")
        self.assertEqual(archived.status, WorldRegistry.Status.ARCHIVED)
        self.assertIsNotNone(archived.archived_at)
        self.assertIn("archived", archive_output.getvalue())

        call_command("delete_world", "simulation0001", stdout=delete_output)
        deleted = WorldRegistry.objects.get(world_id="simulation0001")
        self.assertEqual(deleted.status, WorldRegistry.Status.DELETED)
        self.assertIn("deleted", delete_output.getvalue())

    def test_delete_world_requires_archive_first(self) -> None:
        with self.assertRaises(CommandError) as captured:
            call_command("delete_world", "simulation0001")

        self.assertIn("must be archived before deletion", str(captured.exception))

    def test_archived_world_is_not_routable(self) -> None:
        call_command("archive_world", "simulation0001", stdout=StringIO())

        with self.assertRaises(Http404):
            get_world_registry("simulation0001")

    def test_migrate_world_delegates_to_django_migrate_for_active_world_alias(self) -> None:
        WorldRegistry.objects.create(
            world_id="simulation_migrate",
            name="Simulation Migrate",
            world_type=WorldRegistry.WorldType.SIMULATION,
            database_alias="default",
            database_name=":memory:",
            status=WorldRegistry.Status.ACTIVE,
        )
        output = StringIO()

        with patch("worlds.management.commands.migrate_world.call_command") as migrate_call:
            call_command("migrate_world", "simulation_migrate", "--noinput", stdout=output)

        migrate_call.assert_called_once()
        _command_name, = migrate_call.call_args.args
        self.assertEqual(_command_name, "migrate")
        self.assertEqual(migrate_call.call_args.kwargs["database"], "default")
        self.assertEqual(migrate_call.call_args.kwargs["interactive"], False)
        self.assertIn("migrated", output.getvalue())
