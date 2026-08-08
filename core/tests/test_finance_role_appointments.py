"""Governed finance reviewer appointment and end-to-end tests."""

from io import BytesIO
from threading import Barrier, Thread

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from unittest.mock import patch

from PIL import Image

from core.application_services import submit_member_application
from core.authorization_services import AuthorizationService
from core.deliberator_exam_services import start_deliberator_exam, submit_deliberator_exam
from core.exceptions import DomainError
from core.finance_role_services import (
    execute_finance_reviewer_appointment,
    nominate_finance_reviewer,
    vote_on_finance_reviewer_appointment,
)
from core.finance_services import review_expense_claim, submit_expense_claim
from core.finance_setup import (
    FINANCE_PAY_PERMISSION,
    FINANCE_PUBLISH_PUBLIC_ATTACHMENTS_PERMISSION,
    FINANCE_REVIEW_PERMISSION,
    FINANCE_VIEW_PRIVATE_PERMISSION,
)
from core.governance_setup import ensure_maintainer_role
from core.member_roles import ROLE_COVENANTER, ROLE_DELIBERATOR, ensure_catalog_role, member_has_role
from core.models import (
    DeliberatorExamPolicy,
    DeliberatorExamQuestion,
    ExpenseClaim,
    Member,
    Proposal,
    ProposalVote,
    SystemEvent,
)
from core.proposals.execution import execute_proposal
from core.proposals.lifecycle import create_role_appointment_proposal
from core.proposals.voting import cast_proposal_vote
from core.role_assignment_services import create_role_assignment
from core.tests.helpers import create_member


def _png_upload():
    buffer = BytesIO()
    Image.new("RGB", (4, 4), "white").save(buffer, format="PNG")
    return SimpleUploadedFile("receipt.png", buffer.getvalue(), content_type="image/png")


class FinanceReviewerAppointmentTests(TestCase):
    def setUp(self):
        self.manager = create_member("finance-role-manager", role_name=ROLE_COVENANTER)
        create_role_assignment(member=self.manager, role=ensure_maintainer_role()["role"])
        create_role_assignment(member=self.manager, role=ensure_catalog_role(ROLE_DELIBERATOR))
        self.target = create_member("finance-role-target", role_name=ROLE_COVENANTER)
        self.outsider = create_member("finance-role-outsider", role_name=ROLE_COVENANTER)

    def test_nominate_vote_execute_grants_only_review_capabilities(self):
        proposal = nominate_finance_reviewer(actor=self.manager, target_member=self.target, reason="承担审核")
        self.assertEqual(proposal.status, Proposal.Status.VOTING)
        self.assertFalse(AuthorizationService().member_has_permission(self.target, FINANCE_REVIEW_PERMISSION))

        vote_on_finance_reviewer_appointment(
            actor=self.manager, proposal=proposal, choice=ProposalVote.Choice.YES,
        )
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.Status.PASSED)
        execution = execute_finance_reviewer_appointment(actor=self.manager, proposal=proposal)

        self.assertEqual(execution.status, execution.Status.SUCCEEDED)
        auth = AuthorizationService()
        self.assertTrue(auth.member_has_permission(self.target, FINANCE_REVIEW_PERMISSION))
        self.assertTrue(auth.member_has_permission(self.target, FINANCE_VIEW_PRIVATE_PERMISSION))
        self.assertFalse(auth.member_has_permission(self.target, FINANCE_PAY_PERMISSION))
        self.assertFalse(auth.member_has_permission(self.target, FINANCE_PUBLISH_PUBLIC_ATTACHMENTS_PERMISSION))

    def test_unauthorized_invalid_target_duplicate_and_wrong_proposal_fail_closed(self):
        with self.assertRaises(DomainError):
            nominate_finance_reviewer(actor=self.outsider, target_member=self.target)
        contributor = create_member("finance-role-contributor")
        with self.assertRaises(DomainError):
            nominate_finance_reviewer(actor=self.manager, target_member=contributor)
        proposal = nominate_finance_reviewer(actor=self.manager, target_member=self.target)
        with self.assertRaises(DomainError):
            nominate_finance_reviewer(actor=self.manager, target_member=self.target)
        with self.assertRaises(DomainError):
            execute_finance_reviewer_appointment(actor=self.manager, proposal=proposal)
        wrong = create_role_appointment_proposal(
            target_member=self.target,
            target_role=ensure_maintainer_role()["role"],
            proposer_member=self.manager,
        )
        with self.assertRaises(DomainError):
            execute_finance_reviewer_appointment(actor=self.manager, proposal=wrong)

    def test_non_deliberator_manager_cannot_vote(self):
        manager_only = create_member("finance-manager-only", role_name=ROLE_COVENANTER)
        create_role_assignment(member=manager_only, role=ensure_maintainer_role()["role"])
        proposal = nominate_finance_reviewer(actor=manager_only, target_member=self.target)
        with self.assertRaises(DomainError):
            vote_on_finance_reviewer_appointment(
                actor=manager_only, proposal=proposal, choice=ProposalVote.Choice.YES,
            )

    def test_vote_event_failure_rolls_back_vote_and_proposal_state(self):
        proposal = nominate_finance_reviewer(actor=self.manager, target_member=self.target)

        with patch("core.proposals.voting.append_event", side_effect=RuntimeError("event failed")):
            with self.assertRaisesRegex(RuntimeError, "event failed"):
                vote_on_finance_reviewer_appointment(
                    actor=self.manager,
                    proposal=proposal,
                    choice=ProposalVote.Choice.YES,
                )

        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.Status.VOTING)
        self.assertFalse(ProposalVote.objects.filter(proposal=proposal).exists())

    def test_vote_status_failure_rolls_back_vote_and_vote_event(self):
        proposal = nominate_finance_reviewer(actor=self.manager, target_member=self.target)
        vote_events_before = SystemEvent.objects.filter(
            event_type=SystemEvent.EventType.PROPOSAL_VOTE_CAST,
        ).count()

        with patch(
            "core.proposals.voting.evaluate_proposal",
            side_effect=[proposal, RuntimeError("status failed")],
        ):
            with self.assertRaisesRegex(RuntimeError, "status failed"):
                vote_on_finance_reviewer_appointment(
                    actor=self.manager,
                    proposal=proposal,
                    choice=ProposalVote.Choice.YES,
                )

        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.Status.VOTING)
        self.assertFalse(ProposalVote.objects.filter(proposal=proposal).exists())
        self.assertEqual(
            SystemEvent.objects.filter(event_type=SystemEvent.EventType.PROPOSAL_VOTE_CAST).count(),
            vote_events_before,
        )


class FinanceReviewerAppointmentConcurrencyTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_nominations_create_only_one_open_proposal(self):
        manager = create_member("finance-concurrent-manager", role_name=ROLE_COVENANTER)
        create_role_assignment(member=manager, role=ensure_maintainer_role()["role"])
        target = create_member("finance-concurrent-target", role_name=ROLE_COVENANTER)
        barrier = Barrier(2)
        outcomes = []

        def nominate():
            close_old_connections()
            barrier.wait()
            try:
                nominate_finance_reviewer(
                    actor=Member.objects.get(pk=manager.pk),
                    target_member=Member.objects.get(pk=target.pk),
                )
            except DomainError:
                outcomes.append("duplicate")
            else:
                outcomes.append("created")
            finally:
                close_old_connections()

        threads = [Thread(target=nominate), Thread(target=nominate)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(sorted(outcomes), ["created", "duplicate"])
        self.assertEqual(
            Proposal.objects.filter(
                proposal_type=Proposal.ProposalType.ROLE_APPOINTMENT,
                status__in=(Proposal.Status.DRAFT, Proposal.Status.VOTING, Proposal.Status.PASSED),
            ).count(),
            1,
        )


class FinanceReviewerEndToEndTests(TestCase):
    def setUp(self):
        DeliberatorExamQuestion.objects.all().delete()
        DeliberatorExamPolicy.objects.all().delete()
        DeliberatorExamPolicy.objects.create(version=1, question_count=1, passing_percent=100, status="active")
        DeliberatorExamQuestion.objects.create(
            question_id="finance-e2e", version=1, prompt="谁能参与治理表决？",
            options_json=[{"id": "a", "text": "合格执衡者"}, {"id": "b", "text": "任何账号"}],
            correct_option_id="a", status="published",
        )
        self.bootstrap = create_member("finance-e2e-bootstrap", role_name=ROLE_COVENANTER)
        create_role_assignment(member=self.bootstrap, role=ensure_maintainer_role()["role"])

    def test_exam_admission_finance_appointment_and_expense_review(self):
        attempt = start_deliberator_exam(member=self.bootstrap)
        submit_deliberator_exam(member=self.bootstrap, attempt=attempt, answers={"q1": "a"})
        self.assertTrue(member_has_role(self.bootstrap, ROLE_DELIBERATOR))

        application = submit_member_application(
            applicant_name="新财务负责人", contact="finance-new@example.test", motivation="承担财务审核",
            role_gap="ai_engineer", requested_member_no="finance-e2e-new",
        )
        cast_proposal_vote(
            proposal=application.admission_proposal,
            voter_member=self.bootstrap,
            choice=ProposalVote.Choice.YES,
        )
        application.admission_proposal.refresh_from_db()
        execute_proposal(proposal=application.admission_proposal, executor_member=self.bootstrap)
        application.refresh_from_db()
        reviewer = application.linked_member
        self.assertTrue(member_has_role(reviewer, ROLE_COVENANTER))
        self.assertFalse(AuthorizationService().member_has_permission(reviewer, FINANCE_REVIEW_PERMISSION))

        appointment = nominate_finance_reviewer(
            actor=self.bootstrap, target_member=reviewer, reason="负责仿真财务审核",
        )
        vote_on_finance_reviewer_appointment(
            actor=self.bootstrap, proposal=appointment, choice=ProposalVote.Choice.YES,
        )
        appointment.refresh_from_db()
        execute_finance_reviewer_appointment(actor=self.bootstrap, proposal=appointment)

        claimant = create_member("finance-e2e-claimant", role_name=ROLE_COVENANTER)
        claim = submit_expense_claim(
            claimant_member=claimant,
            title="仿真采购报销",
            description="带消费凭证的测试报销",
            amount=128,
            expense_date="2026-08-04",
            evidence_uploads=[_png_upload()],
            require_evidence=True,
            world_id="simulation0001",
        )
        review_expense_claim(claim=claim, reviewer_member=reviewer, decision="approved")
        claim.refresh_from_db()
        self.assertEqual(claim.status, ExpenseClaim.Status.APPROVED)
        self.assertEqual(claim.reviews.get().reviewer_member, reviewer)

        own_claim = submit_expense_claim(
            claimant_member=reviewer, title="本人报销", description="", amount=1,
            expense_date="2026-08-04",
        )
        with self.assertRaises(DomainError):
            review_expense_claim(claim=own_claim, reviewer_member=reviewer, decision="approved")
