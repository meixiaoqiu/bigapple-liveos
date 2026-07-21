from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from core.models import (
    CapacityAssessment,
    Dispute,
    Event,
    LedgerEntry,
    PlanCapacityImpact,
    PlanDependency,
    PlanNode,
    PlanRequirement,
    PlanRevision,
    ProjectPlan,
    Resource,
    SystemEvent,
    Task,
)
from worlds.state import get_current_world


class SeedDemoTests(TestCase):
    """验证演示数据覆盖关键后台场景，并且可以幂等执行。"""

    def test_seed_demo_creates_rich_admin_scenarios(self) -> None:
        call_command("seed_demo", stdout=StringIO())

        self.assertTrue(Task.objects.filter(status=Task.Status.ACCEPTED).exists())
        self.assertTrue(Task.objects.filter(status=Task.Status.PENDING_REVIEW).exists())
        self.assertTrue(Task.objects.filter(status=Task.Status.REJECTED).exists())
        self.assertTrue(Task.objects.filter(status=Task.Status.DISPUTED).exists())
        self.assertTrue(Task.objects.filter(status=Task.Status.CLOSED).exists())
        self.assertTrue(Task.objects.filter(status=Task.Status.REVERSED).exists())
        closed_task = Task.objects.get(task_id="task-0007")
        self.assertIn("close_reason", closed_task.metadata)

        low_resource = Resource.objects.get(resource_id="res-medicine")
        self.assertLessEqual(low_resource.current_stock, low_resource.warning_threshold)
        self.assertEqual(Resource.objects.get(resource_id="res-cash").resource_type, Resource.ResourceType.CASH)

        self.assertTrue(Dispute.objects.filter(status=Dispute.Status.SUBMITTED).exists())
        self.assertTrue(Dispute.objects.filter(status=Dispute.Status.IN_REVIEW).exists())
        self.assertTrue(Dispute.objects.filter(status=Dispute.Status.RESOLVED).exists())

        reversal = LedgerEntry.objects.get(ledger_entry_id="ledger-0003")
        self.assertEqual(reversal.entry_type, LedgerEntry.EntryType.REVERSAL)
        self.assertEqual(reversal.amount, -18)
        self.assertEqual(reversal.reverses_entry_id, "ledger-0002")
        self.assertEqual(LedgerEntry.objects.filter(system_event__isnull=True).count(), 0)
        self.assertTrue(SystemEvent.objects.filter(aggregate_type="LedgerEntry").exists())

        latest_capacity = CapacityAssessment.objects.first()
        self.assertIsNotNone(latest_capacity)
        self.assertEqual(latest_capacity.assessment_id, "capacity-0002")
        self.assertEqual(latest_capacity.recommended_new_members, 0)

        self.assertTrue(Event.objects.filter(event_id="event-resource-0001").exists())
        self.assertTrue(Event.objects.filter(event_type=Event.EventType.DISPUTE).exists())

        plan = ProjectPlan.objects.get(plan_id="plan-bigapple001")
        self.assertEqual(plan.name, "bigapple001据点执行计划")
        revision = PlanRevision.objects.get(revision_id="plan-bigapple001-rev-v0_1_0")
        self.assertEqual(revision.status, PlanRevision.Status.PUBLISHED)
        self.assertGreaterEqual(PlanNode.objects.filter(revision=revision).count(), 30)
        self.assertTrue(PlanNode.objects.filter(title="光伏一期 0.5MW").exists())
        self.assertTrue(PlanNode.objects.filter(title="民宿和旅馆一期").exists())
        self.assertTrue(PlanDependency.objects.filter(revision=revision).exists())
        self.assertTrue(PlanRequirement.objects.filter(requirement_type=PlanRequirement.RequirementType.BUDGET).exists())
        self.assertTrue(PlanCapacityImpact.objects.filter(impact_type=PlanCapacityImpact.ImpactType.PV_MW).exists())
        self.assertEqual(Task.objects.get(task_id="task-0001").plan_node.code, "B1")

    def test_seed_demo_is_idempotent(self) -> None:
        call_command("seed_demo", stdout=StringIO())
        counts_after_first_run = {
            "tasks": Task.objects.count(),
            "events": Event.objects.count(),
            "ledger_entries": LedgerEntry.objects.count(),
            "system_events": SystemEvent.objects.count(),
            "disputes": Dispute.objects.count(),
            "capacity_assessments": CapacityAssessment.objects.count(),
            "project_plans": ProjectPlan.objects.count(),
            "plan_revisions": PlanRevision.objects.count(),
            "plan_nodes": PlanNode.objects.count(),
            "plan_dependencies": PlanDependency.objects.count(),
            "plan_requirements": PlanRequirement.objects.count(),
            "plan_capacity_impacts": PlanCapacityImpact.objects.count(),
        }

        call_command("seed_demo", stdout=StringIO())

        self.assertEqual(Task.objects.count(), counts_after_first_run["tasks"])
        self.assertEqual(Event.objects.count(), counts_after_first_run["events"])
        self.assertEqual(LedgerEntry.objects.count(), counts_after_first_run["ledger_entries"])
        self.assertEqual(SystemEvent.objects.count(), counts_after_first_run["system_events"])
        self.assertEqual(Dispute.objects.count(), counts_after_first_run["disputes"])
        self.assertEqual(CapacityAssessment.objects.count(), counts_after_first_run["capacity_assessments"])
        self.assertEqual(ProjectPlan.objects.count(), counts_after_first_run["project_plans"])
        self.assertEqual(PlanRevision.objects.count(), counts_after_first_run["plan_revisions"])
        self.assertEqual(PlanNode.objects.count(), counts_after_first_run["plan_nodes"])
        self.assertEqual(PlanDependency.objects.count(), counts_after_first_run["plan_dependencies"])
        self.assertEqual(PlanRequirement.objects.count(), counts_after_first_run["plan_requirements"])
        self.assertEqual(PlanCapacityImpact.objects.count(), counts_after_first_run["plan_capacity_impacts"])
        self.assertEqual(LedgerEntry.objects.filter(system_event__isnull=True).count(), 0)

    @override_settings(WORLD_DATABASE_ROUTING_ENABLED=True)
    def test_seed_demo_requires_explicit_world_when_routing_is_enabled(self) -> None:
        with self.assertRaises(CommandError) as captured:
            call_command("seed_demo", stdout=StringIO())

        self.assertIn("requires --world-id", str(captured.exception))

    def test_seed_demo_world_id_binds_command_context(self) -> None:
        output = StringIO()

        def assert_world_and_return(value):
            def inner(*args, **kwargs):
                current_world = get_current_world()
                self.assertIsNotNone(current_world)
                self.assertEqual(current_world.world_id, "simulation0001")
                return value

            return inner

        with (
            patch(
                "core.management.commands.seed_demo.seed_project_plan",
                side_effect=assert_world_and_return((object(), object(), {})),
            ),
            patch("core.management.commands.seed_demo.seed_members", side_effect=assert_world_and_return({})),
            patch("core.management.commands.seed_demo.seed_resources", side_effect=assert_world_and_return(None)),
            patch("core.management.commands.seed_demo.seed_tasks", side_effect=assert_world_and_return({})),
            patch("core.management.commands.seed_demo.seed_events", side_effect=assert_world_and_return(None)),
            patch("core.management.commands.seed_demo.seed_ledger", side_effect=assert_world_and_return({})),
            patch("core.management.commands.seed_demo.seed_disputes", side_effect=assert_world_and_return(None)),
            patch("core.management.commands.seed_demo.seed_capacity", side_effect=assert_world_and_return(None)),
        ):
            call_command("seed_demo", "--world-id", "simulation0001", stdout=output)

        self.assertIsNone(get_current_world())
        self.assertIn("world_id=simulation0001", output.getvalue())

    def test_zero_start_seed_creates_full_lifecycle_mainline(self) -> None:
        from live_os.demo_seed.zero_start import seed_zero_start

        result = seed_zero_start(founder_member_no="M-ZT-001", founder_display_name="测试发起人")
        revision = result["revision"]
        nodes = PlanNode.objects.filter(revision=revision).order_by("sequence")
        self.assertGreaterEqual(nodes.count(), 25)

        # Z nodes — Z0 is the only IN_PROGRESS node
        z0 = nodes.get(code="Z0")
        self.assertEqual(z0.status, PlanNode.Status.IN_PROGRESS)
        self.assertEqual(z0.node_type, PlanNode.NodeType.MILESTONE)

        for code in ("Z1", "Z2", "Z3"):
            node = nodes.get(code=code)
            self.assertEqual(node.status, PlanNode.Status.PLANNED)
            self.assertEqual(node.parent, z0)

        # Stage nodes — all PLANNED
        for code in ("A0", "B0", "C0", "D0"):
            stage = nodes.get(code=code)
            self.assertEqual(stage.status, PlanNode.Status.PLANNED)
            self.assertIn(stage.node_type, (PlanNode.NodeType.STAGE, PlanNode.NodeType.MILESTONE))

        # Children belong to correct stage
        for child_code, stage_code in (
            ("B1", "B0"),
            ("C3", "C0"),
            ("D4", "D0"),
        ):
            child = nodes.get(code=child_code)
            stage = nodes.get(code=stage_code)
            self.assertEqual(child.parent, stage)
            self.assertEqual(child.status, PlanNode.Status.PLANNED)

    def test_zero_start_seed_is_idempotent(self) -> None:
        from live_os.demo_seed.zero_start import seed_zero_start

        result = seed_zero_start(founder_member_no="M-ZT-002", founder_display_name="幂等测试")
        first_count = PlanNode.objects.filter(revision=result["revision"]).count()
        seed_zero_start(founder_member_no="M-ZT-002", founder_display_name="幂等测试")
        self.assertEqual(
            PlanNode.objects.filter(revision=result["revision"]).count(),
            first_count,
        )
