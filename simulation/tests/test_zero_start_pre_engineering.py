from __future__ import annotations

from django.test import TestCase
from django.utils import timezone

from core.models import PartnerApplication, PlanRevision, ProjectPlan, SimulationRun
from simulation.zero_start_pre_engineering import (
    candidate_site_rows,
    document_signer_for_code,
    pre_engineering_hour_summary,
    pre_engineering_next_actions,
    pre_engineering_state,
    selected_site_candidate,
)


class ZeroStartPreEngineeringTests(TestCase):
    def setUp(self) -> None:
        self.now = timezone.now()
        plan = ProjectPlan.objects.create(
            plan_id="plan-pe-test", name="pe", status=ProjectPlan.Status.ACTIVE, created_at=self.now,
        )
        self.revision = PlanRevision.objects.create(
            revision_id="plan-pe-test-rev", plan=plan, revision_code="v1",
            status=PlanRevision.Status.PUBLISHED, title="pe", change_summary="", created_at=self.now,
        )

    def _run(self, metadata=None):
        return SimulationRun.objects.create(
            run_id="sim-run-pe-test", plan_revision=self.revision,
            status=SimulationRun.Status.RUNNING, max_turns=10, started_at=self.now,
            metadata=metadata or {},
        )

    def test_pre_engineering_state_empty_when_gate_not_satisfied(self):
        run = self._run()
        self.assertEqual(pre_engineering_state(run=run, hour=10, startup_gate={"startup_gate_satisfied": False}), {})

    def test_pre_engineering_state_computes_elapsed_hours(self):
        run = self._run(metadata={"pre_engineering_started_hour": 0})
        state = pre_engineering_state(run=run, hour=50, startup_gate={"startup_gate_satisfied": True})
        self.assertGreaterEqual(state["elapsed_hours"], 50)
        self.assertIn("milestones", state)
        self.assertIn("candidate_sites", state)

    def test_candidate_site_rows_show_roof_a(self):
        rows = candidate_site_rows(0)
        codes = {r["code"] for r in rows}
        self.assertIn("site-roof-a", codes)

    def test_candidate_site_rows_expand_with_hours(self):
        rows50 = candidate_site_rows(50)
        for r in rows50:
            if r["code"] == "site-roof-a":
                self.assertNotEqual(r["grid_prescreen_status"], "pending")

    def test_selected_site_candidate_returns_site_after_48h(self):
        self.assertIsNone(selected_site_candidate(10))
        self.assertIsNotNone(selected_site_candidate(50))

    def test_document_signer_for_code_finds_signer(self):
        run = self._run()
        PartnerApplication.objects.create(
            application_id="partner-pe-signer", organization_name="S", contact_name="c", contact="c@t",
            submitted_at=self.now,
            status=PartnerApplication.Status.QUALIFIED, can_issue_responsibility_documents=True,
            responsibility_document_domains=["structural_safety_document"],
            metadata={"simulation_run_id": run.run_id},
        )
        result = document_signer_for_code(run=run, document_code="structural_safety_document")
        self.assertEqual(result["organization_name"], "S")

    def test_pre_engineering_hour_summary_completed(self):
        pe = {"status": "completed", "selected_site_code": "site-roof-a"}
        self.assertIn("工程前置阶段完成", pre_engineering_hour_summary(pe))

    def test_pre_engineering_next_actions_incomplete(self):
        actions = pre_engineering_next_actions([{"name": "并网预筛", "completed": False}])
        self.assertTrue(any("继续推进" in a for a in actions))
