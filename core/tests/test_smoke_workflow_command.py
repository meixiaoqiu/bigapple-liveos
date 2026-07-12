from __future__ import annotations

from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from core.models import LedgerEntry, Member, Task
from worlds.state import get_current_world


@override_settings(
    WORLD_DATABASE_ROUTING_ENABLED=False,
    DEFAULT_WORLD_DATABASE_ALIAS="default",
    WORLD_DATABASE_ALIASES=("default",),
)
class SmokeWorkflowCommandTests(TestCase):
    def test_smoke_workflow_does_not_seed_realworld_by_default(self) -> None:
        output = StringIO()

        with self.assertRaises(CommandError) as captured:
            call_command(
                "smoke_workflow",
                "--world-id",
                "realworld",
                "--task-id",
                "task-smoke-realworld-no-seed",
                stdout=output,
            )

        self.assertIn("mem-0001", str(captured.exception))
        self.assertEqual(Member.objects.count(), 0)
        self.assertNotIn("Demo seed completed", output.getvalue())

    def test_smoke_workflow_can_explicitly_seed_realworld(self) -> None:
        output = StringIO()

        call_command(
            "smoke_workflow",
            "--world-id",
            "realworld",
            "--seed-demo",
            "--task-id",
            "task-smoke-realworld-seeded",
            stdout=output,
        )

        task = Task.objects.get(task_id="task-smoke-realworld-seeded")

        self.assertEqual(task.status, Task.Status.ACCEPTED)
        self.assertIn("Seeding demo data into realworld", output.getvalue())
        self.assertIn("world=realworld", output.getvalue())

    def test_smoke_workflow_runs_against_simulation_world(self) -> None:
        output = StringIO()

        call_command(
            "smoke_workflow",
            "--world-id",
            "simulation0001",
            "--task-id",
            "task-smoke-command",
            stdout=output,
        )

        task = Task.objects.get(task_id="task-smoke-command")
        worker = Member.objects.get(member_no="mem-0001")
        reviewer = Member.objects.get(member_no="member-admin-0001")

        self.assertEqual(task.status, Task.Status.ACCEPTED)
        self.assertEqual(LedgerEntry.objects.filter(related_task=task, member=worker).count(), 1)
        self.assertIsNotNone(worker.user)
        self.assertIsNotNone(reviewer.user)
        self.assertTrue(get_user_model().objects.filter(username="mem-0001").exists())
        self.assertIn("world=simulation0001", output.getvalue())
        self.assertIsNone(get_current_world())
