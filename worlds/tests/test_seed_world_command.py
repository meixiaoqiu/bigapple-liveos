from __future__ import annotations

import os
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from core.access import user_has_governance_permission
from core.governance_setup import GOVERNANCE_VIEW_ADMIN_PERMISSION
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

        with patch.dict(os.environ, {"BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_ENABLED": "false"}):
            with patch("worlds.management.commands.seed_world.call_command", side_effect=assert_seed_demo_context):
                call_command("seed_world", "simulation0001", stdout=output)

        self.assertIsNone(get_current_world())
        self.assertIn("seeded: world_id=simulation0001", output.getvalue())

    def test_seed_world_ensures_configured_simulation_admin(self) -> None:
        output = StringIO()
        env = {
            "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_ENABLED": "true",
            "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_USERNAME": "sim-admin",
            "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_PASSWORD": "test-password",
            "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_MEMBER_NO": "sim-admin",
            "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_DISPLAY_NAME": "Simulation admin",
        }

        with patch.dict(os.environ, env):
            call_command("seed_world", "simulation0001", stdout=output)

        user = get_user_model().objects.get(username="sim-admin")
        member = Member.objects.get(member_no="sim-admin")

        self.assertTrue(user.check_password("test-password"))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(member.user, user)
        self.assertTrue(user_has_governance_permission(user, GOVERNANCE_VIEW_ADMIN_PERMISSION))
        self.assertIn("world_admin world_id=simulation0001, username=sim-admin", output.getvalue())

    def test_seed_world_skips_simulation_admin_when_disabled(self) -> None:
        env = {
            "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_ENABLED": "false",
            "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_USERNAME": "sim-admin",
            "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_PASSWORD": "test-password",
        }

        with patch.dict(os.environ, env):
            call_command("seed_world", "simulation0001", stdout=StringIO())

        self.assertFalse(get_user_model().objects.filter(username="sim-admin").exists())

    def test_seed_world_rejects_simulation_admin_without_password(self) -> None:
        env = {
            "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_ENABLED": "true",
            "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_USERNAME": "sim-admin",
            "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_PASSWORD": "",
        }

        with patch.dict(os.environ, env):
            with self.assertRaises(CommandError) as captured:
                call_command("seed_world", "simulation0001", stdout=StringIO())

        self.assertIn("must be set when", str(captured.exception))
        self.assertFalse(get_user_model().objects.filter(username="sim-admin").exists())

    def test_seed_world_rejects_simulation_admin_without_username(self) -> None:
        env = {
            "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_ENABLED": "true",
            "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_USERNAME": "",
            "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_PASSWORD": "test-password",
        }

        with patch.dict(os.environ, env):
            with self.assertRaises(CommandError) as captured:
                call_command("seed_world", "simulation0001", stdout=StringIO())

        self.assertIn("must be set when", str(captured.exception))
        self.assertFalse(get_user_model().objects.filter(username="sim-admin").exists())

    def test_seed_world_rejects_placeholder_simulation_admin_password(self) -> None:
        env = {
            "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_ENABLED": "true",
            "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_USERNAME": "sim-admin",
            "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_PASSWORD": "CHANGE_ME",
        }

        with patch.dict(os.environ, env):
            with self.assertRaises(CommandError) as captured:
                call_command("seed_world", "simulation0001", stdout=StringIO())

        self.assertIn("must be changed before bootstrap admin creation", str(captured.exception))
        self.assertFalse(get_user_model().objects.filter(username="sim-admin").exists())

    def test_seed_world_simulation_admin_is_idempotent(self) -> None:
        env = {
            "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_ENABLED": "true",
            "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_USERNAME": "sim-admin",
            "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_PASSWORD": "test-password",
            "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_MEMBER_NO": "sim-admin",
            "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_DISPLAY_NAME": "Simulation admin",
        }

        with patch.dict(os.environ, env):
            call_command("seed_world", "simulation0001", stdout=StringIO())
            call_command("seed_world", "simulation0001", stdout=StringIO())

        self.assertEqual(get_user_model().objects.filter(username="sim-admin").count(), 1)
        self.assertEqual(Member.objects.filter(member_no="sim-admin").count(), 1)

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
