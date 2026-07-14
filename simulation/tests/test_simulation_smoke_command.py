from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import (
    Event,
    LedgerEntry,
    Member,
    MemberApplication,
    PartnerApplication,
    PlanChangeOperation,
    PlanChangeSet,
    PlanRevision,
    PlanRevisionProposal,
    PlanNode,
    ProjectPlan,
    Resource,
    SimulationFailure,
    SimulationRun,
    SimulationRunDisposition,
    SimulationTurn,
    SystemEvent,
    Task,
)
from simulation.zero_start_strategy import applicant_specs_for_hours, partner_specs_for_hours


@override_settings(
    WORLD_DATABASE_ROUTING_ENABLED=False,
    DEFAULT_WORLD_DATABASE_ALIAS="default",
    WORLD_DATABASE_ALIASES=("default",),
)
class SimulationSmokeCommandTests(TestCase):
    def test_run_simulation_smoke_seeds_world_and_runs_automatic_simulation(self) -> None:
        output = StringIO()

        call_command("run_simulation_smoke", "--world-id", "simulation0001", "--max-turns", "30", stdout=output)

        run = SimulationRun.objects.get()
        self.assertIn(run.status, {SimulationRun.Status.FAILED, SimulationRun.Status.COMPLETED, SimulationRun.Status.PAUSED})
        self.assertGreater(SimulationTurn.objects.filter(run=run).count(), 0)
        self.assertTrue(
            Event.objects.filter(
                generated_by=Event.GeneratedBy.SIMULATION_ENGINE,
                simulation_run=run,
                payload__run_id=run.run_id,
            ).exists()
        )
        self.assertIn("Simulation smoke passed: world=simulation0001", output.getvalue())
        self.assertIn("isolation=not_applicable", output.getvalue())

    def test_run_simulation_smoke_does_not_mutate_live_business_tables_after_seed(self) -> None:
        call_command("seed_world", "simulation0001", stdout=StringIO())
        counts_before = {
            "tasks": Task.objects.count(),
            "ledger_entries": LedgerEntry.objects.count(),
            "members": Member.objects.count(),
            "resources": Resource.objects.count(),
            "project_plans": ProjectPlan.objects.count(),
            "plan_nodes": PlanNode.objects.count(),
        }

        call_command(
            "run_simulation_smoke",
            "--world-id",
            "simulation0001",
            "--max-turns",
            "30",
            "--skip-seed",
            stdout=StringIO(),
        )

        counts_after = {
            "tasks": Task.objects.count(),
            "ledger_entries": LedgerEntry.objects.count(),
            "members": Member.objects.count(),
            "resources": Resource.objects.count(),
            "project_plans": ProjectPlan.objects.count(),
            "plan_nodes": PlanNode.objects.count(),
        }
        self.assertEqual(counts_after, counts_before)

    def test_run_simulation_smoke_refuses_realworld(self) -> None:
        with self.assertRaises(CommandError) as captured:
            call_command("run_simulation_smoke", "--world-id", "realworld", stdout=StringIO())

        self.assertIn("Refusing to run simulation smoke for non-simulation world", str(captured.exception))

    def test_seed_world_zero_start_creates_only_founder_baseline(self) -> None:
        output = StringIO()

        # Local .env may enable a bootstrap admin for manual bigsim login; this
        # baseline test verifies the zero_start template itself.
        with patch.dict("os.environ", {"BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_ENABLED": "false"}):
            call_command("seed_world", "simulation0001", "--template", "zero_start", stdout=output)

        self.assertTrue(Member.objects.filter(member_no="founder-0001", status=Member.Status.ACTIVE).exists())
        self.assertTrue(ProjectPlan.objects.filter(plan_id="plan-zero-start", status=ProjectPlan.Status.ACTIVE).exists())
        self.assertTrue(
            PlanRevision.objects.filter(revision_id="plan-zero-start-rev-v0_0_1", status=PlanRevision.Status.PUBLISHED).exists()
        )
        self.assertEqual(Member.objects.count(), 1)
        self.assertEqual(Task.objects.count(), 0)
        self.assertEqual(Resource.objects.count(), 0)
        self.assertIn("template=zero_start", output.getvalue())

    def test_zero_start_applicant_specs_grow_after_early_exposure(self) -> None:
        specs = applicant_specs_for_hours(168)

        early_count = len([spec for spec in specs if spec.apply_hour < 96])
        later_count = len([spec for spec in specs if spec.apply_hour >= 96])

        self.assertEqual(early_count, 6)
        self.assertGreater(later_count, early_count)

    def test_zero_start_partner_specs_keep_growing_and_include_document_signers(self) -> None:
        early_specs = partner_specs_for_hours(168)
        later_specs = partner_specs_for_hours(720)

        self.assertEqual(len(early_specs), 3)
        self.assertGreater(len(later_specs), 10)
        document_domains = {
            domain
            for spec in later_specs
            if spec.can_issue_responsibility_documents
            for domain in spec.responsibility_document_domains
        }
        self.assertIn("structural_safety_document", document_domains)
        self.assertIn("pv_system_design_document", document_domains)
        self.assertIn("electrical_grid_document", document_domains)
        self.assertIn("construction_safety_quality_document", document_domains)
        self.assertIn("acceptance_archive_document", document_domains)

    def test_run_zero_start_simulation_creates_hourly_recruitment_screening_trace(self) -> None:
        output = StringIO()

        call_command("run_zero_start_simulation", "--world-id", "simulation0001", "--hours", "96", stdout=output)

        run = SimulationRun.objects.get()
        self.assertEqual(run.status, SimulationRun.Status.RUNNING)
        self.assertEqual(run.metadata["scenario"], "zero_start")
        self.assertEqual(run.metadata["project_phase"], "preparation")
        self.assertIs(run.metadata["startup_gate_satisfied"], False)
        self.assertIs(run.metadata["can_continue"], True)
        self.assertEqual(SimulationTurn.objects.filter(run=run).count(), 97)
        first_turn = SimulationTurn.objects.get(run=run, turn_number=1)
        self.assertEqual(first_turn.metadata["simulation_hour"], 0)
        self.assertEqual(first_turn.metadata["state_machine"], "zero_start_recruitment_screening")
        self.assertEqual(first_turn.metadata["driver_mode"], "http_form")
        self.assertIn("funnel_delta", first_turn.metadata)
        self.assertIn("blockers", first_turn.metadata)
        self.assertIn("next_actions", first_turn.metadata)
        last_turn = SimulationTurn.objects.filter(run=run).order_by("-turn_number").first()
        self.assertIn("candidate_summary", last_turn.metadata)
        self.assertIn("startup_gate", last_turn.metadata)
        self.assertIn("missing_capabilities", last_turn.metadata["startup_gate"])
        self.assertIn("missing_document_signers", last_turn.metadata["startup_gate"])
        self.assertTrue(
            SimulationTurn.objects.filter(run=run, summary__contains="只有一个发起人").exists()
        )
        self.assertTrue(
            Event.objects.filter(
                generated_by=Event.GeneratedBy.SIMULATION_ENGINE,
                simulation_run=run,
                payload__scenario="zero_start",
            ).exists()
        )
        applications = MemberApplication.objects.filter(metadata__simulation_run_id=run.run_id)
        self.assertEqual(applications.count(), 6)
        self.assertTrue(applications.filter(metadata__screening_status="candidate").exists())
        self.assertTrue(applications.filter(metadata__screening_status="standby").exists())
        self.assertTrue(applications.filter(metadata__screening_status="rejected").exists())
        self.assertTrue(applications.filter(metadata__screening_status="withdrew").exists())
        simulation_members = Member.objects.filter(member_applications__metadata__simulation_run_id=run.run_id).distinct()
        self.assertEqual(simulation_members.count(), 6)
        self.assertEqual(
            simulation_members.filter(member_applications__metadata__screening_status="candidate").distinct().count(),
            3,
        )
        # Verify projections module produces the same results as direct queries.
        from simulation.projections import (
            candidate_members_for_run,
            candidate_summary_for_run,
        )
        from live_os.demo_seed.zero_start import ZERO_START_FOUNDER_MEMBER_NO

        proj_members = candidate_members_for_run(
            run,
            founder_member_no=ZERO_START_FOUNDER_MEMBER_NO,
        )
        self.assertEqual(len(proj_members), 4)  # founder + 3 candidates
        proj_summary = candidate_summary_for_run(run, startup_gate_satisfied=False)
        self.assertEqual(proj_summary["registered_applicants"], 6)
        self.assertEqual(proj_summary["candidate_members"], 3)

        partners = PartnerApplication.objects.filter(metadata__simulation_run_id=run.run_id)
        self.assertEqual(partners.count(), 2)
        self.assertTrue(partners.filter(status=PartnerApplication.Status.STANDBY).exists())
        self.assertTrue(
            SystemEvent.objects.filter(event_type=SystemEvent.EventType.MEMBER_APPLICATION_SUBMITTED).exists()
        )
        self.assertTrue(
            SystemEvent.objects.filter(event_type=SystemEvent.EventType.PARTNER_APPLICATION_SUBMITTED).exists()
        )
        failure = SimulationFailure.objects.get(run=run)
        self.assertEqual(failure.failure_type, SimulationFailure.FailureType.RESPONSIBILITY_CLOSURE_MISSING)
        self.assertIn("required_initial_capabilities", failure.metadata)
        self.assertIn("required_document_signers", failure.metadata)
        self.assertIn("meal_support", {row["code"] for row in failure.metadata["missing_capabilities"]})
        self.assertIn("structural_safety_document", {row["code"] for row in failure.metadata["missing_document_signers"]})
        self.assertTrue(PlanRevisionProposal.objects.filter(run=run, title__contains="自媒体").exists())
        change_set = PlanChangeSet.objects.get(run=run, title__contains="启动门槛")
        operations = PlanChangeOperation.objects.filter(change_set=change_set)
        self.assertEqual(operations.filter(operation_type=PlanChangeOperation.OperationType.ADD_NODE).count(), 1)
        self.assertEqual(operations.filter(operation_type=PlanChangeOperation.OperationType.ADD_REQUIREMENT).count(), 11)
        self.assertTrue(operations.filter(metadata__requirement_kind="capability").exists())
        self.assertTrue(operations.filter(metadata__requirement_kind="document").exists())
        self.assertIn("Zero-start simulation passed: world=simulation0001", output.getvalue())

    def test_run_zero_start_simulation_completes_pre_engineering_after_startup_gate(self) -> None:
        output = StringIO()

        call_command("run_zero_start_simulation", "--world-id", "simulation0001", "--hours", "500", stdout=output)

        run = SimulationRun.objects.get()
        self.assertEqual(run.status, SimulationRun.Status.RUNNING)
        self.assertEqual(run.metadata["project_phase"], "pre_engineering")
        self.assertIs(run.metadata["startup_gate_satisfied"], True)
        self.assertIs(run.metadata["can_continue"], True)

        call_command("run_zero_start_simulation", "--world-id", "simulation0001", "--hours", "220", stdout=output)

        run.refresh_from_db()
        self.assertEqual(run.status, SimulationRun.Status.COMPLETED)
        self.assertEqual(run.metadata["project_phase"], "pre_engineering_completed")
        self.assertIs(run.metadata["startup_gate_satisfied"], True)
        self.assertIs(run.metadata["can_continue"], False)
        pre_engineering = run.metadata["pre_engineering"]
        self.assertEqual(pre_engineering["status"], "completed")
        self.assertEqual(pre_engineering["pending_milestone_count"], 0)
        self.assertEqual(pre_engineering["selected_site_code"], "site-roof-a")
        self.assertGreaterEqual(len(pre_engineering["candidate_sites"]), 3)
        document_milestones = [
            row for row in pre_engineering["milestones"] if row.get("document_code")
        ]
        self.assertTrue(document_milestones)
        self.assertTrue(all(row["covered_by"] for row in document_milestones))
        self.assertTrue(
            SimulationTurn.objects.filter(
                run=run,
                metadata__pre_engineering__status="completed",
            ).exists()
        )
        self.assertTrue(
            Event.objects.filter(
                simulation_run=run,
                payload__pre_engineering__selected_site_code="site-roof-a",
            ).exists()
        )
        self.assertIn("status=completed", output.getvalue())

    def test_run_zero_start_simulation_uses_latest_published_zero_start_revision(self) -> None:
        call_command("seed_world", "simulation0001", "--template", "zero_start", stdout=StringIO())
        plan = ProjectPlan.objects.get(plan_id="plan-zero-start")
        latest_revision = PlanRevision.objects.create(
            revision_id="plan-zero-start-rev-v0_0_2",
            plan=plan,
            revision_code="v0.0.2",
            status=PlanRevision.Status.PUBLISHED,
            title="零起点仿真基线 / v0.0.2",
            change_summary="吸收上一轮报名筛选经验。",
            created_at=timezone.now(),
            published_at=timezone.now(),
            metadata={"template": "zero_start", "applied_change_set_id": "changeset-test"},
        )
        output = StringIO()

        call_command("run_zero_start_simulation", "--world-id", "simulation0001", "--hours", "24", "--skip-seed", stdout=output)

        run = SimulationRun.objects.get()
        self.assertEqual(run.plan_revision, latest_revision)
        self.assertIn("Zero-start simulation passed: world=simulation0001", output.getvalue())

    def test_seed_world_zero_start_does_not_republish_old_baseline_over_latest_revision(self) -> None:
        call_command("seed_world", "simulation0001", "--template", "zero_start", stdout=StringIO())
        plan = ProjectPlan.objects.get(plan_id="plan-zero-start")
        original_revision = PlanRevision.objects.get(revision_id="plan-zero-start-rev-v0_0_1")
        latest_revision = PlanRevision.objects.create(
            revision_id="plan-zero-start-rev-v0_0_2",
            plan=plan,
            revision_code="v0.0.2",
            status=PlanRevision.Status.PUBLISHED,
            title="零起点仿真基线 / v0.0.2",
            change_summary="吸收上一轮报名筛选经验。",
            created_at=timezone.now(),
            published_at=timezone.now(),
            metadata={"template": "zero_start", "applied_change_set_id": "changeset-test"},
        )
        output = StringIO()

        call_command("seed_world", "simulation0001", "--template", "zero_start", stdout=StringIO())
        call_command("run_zero_start_simulation", "--world-id", "simulation0001", "--hours", "24", stdout=output)

        original_revision.refresh_from_db()
        run = SimulationRun.objects.get()
        self.assertEqual(run.plan_revision, latest_revision)
        self.assertLess(original_revision.published_at, latest_revision.published_at)
        self.assertIn("Zero-start simulation passed: world=simulation0001", output.getvalue())

    def test_zero_start_revision_with_gate_does_not_generate_duplicate_gate_change_set(self) -> None:
        call_command("seed_world", "simulation0001", "--template", "zero_start", stdout=StringIO())
        plan = ProjectPlan.objects.get(plan_id="plan-zero-start")
        latest_revision = PlanRevision.objects.create(
            revision_id="plan-zero-start-rev-with-z0",
            plan=plan,
            revision_code="v0.0.2",
            status=PlanRevision.Status.PUBLISHED,
            title="Zero-start baseline with Z0",
            change_summary="The startup gate has already been absorbed into the plan baseline.",
            created_at=timezone.now(),
            published_at=timezone.now(),
            metadata={"template": "zero_start", "applied_change_set_id": "changeset-test"},
        )
        PlanNode.objects.create(
            node_id="node-zero-start-z0",
            revision=latest_revision,
            sequence=0,
            code="Z0",
            title="Zero-start startup gate",
            node_type=PlanNode.NodeType.RECRUITMENT,
            created_at=timezone.now(),
            metadata={"scenario": "zero_start"},
        )

        call_command("run_zero_start_simulation", "--world-id", "simulation0001", "--hours", "24", "--skip-seed", stdout=StringIO())

        run = SimulationRun.objects.get()
        self.assertEqual(run.plan_revision, latest_revision)
        self.assertEqual(PlanRevisionProposal.objects.filter(run=run).count(), 0)
        self.assertEqual(PlanChangeSet.objects.filter(run=run).count(), 0)
        self.assertEqual(run.metadata["change_set_id"], "")

    def test_run_zero_start_simulation_continues_unfinished_recruitment_run(self) -> None:
        call_command("run_zero_start_simulation", "--world-id", "simulation0001", "--hours", "24", stdout=StringIO())
        run = SimulationRun.objects.get()
        first_turn_count = SimulationTurn.objects.filter(run=run).count()
        first_change_set_count = PlanChangeSet.objects.filter(run=run).count()

        call_command("run_zero_start_simulation", "--world-id", "simulation0001", "--hours", "24", stdout=StringIO())

        self.assertEqual(SimulationRun.objects.count(), 1)
        run.refresh_from_db()
        self.assertEqual(run.status, SimulationRun.Status.RUNNING)
        self.assertEqual(run.metadata["completed_hours"], 48)
        self.assertGreater(SimulationTurn.objects.filter(run=run).count(), first_turn_count)
        self.assertEqual(PlanChangeSet.objects.filter(run=run).count(), first_change_set_count)

    def test_run_zero_start_simulation_continues_legacy_startup_gate_failed_run(self) -> None:
        call_command("run_zero_start_simulation", "--world-id", "simulation0001", "--hours", "24", stdout=StringIO())
        run = SimulationRun.objects.get()
        run.status = SimulationRun.Status.FAILED
        run.ended_at = timezone.now()
        run.failure_summary = "Z0 自媒体报名筛选后仍未达到启动门槛"
        run.metadata = {
            **run.metadata,
            "current_hour": 23,
            "completed_hours": 24,
            "startup_gate_satisfied": False,
            "can_continue": True,
        }
        run.save(update_fields=["status", "ended_at", "failure_summary", "metadata"])

        output = StringIO()
        call_command("run_zero_start_simulation", "--world-id", "simulation0001", "--hours", "24", stdout=output)

        self.assertEqual(SimulationRun.objects.count(), 1)
        run.refresh_from_db()
        self.assertEqual(run.status, SimulationRun.Status.RUNNING)
        self.assertIsNone(run.ended_at)
        self.assertEqual(run.metadata["completed_hours"], 48)
        self.assertIn("status=running", output.getvalue())

    def test_run_zero_start_simulation_does_not_continue_disposed_failed_run(self) -> None:
        call_command("run_zero_start_simulation", "--world-id", "simulation0001", "--hours", "24", stdout=StringIO())
        disposed_run = SimulationRun.objects.get()
        disposed_run.status = SimulationRun.Status.FAILED
        disposed_run.ended_at = timezone.now()
        disposed_run.failure_summary = "Z0 自媒体报名筛选后仍未达到启动门槛"
        disposed_run.metadata = {
            **disposed_run.metadata,
            "current_hour": 23,
            "completed_hours": 24,
            "startup_gate_satisfied": False,
            "can_continue": True,
        }
        disposed_run.save(update_fields=["status", "ended_at", "failure_summary", "metadata"])
        SimulationRunDisposition.objects.create(
            disposition_id="disposition-zero-start-disposed-test",
            source_world_id="simulation0001",
            source_world_type="simulation",
            source_database_alias="default",
            source_database_name="test",
            source_run_id=disposed_run.run_id,
            run_status=disposed_run.status,
            run_started_at=disposed_run.started_at,
            run_ended_at=disposed_run.ended_at,
            simulation_round=1,
            scenario="zero_start",
            disposition=SimulationRunDisposition.Disposition.DISCARDED,
            reason="测试已处置的 failed run 不应再被继续。",
            decided_by="test",
            decided_at=timezone.now(),
        )

        output = StringIO()
        call_command("run_zero_start_simulation", "--world-id", "simulation0001", "--hours", "24", stdout=output)

        self.assertEqual(SimulationRun.objects.count(), 2)
        disposed_run.refresh_from_db()
        self.assertEqual(disposed_run.status, SimulationRun.Status.FAILED)
        new_run = SimulationRun.objects.exclude(run_id=disposed_run.run_id).get()
        self.assertEqual(new_run.status, SimulationRun.Status.RUNNING)
        self.assertIn(f"run={new_run.run_id}", output.getvalue())

    def test_run_zero_start_simulation_refuses_realworld(self) -> None:
        with self.assertRaises(CommandError) as captured:
            call_command("run_zero_start_simulation", "--world-id", "realworld", stdout=StringIO())

        self.assertIn("Refusing to run zero-start simulation for non-simulation world", str(captured.exception))
