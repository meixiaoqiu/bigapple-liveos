from __future__ import annotations

from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from worlds.command_context import command_world_context
from worlds.state import get_current_world


@override_settings(
    SITE_FIXED_WORLD=True,
    SITE_WORLD_ID="simulation0001",
    SITE_WORLD_TYPE="simulation",
    SITE_WORLD_DATABASE_ALIAS="default",
    SITE_WORLD_DATABASE_NAME="dev_big_sim0001",
    WORLD_DATABASE_ROUTING_ENABLED=False,
)
class CommandWorldContextTests(SimpleTestCase):
    def test_fixed_world_context_uses_site_settings_before_registry_lookup(self) -> None:
        with command_world_context("simulation0001", command_name="fixed_command") as world:
            self.assertIsNotNone(world)
            self.assertEqual(world.world_id, "simulation0001")
            self.assertEqual(world.world_type, "simulation")
            self.assertEqual(world.database_alias, "default")
            self.assertEqual(world.database_name, "dev_big_sim0001")
            self.assertEqual(get_current_world(), world)

        self.assertIsNone(get_current_world())

    def test_fixed_world_context_rejects_mismatched_world_id(self) -> None:
        with self.assertRaises(CommandError) as captured:
            with command_world_context("realworld", command_name="fixed_command"):
                pass

        self.assertIn("fixed to world simulation0001", str(captured.exception))
