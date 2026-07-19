from __future__ import annotations

from django.test import TestCase

from core.models import PlanRevision, ProjectPlan, SimulationRun
from simulation.form_drivers import FormSubmissionResult
from simulation.zero_start_form_submission import (
    availability_slots_for_spec,
    motivation_reasons_for_spec,
    role_gap_for_spec,
    submit_member_application_via_form,
    submit_partner_application_via_form,
)
from simulation.zero_start_strategy import ApplicantSpec, PartnerSpec
from django.utils import timezone


class FakeDriver:
    mode = "form"

    def __init__(self):
        self.last_member_kwargs = None
        self.last_partner_kwargs = None

    def submit_member_application(self, **kwargs):
        self.last_member_kwargs = kwargs
        return FormSubmissionResult(success=True, path="/apply/", status_code=200, application_id="app-1", errors=[])

    def submit_partner_application(self, **kwargs):
        self.last_partner_kwargs = kwargs
        return FormSubmissionResult(success=True, path="/apply/partner/", status_code=200, application_id="papp-1", errors=[])


class ZeroStartFormSubmissionTests(TestCase):
    def setUp(self) -> None:
        self.now = timezone.now()
        plan = ProjectPlan.objects.create(plan_id="plan-fs-test", name="fs", status=ProjectPlan.Status.ACTIVE, created_at=self.now)
        revision = PlanRevision.objects.create(
            revision_id="plan-fs-test-rev", plan=plan, revision_code="v1",
            status=PlanRevision.Status.PUBLISHED, title="fs", change_summary="", created_at=self.now,
        )
        self.run = SimulationRun.objects.create(
            run_id="sim-run-fs-test", plan_revision=revision,
            status=SimulationRun.Status.RUNNING, max_turns=10, started_at=self.now,
            metadata={},
        )
        self.driver = FakeDriver()

    def _member_spec(self, **kw):
        defaults = dict(index=1, apply_hour=0, screen_hour=10, display_name="T", motivation="M",
                        capability_scores={"文档": 70}, availability_hours_per_week=10)
        defaults.update(kw)
        return ApplicantSpec(**defaults)

    def _partner_spec(self, **kw):
        defaults = dict(index=1, apply_hour=0, screen_hour=10, organization_name="O", contact_name="C",
                        service_domains=("s",), can_issue_responsibility_documents=False,
                        responsibility_document_domains=(), qualification_summary="Q", quote_summary="Q",
                        service_area="S", delivery_cycle_days=10, constraints="")
        defaults.update(kw)
        return PartnerSpec(**defaults)

    def test_availability_slots_for_spec_any_time(self):
        self.assertEqual(availability_slots_for_spec(self._member_spec(availability_hours_per_week=30)), ["any_time"])

    def test_availability_slots_for_spec_off_hours(self):
        self.assertEqual(availability_slots_for_spec(self._member_spec(availability_hours_per_week=10)), ["off_hours", "weekend"])

    def test_role_gap_for_spec_developer(self):
        self.assertEqual(role_gap_for_spec(self._member_spec(capability_scores={"文档": 70})), "ai_engineer")

    def test_motivation_reasons_for_spec_default(self):
        spec = self._member_spec(capability_scores={"兴趣": 50})
        self.assertEqual(motivation_reasons_for_spec(spec), ["build_community", "other"])

    def test_submit_member_application_via_form_payload_keys(self):
        result = submit_member_application_via_form(
            driver=self.driver, world_id="test", run=self.run, spec=self._member_spec(), hour=1,
        )
        self.assertTrue(result.success)
        self.assertIsNotNone(self.driver.last_member_kwargs)
        data = self.driver.last_member_kwargs["data"]
        self.assertIn("username", data)
        self.assertIn("password1", data)
        self.assertIn("password2", data)
        self.assertIn("applicant_name", data)
        self.assertIn("contact", data)
        self.assertIn("motivation", data)
        self.assertIn("role_gap", data)
        self.assertIn("availability_slots", data)
        self.assertIn("motivation_reasons", data)
        self.assertIn("capabilities_text", data)
        self.assertIn("requested_member_no", data)
        self.assertIn("confirm_submit", data)
        self.assertEqual(self.driver.last_member_kwargs["external_ref"], f"{self.run.run_id}:member:1")
        self.assertEqual(self.driver.last_member_kwargs["world_id"], "test")
        self.assertEqual(self.driver.last_member_kwargs["run_id"], self.run.run_id)
        self.assertEqual(self.driver.last_member_kwargs["simulation_hour"], 1)

    def test_submit_partner_application_via_form_payload_keys(self):
        result = submit_partner_application_via_form(
            driver=self.driver, world_id="test", run=self.run, spec=self._partner_spec(), hour=1,
        )
        self.assertTrue(result.success)
        self.assertIsNotNone(self.driver.last_partner_kwargs)
        data = self.driver.last_partner_kwargs["data"]
        self.assertIn("organization_name", data)
        self.assertIn("contact_name", data)
        self.assertIn("contact", data)
        self.assertIn("service_domains_text", data)
        self.assertIn("can_issue_responsibility_documents", data)
        self.assertIn("responsibility_document_domains_text", data)
        self.assertIn("qualification_summary", data)
        self.assertIn("quote_summary", data)
        self.assertIn("service_area", data)
        self.assertIn("delivery_cycle_days", data)
        self.assertIn("constraints", data)
        self.assertEqual(self.driver.last_partner_kwargs["external_ref"], f"{self.run.run_id}:partner:1")
        self.assertEqual(self.driver.last_partner_kwargs["world_id"], "test")
        self.assertEqual(self.driver.last_partner_kwargs["run_id"], self.run.run_id)
        self.assertEqual(self.driver.last_partner_kwargs["simulation_hour"], 1)
