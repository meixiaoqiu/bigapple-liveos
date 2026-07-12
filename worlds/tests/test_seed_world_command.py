from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from core.models import Member, Task
from worlds.models import WorldRegistry
from worlds.state import get_current_world


@override_settings(
    WORLD_DATABASE_ROUTING_ENABLED=False,
    DEFAULT_WORLD_DATABASE_ALIAS="default",
    WORLD_DATABASE_ALIASES=("default",),
)
class SeedWorldCommandTests(TestCase):
    def test_seed_world_binds_simulation_world_context(self) -> None:
        output = StringIO()

        def assert_seed_demo_context(*args, **kwargs):
            current_world = get_current_world()
            self.assertIsNotNone(current_world)
            self.assertEqual(current_world.world_id, "simulation0001")
            self.assertEqual(args[0], "seed_demo")

        with patch("worlds.management.commands.seed_world.call_command", side_effect=assert_seed_demo_context):
            call_command("seed_world", "simulation0001", stdout=output)

        self.assertIsNone(get_current_world())
        self.assertIn("seeded: world_id=simulation0001", output.getvalue())

    def test_seed_world_rejects_realworld(self) -> None:
        with self.assertRaises(CommandError) as captured:
            call_command("seed_world", "realworld", stdout=StringIO())

        self.assertIn("Refusing to seed non-simulation world", str(captured.exception))

    def test_seed_world_rejects_archived_world(self) -> None:
        WorldRegistry.objects.filter(world_id="simulation0001").update(status=WorldRegistry.Status.ARCHIVED)

        with self.assertRaises(CommandError) as captured:
            call_command("seed_world", "simulation0001", stdout=StringIO())

        self.assertIn("World is not active", str(captured.exception))

    def test_seed_world_demo_template_is_idempotent(self) -> None:
        call_command("seed_world", "simulation0001", stdout=StringIO())
        counts_after_first_run = {
            "members": Member.objects.count(),
            "tasks": Task.objects.count(),
        }

        call_command("seed_world", "simulation0001", stdout=StringIO())

        self.assertEqual(Member.objects.count(), counts_after_first_run["members"])
        self.assertEqual(Task.objects.count(), counts_after_first_run["tasks"])
