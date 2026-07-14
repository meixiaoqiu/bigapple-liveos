from __future__ import annotations

from django.test import TestCase
from django.utils import timezone

from core.models import Member, MemberApplication, PartnerApplication, PlanNode, PlanRevision, ProjectPlan, SimulationRun
from core.tests.helpers import create_member
from simulation.zero_start_screening import (
    member_application_for_run,
    partner_application_for_run,
    screen_member_application,
    screen_partner_application,
)
from simulation.zero_start_strategy import ApplicantSpec, PartnerSpec


class ZeroStartScreeningTests(TestCase):
    def setUp(self) -> None:
        self.now = timezone.now()
        plan = ProjectPlan.objects.create(plan_id="plan-sc-test", name="sc", status=ProjectPlan.Status.ACTIVE, created_at=self.now)
        revision = PlanRevision.objects.create(
            revision_id="plan-sc-test-rev", plan=plan, revision_code="v1",
            status=PlanRevision.Status.PUBLISHED, title="sc", change_summary="", created_at=self.now,
        )
        PlanNode.objects.create(
            node_id="node-sc", revision=revision, sequence=0, code="A0", title="A0",
            node_type=PlanNode.NodeType.MILESTONE, created_at=self.now, metadata={},
        )
        self.run = SimulationRun.objects.create(
            run_id="sim-run-sc-test", plan_revision=revision,
            status=SimulationRun.Status.RUNNING, max_turns=10, started_at=self.now,
            metadata={},
        )

    def _member_spec(self, **kw):
        defaults = dict(index=1, apply_hour=0, screen_hour=10, display_name="T", motivation="M",
                        capability_scores={"做饭": 80}, availability_hours_per_week=20)
        defaults.update(kw)
        return ApplicantSpec(**defaults)

    def _partner_spec(self, **kw):
        defaults = dict(index=1, apply_hour=0, screen_hour=10, organization_name="O", contact_name="C",
                        service_domains=("s",), can_issue_responsibility_documents=False,
                        responsibility_document_domains=(), qualification_summary="Q", quote_summary="Q",
                        service_area="S", delivery_cycle_days=10, constraints="", review_status="qualified")
        defaults.update(kw)
        return PartnerSpec(**defaults)

    def _create_app(self, ext_ref):
        return MemberApplication.objects.create(
            application_id=f"app-{ext_ref}", applicant_name="T", contact="c@t", motivation="M",
            submitted_at=self.now, frozen_at=self.now,
            metadata={"external_ref": ext_ref, "simulation_run_id": self.run.run_id},
        )

    def _create_partner_app(self, ext_ref):
        return PartnerApplication.objects.create(
            application_id=f"papp-{ext_ref}", organization_name="O", contact_name="C", contact="c@t",
            submitted_at=self.now, status=PartnerApplication.Status.QUALIFIED,
            can_issue_responsibility_documents=False,
            metadata={"external_ref": ext_ref, "simulation_run_id": self.run.run_id},
        )

    def test_member_application_for_run_finds_by_external_ref(self):
        self._create_app(f"{self.run.run_id}:member:1")
        app = member_application_for_run(run=self.run, spec=self._member_spec(index=1))
        self.assertIn(":member:1", app.application_id)

    def test_partner_application_for_run_finds_by_external_ref(self):
        self._create_partner_app(f"{self.run.run_id}:partner:1")
        app = partner_application_for_run(run=self.run, spec=self._partner_spec(index=1))
        self.assertIn(":partner:1", app.application_id)

    def test_screen_member_application_does_not_mutate_status(self):
        app = self._create_app(f"{self.run.run_id}:member:1")
        original_status = app.status
        screen_member_application(application=app, spec=self._member_spec(), screened_hour=10)
        app.refresh_from_db()
        self.assertEqual(app.status, original_status)
        self.assertIn("screening_status", app.metadata)

    def test_screen_member_application_writes_linked_member_metadata(self):
        user_model = __import__("django.contrib.auth", fromlist=["get_user_model"]).get_user_model()
        user = user_model.objects.create_user(username="sc-applicant", password="x")
        member = create_member(member_no="sc-applicant", status=Member.Status.PENDING_REVIEW)
        member.user = user
        member.save(update_fields=["user"])
        app = MemberApplication.objects.create(
            application_id="app-sc-linked", applicant_name="T", contact="c@t", motivation="M",
            submitted_at=self.now, frozen_at=self.now,
            linked_member=member, account_user=user,
            metadata={"external_ref": f"{self.run.run_id}:member:1", "simulation_run_id": self.run.run_id},
        )
        screen_member_application(application=app, spec=self._member_spec(), screened_hour=10)
        member.refresh_from_db()
        self.assertEqual(member.metadata.get("screening_status"), "candidate")

    def test_screen_partner_application_returns_snapshot(self):
        app = self._create_partner_app(f"{self.run.run_id}:partner:1")
        result = screen_partner_application(application=app, spec=self._partner_spec(), screened_hour=10)
        self.assertIn("decision", result)
        self.assertIn("organization_name", result)
