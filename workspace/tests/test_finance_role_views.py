"""Workspace tests for governed finance reviewer appointments."""

from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from core.finance_role_services import nominate_finance_reviewer
from core.finance_setup import ensure_finance_roles
from core.governance_setup import ensure_administrator_role
from core.member_roles import ROLE_COVENANTER, ROLE_DELIBERATOR, ensure_catalog_role
from core.models import Proposal
from core.proposals.lifecycle import create_role_appointment_proposal
from core.role_assignment_services import create_role_assignment
from core.tests.helpers import create_member, login_as_member


@override_settings(
    SITE_FIXED_WORLD=True, SITE_WORLD_ID="simulation0001", SITE_WORLD_DATABASE_ALIAS="default",
    SITE_WORLD_DATABASE_NAME="test", SITE_WORLD_TYPE="simulation",
)
class FinanceRoleWorkspaceTests(TestCase):
    def setUp(self):
        self.manager = create_member("finance-role-view-manager", role_name=ROLE_COVENANTER)
        create_role_assignment(member=self.manager, role=ensure_administrator_role()["role"])
        create_role_assignment(member=self.manager, role=ensure_catalog_role(ROLE_DELIBERATOR))
        self.target = create_member("finance-role-view-target", role_name=ROLE_COVENANTER)
        login_as_member(self.client, self.manager)

    def test_manager_can_nominate_vote_and_execute_without_client_role_selection(self):
        page = self.client.get("/workspace/finance/reviewer-appointments/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, self.target.member_no)
        response = self.client.post(
            "/workspace/finance/reviewer-appointments/",
            {"action": "nominate", "target_member_id": self.target.pk, "reason": "负责审核", "role_id": "forged"},
        )
        self.assertEqual(response.status_code, 302)
        proposal = Proposal.objects.get(proposal_type=Proposal.ProposalType.ROLE_APPOINTMENT)
        self.client.post(
            "/workspace/finance/reviewer-appointments/",
            {"action": "vote", "proposal_id": proposal.pk, "choice": "yes", "score": "999"},
        )
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.Status.PASSED)
        self.client.post(
            "/workspace/finance/reviewer-appointments/",
            {"action": "execute", "proposal_id": proposal.pk},
        )
        self.assertTrue(self.target.role_assignments.filter(role__name="财务审核者", status="active").exists())

    def test_anonymous_and_ordinary_covenanter_are_denied(self):
        self.client.logout()
        self.assertEqual(self.client.get("/workspace/finance/reviewer-appointments/").status_code, 403)
        ordinary = create_member("finance-role-view-ordinary", role_name=ROLE_COVENANTER)
        login_as_member(self.client, ordinary)
        self.assertEqual(self.client.get("/workspace/finance/reviewer-appointments/").status_code, 403)
        response = self.client.post(
            "/workspace/finance/reviewer-appointments/",
            {"action": "nominate", "target_member_id": self.target.pk, "reason": "越权"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Proposal.objects.exists())

    def test_wrong_proposal_type_cannot_be_executed(self):
        wrong = create_role_appointment_proposal(
            target_member=self.target,
            target_role=ensure_administrator_role()["role"],
            proposer_member=self.manager,
        )
        Proposal.objects.filter(pk=wrong.pk).update(status=Proposal.Status.PASSED)
        wrong.refresh_from_db()
        response = self.client.post(
            "/workspace/finance/reviewer-appointments/",
            {"action": "execute", "proposal_id": wrong.pk},
            follow=True,
        )
        self.assertContains(response, "不是财务审核职责任命提案")
        self.assertFalse(self.target.role_assignments.filter(role__name="财务审核者").exists())

    def test_non_deliberator_manager_sees_page_but_vote_fails(self):
        manager_only = create_member("finance-role-view-manager-only", role_name=ROLE_COVENANTER)
        create_role_assignment(member=manager_only, role=ensure_administrator_role()["role"])
        proposal = nominate_finance_reviewer(actor=self.manager, target_member=self.target)
        login_as_member(self.client, manager_only)
        response = self.client.post(
            "/workspace/finance/reviewer-appointments/",
            {"action": "vote", "proposal_id": proposal.pk, "choice": "yes"},
            follow=True,
        )
        self.assertContains(response, "不在此提案的投票资格范围")
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.Status.VOTING)

    def test_future_and_expired_assignments_are_not_current_reviewers(self):
        review_role = ensure_finance_roles()["review_role"]
        now = timezone.now()
        create_role_assignment(
            member=self.target,
            role=review_role,
            start_at=now - timedelta(days=2),
            end_at=now - timedelta(days=1),
        )
        future = create_member("finance-role-view-future", role_name=ROLE_COVENANTER)
        create_role_assignment(
            member=future,
            role=review_role,
            start_at=now + timedelta(days=1),
            end_at=now + timedelta(days=2),
        )

        response = self.client.get("/workspace/finance/reviewer-appointments/")

        reviewer_ids = set(response.context["reviewers"].values_list("pk", flat=True))
        candidate_ids = {candidate.pk for candidate in response.context["candidates"]}
        self.assertNotIn(self.target.pk, reviewer_ids)
        self.assertNotIn(future.pk, reviewer_ids)
        self.assertIn(self.target.pk, candidate_ids)
        self.assertIn(future.pk, candidate_ids)

    def test_suspended_reviewer_is_neither_current_nor_candidate(self):
        review_role = ensure_finance_roles()["review_role"]
        create_role_assignment(member=self.target, role=review_role)
        self.target.status = self.target.Status.SUSPENDED
        self.target.save(update_fields=("status",))

        response = self.client.get("/workspace/finance/reviewer-appointments/")

        reviewer_ids = set(response.context["reviewers"].values_list("pk", flat=True))
        candidate_ids = {candidate.pk for candidate in response.context["candidates"]}
        self.assertNotIn(self.target.pk, reviewer_ids)
        self.assertNotIn(self.target.pk, candidate_ids)
