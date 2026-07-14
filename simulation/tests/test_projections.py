from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from core.models import (
    Member,
    MemberApplication,
    PartnerApplication,
    PlanNode,
    PlanRevision,
    ProjectPlan,
    SimulationRun,
)
from core.tests.helpers import create_member
from simulation.projections import (
    SCREENING_CANDIDATE,
    SCREENING_REGISTERED,
    SCREENING_REJECTED,
    SCREENING_STANDBY,
    SCREENING_WITHDREW,
    candidate_applications_for_run,
    candidate_members_for_run,
    candidate_summary_for_run,
    is_screened,
    is_screening_candidate,
    is_screening_standby,
    member_applications_for_run,
    partner_applications_for_run,
    screening_status_for,
)


class ProjectionsTests(TestCase):
    """Unit tests for simulation.projections."""

    def setUp(self) -> None:
        self.now = timezone.now()
        plan = ProjectPlan.objects.create(
            plan_id="plan-projections-test",
            name="test plan",
            status=ProjectPlan.Status.ACTIVE,
            created_at=self.now,
        )
        revision = PlanRevision.objects.create(
            revision_id="plan-projections-test-rev-v0_0_1",
            plan=plan,
            revision_code="v0.0.1",
            status=PlanRevision.Status.PUBLISHED,
            title="test revision",
            change_summary="test",
            created_at=self.now,
        )
        PlanNode.objects.create(
            node_id="node-projections-test",
            revision=revision,
            sequence=0,
            code="A0",
            title="test node",
            node_type=PlanNode.NodeType.MILESTONE,
            created_at=self.now,
            metadata={},
        )
        self.run = SimulationRun.objects.create(
            run_id="sim-run-projections-test",
            plan_revision=revision,
            status=SimulationRun.Status.RUNNING,
            max_turns=10,
            started_at=self.now,
            metadata={"scenario": "test"},
        )
        self.user_model = get_user_model()

    def _app(self, member_no: str, screening_status: str | None) -> MemberApplication:
        user = self.user_model.objects.create_user(username=member_no, password="x")
        member = create_member(member_no=member_no, status=Member.Status.PENDING_REVIEW)
        member.user = user
        member.save(update_fields=["user"])
        meta = {"simulation_run_id": self.run.run_id}
        if screening_status is not None:
            meta["screening_status"] = screening_status
        return MemberApplication.objects.create(
            application_id=f"member-application-{member_no}",
            applicant_name=member_no,
            contact=f"{member_no}@test",
            motivation="test",
            submitted_at=self.now,
            frozen_at=self.now,
            linked_member=member,
            account_user=user,
            metadata=meta,
        )

    # screening_status_for

    def test_screening_status_for_returns_status_when_present(self) -> None:
        app = self._app("screened-app", SCREENING_CANDIDATE)
        self.assertEqual(screening_status_for(app), SCREENING_CANDIDATE)

    def test_screening_status_for_falls_back_to_registered(self) -> None:
        app = self._app("unscreened-app", None)
        self.assertEqual(screening_status_for(app), SCREENING_REGISTERED)

    # is_screening_candidate / standby / screened

    def test_is_screening_candidate(self) -> None:
        self.assertTrue(is_screening_candidate(self._app("c1", SCREENING_CANDIDATE)))
        self.assertFalse(is_screening_candidate(self._app("c2", SCREENING_STANDBY)))
        self.assertFalse(is_screening_candidate(self._app("c3", None)))

    def test_is_screening_standby(self) -> None:
        self.assertTrue(is_screening_standby(self._app("s1", SCREENING_STANDBY)))
        self.assertFalse(is_screening_standby(self._app("s2", SCREENING_CANDIDATE)))

    def test_is_screened(self) -> None:
        self.assertTrue(is_screened(self._app("sc1", SCREENING_CANDIDATE)))
        self.assertTrue(is_screened(self._app("sc2", SCREENING_REJECTED)))
        self.assertFalse(is_screened(self._app("sc3", None)))

    # queryset helpers

    def test_candidate_applications_for_run_only_returns_candidates(self) -> None:
        self._app("candidate-a", SCREENING_CANDIDATE)
        self._app("candidate-b", SCREENING_CANDIDATE)
        self._app("standby-x", SCREENING_STANDBY)
        self._app("rejected-y", SCREENING_REJECTED)
        qs = candidate_applications_for_run(self.run)
        self.assertEqual(qs.count(), 2)

    def test_candidate_members_for_run_without_founder_returns_candidates_only(self) -> None:
        self._app("candidate-a", SCREENING_CANDIDATE)
        members = candidate_members_for_run(self.run, founder_member_no=None)
        self.assertEqual(len(members), 1)
        members = candidate_members_for_run(self.run, founder_member_no="founder-noexist")
        self.assertEqual(len(members), 1)  # founder not found, only applicant

    def test_candidate_members_for_run_with_founder_includes_founder_first(self) -> None:
        create_member(member_no="founder-test", status=Member.Status.ACTIVE)
        self._app("candidate-a", SCREENING_CANDIDATE)
        members = candidate_members_for_run(self.run, founder_member_no="founder-test")
        self.assertEqual(len(members), 2)
        self.assertEqual(members[0].member_no, "founder-test")
        self.assertEqual(members[1].member_no, "candidate-a")

    def test_candidate_members_for_run_skips_app_without_linked_member(self) -> None:
        MemberApplication.objects.create(
            application_id="member-application-no-link",
            applicant_name="no-link",
            contact="x@test",
            motivation="x",
            submitted_at=self.now,
            frozen_at=self.now,
            metadata={"simulation_run_id": self.run.run_id, "screening_status": SCREENING_CANDIDATE},
        )
        members = candidate_members_for_run(self.run)
        self.assertEqual(len(members), 0)

    # candidate_summary_for_run

    def test_candidate_summary_counts_all_screening_statuses(self) -> None:
        self._app("c1", SCREENING_CANDIDATE)
        self._app("c2", SCREENING_CANDIDATE)
        self._app("s1", SCREENING_STANDBY)
        self._app("r1", SCREENING_REJECTED)
        self._app("w1", SCREENING_WITHDREW)
        # one unscreened
        self._app("reg1", None)
        summary = candidate_summary_for_run(self.run, startup_gate_satisfied=False)
        self.assertEqual(summary["registered_applicants"], 6)
        self.assertEqual(summary["candidate_members"], 2)
        self.assertEqual(summary["standby_applicants"], 1)
        self.assertEqual(summary["rejected_applicants"], 1)
        self.assertEqual(summary["withdrawn_applicants"], 1)
        self.assertEqual(summary["screened_applicants"], 5)
        self.assertFalse(summary["startup_gate_satisfied"])

    def test_member_applications_for_run_scoped_to_run(self) -> None:
        self._app("app-a", SCREENING_CANDIDATE)
        other_run = SimulationRun.objects.create(
            run_id="sim-run-other",
            plan_revision=self.run.plan_revision,
            status=SimulationRun.Status.RUNNING,
            max_turns=5,
            started_at=self.now,
            metadata={"scenario": "other"},
        )
        MemberApplication.objects.create(
            application_id="member-application-other",
            applicant_name="other",
            contact="other@test",
            motivation="other",
            submitted_at=self.now,
            frozen_at=self.now,
            metadata={"simulation_run_id": other_run.run_id},
        )
        self.assertEqual(member_applications_for_run(self.run).count(), 1)

    def test_partner_applications_for_run_scoped_to_run(self) -> None:
        PartnerApplication.objects.create(
            application_id="partner-app-1",
            organization_name="测试合作方",
            contact_name="p",
            contact="p@test",
            submitted_at=self.now,
            metadata={"simulation_run_id": self.run.run_id},
        )
        self.assertEqual(partner_applications_for_run(self.run).count(), 1)
