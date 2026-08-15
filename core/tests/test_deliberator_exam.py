"""Deliberator qualification exam tests."""

from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.test import RequestFactory
from django.contrib import admin

from core.application_services import submit_member_application
from core.deliberation_services import apply_for_deliberator_term
from core.deliberator_exam_services import (
    create_exam_question,
    copy_exam_question_to_draft,
    deliberator_exam_readiness,
    ensure_simulation_exam_baseline,
    member_exam_view,
    publish_exam_policy,
    replace_exam_question,
    retire_exam_question,
    start_deliberator_exam,
    submit_deliberator_exam,
)
from core.exceptions import DomainError
from core.governance_setup import ensure_administrator_role
from core.member_roles import ROLE_COVENANTER, ROLE_DELIBERATOR, ensure_catalog_role, member_has_role
from core.models import DeliberatorExamAttempt, DeliberatorExamPolicy, DeliberatorExamQuestion, SystemEvent
from core.models import Proposal, ProposalVote
from core.proposals.execution import execute_proposal
from core.proposals.voting import cast_proposal_vote
from core.role_assignment_services import create_role_assignment
from core.tests.helpers import create_member
from core.tests.helpers import ensure_login_user_for_member
from core.admin_deliberator_exams import DeliberatorExamAttemptAdmin, DeliberatorExamQuestionAdmin
from worlds.models import WorldRegistry


class DeliberatorExamTests(TestCase):
    def setUp(self):
        self.member = create_member("exam-candidate", role_name=ROLE_COVENANTER)
        DeliberatorExamQuestion.objects.all().delete()
        DeliberatorExamPolicy.objects.all().delete()
        self.policy = DeliberatorExamPolicy.objects.create(
            version=1, question_count=1, passing_percent=100,
            status=DeliberatorExamPolicy.Status.ACTIVE,
        )
        self.question = DeliberatorExamQuestion.objects.create(
            question_id="governance-baseline", version=1,
            prompt="谁可以投票？",
            options_json=[{"id": "a", "text": "合格执衡者"}, {"id": "b", "text": "任何账号"}],
            correct_option_id="a", points=1,
            status=DeliberatorExamQuestion.Status.PUBLISHED,
        )

    def test_legacy_direct_application_is_closed(self):
        with self.assertRaisesRegex(DomainError, "资格考试"):
            apply_for_deliberator_term(member=self.member)
        self.assertFalse(member_has_role(self.member, ROLE_DELIBERATOR))

    def test_single_question_exam_passes_and_grants_one_year_term(self):
        attempt = start_deliberator_exam(member=self.member)
        public = member_exam_view(attempt)
        self.assertNotIn("correct_option_id", str(public))
        result = submit_deliberator_exam(
            member=self.member, attempt=attempt, answers={"q1": "a"},
        )
        self.assertEqual(result.status, DeliberatorExamAttempt.Status.PASSED)
        self.assertEqual(result.score, 1)
        self.assertIsNotNone(result.role_assignment_id)
        self.assertTrue(member_has_role(self.member, ROLE_DELIBERATOR))

    def test_failed_exam_is_audited_without_role(self):
        attempt = start_deliberator_exam(member=self.member)
        result = submit_deliberator_exam(
            member=self.member, attempt=attempt, answers={"q1": "b"},
        )
        self.assertEqual(result.status, DeliberatorExamAttempt.Status.FAILED)
        self.assertEqual(result.score, 0)
        self.assertFalse(member_has_role(self.member, ROLE_DELIBERATOR))

    def test_tampered_question_or_option_is_rejected(self):
        attempt = start_deliberator_exam(member=self.member)
        with self.assertRaises(DomainError):
            submit_deliberator_exam(member=self.member, attempt=attempt, answers={"other": "a"})
        with self.assertRaises(DomainError):
            submit_deliberator_exam(member=self.member, attempt=attempt, answers={"q1": "x"})
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, DeliberatorExamAttempt.Status.IN_PROGRESS)

    def test_non_covenanter_cannot_start(self):
        outsider = create_member("exam-outsider")
        with self.assertRaises(DomainError):
            start_deliberator_exam(member=outsider)

    def test_existing_deliberator_cannot_start(self):
        create_role_assignment(member=self.member, role=ensure_catalog_role(ROLE_DELIBERATOR))
        with self.assertRaises(DomainError):
            start_deliberator_exam(member=self.member)

    def test_only_exam_administrator_can_create_and_replace_question(self):
        with self.assertRaises(DomainError):
            create_exam_question(
                actor=self.member, prompt="题目", options=[{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
                correct_option_id="a", publish=True,
            )
        administrator = create_member("exam-administrator", role_name=ROLE_COVENANTER)
        create_role_assignment(member=administrator, role=ensure_administrator_role()["role"])
        created = create_exam_question(
            actor=administrator, prompt="新题", options=[{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
            correct_option_id="a", publish=True,
        )
        attempt = start_deliberator_exam(member=self.member, sampler=lambda items, count: [created])
        replacement = replace_exam_question(
            actor=administrator, question=created, prompt="新版题",
            options=[{"id": "a", "text": "A2"}, {"id": "b", "text": "B2"}], correct_option_id="b",
        )
        attempt.refresh_from_db()
        self.assertEqual(attempt.question_snapshot_json[0]["prompt"], "新题")
        self.assertEqual(replacement.version, 2)

    def test_published_question_is_edited_through_new_draft_version(self):
        administrator = create_member("exam-version-administrator", role_name=ROLE_COVENANTER)
        create_role_assignment(member=administrator, role=ensure_administrator_role()["role"])
        draft = copy_exam_question_to_draft(actor=administrator, question=self.question)
        self.assertEqual(draft.question_id, self.question.question_id)
        self.assertEqual(draft.version, 2)
        self.assertEqual(draft.status, DeliberatorExamQuestion.Status.DRAFT)
        self.question.refresh_from_db()
        self.assertEqual(self.question.status, DeliberatorExamQuestion.Status.PUBLISHED)

    def test_database_allows_only_one_active_policy(self):
        self.assertEqual(self.policy.active_slot, 1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            DeliberatorExamPolicy.objects.create(
                version=2,
                question_count=1,
                passing_percent=100,
                status=DeliberatorExamPolicy.Status.ACTIVE,
            )
        self.assertEqual(
            DeliberatorExamPolicy.objects.filter(status=DeliberatorExamPolicy.Status.ACTIVE).count(),
            1,
        )

    def test_policy_unique_conflict_is_a_domain_error_and_rolls_back(self):
        administrator = create_member("exam-policy-conflict-administrator", role_name=ROLE_COVENANTER)
        create_role_assignment(member=administrator, role=ensure_administrator_role()["role"])

        with patch.object(DeliberatorExamPolicy, "save", side_effect=IntegrityError("duplicate active")):
            with self.assertRaisesRegex(DomainError, "另一项考试政策同时生效"):
                publish_exam_policy(actor=administrator, question_count=1, passing_percent=100)

        self.policy.refresh_from_db()
        self.assertEqual(self.policy.status, DeliberatorExamPolicy.Status.ACTIVE)
        self.assertEqual(self.policy.active_slot, 1)

    def test_question_change_event_is_safe_and_question_can_be_retired(self):
        administrator = create_member("exam-event-administrator", role_name=ROLE_COVENANTER)
        create_role_assignment(member=administrator, role=ensure_administrator_role()["role"])
        secret_prompt = "仅应出现在私有题库中的题目"
        secret_explanation = "私有解析"
        created = create_exam_question(
            actor=administrator,
            prompt=secret_prompt,
            options=[{"id": "a", "text": "私有正确项"}, {"id": "b", "text": "私有错误项"}],
            correct_option_id="a",
            explanation=secret_explanation,
            publish=True,
        )

        retire_exam_question(actor=administrator, question=created)

        created.refresh_from_db()
        self.assertEqual(created.status, DeliberatorExamQuestion.Status.RETIRED)
        payloads = list(SystemEvent.objects.filter(
            event_type=SystemEvent.EventType.DELIBERATOR_EXAM_QUESTION_CHANGED,
            aggregate_id=f"{created.question_id}:v{created.version}",
        ).values_list("payload_json", flat=True))
        self.assertEqual(len(payloads), 2)
        serialized = str(payloads)
        self.assertNotIn(secret_prompt, serialized)
        self.assertNotIn(secret_explanation, serialized)
        self.assertNotIn("私有正确项", serialized)
        self.assertNotIn("correct_option_id", serialized)
        self.assertIn("question_version", serialized)
        self.assertIn("retired", serialized)

    def test_admin_uses_business_permission_and_attempts_are_immutable(self):
        factory = RequestFactory()
        technical = create_member("exam-technical", role_name=ROLE_COVENANTER)
        technical_user = ensure_login_user_for_member(technical, is_staff=True)
        technical_user.is_superuser = True
        technical_user.save(update_fields=("is_superuser",))
        request = factory.get("/admin/")
        request.user = technical_user
        question_admin = DeliberatorExamQuestionAdmin(DeliberatorExamQuestion, admin.site)
        self.assertFalse(question_admin.has_module_permission(request))

        administrator = create_member("exam-admin-administrator", role_name=ROLE_COVENANTER)
        create_role_assignment(member=administrator, role=ensure_administrator_role()["role"])
        request.user = ensure_login_user_for_member(administrator, is_staff=True)
        self.assertTrue(question_admin.has_module_permission(request))
        attempt_admin = DeliberatorExamAttemptAdmin(DeliberatorExamAttempt, admin.site)
        self.assertFalse(attempt_admin.has_add_permission(request))
        self.assertFalse(attempt_admin.has_change_permission(request))
        self.assertFalse(attempt_admin.has_delete_permission(request))

    def test_insufficient_question_bank_fails_without_attempt(self):
        self.policy.question_count = 2
        self.policy.save(update_fields=("question_count",))
        self.assertEqual(deliberator_exam_readiness().code, "insufficient_questions")
        with self.assertRaisesRegex(DomainError, "暂未开放"):
            start_deliberator_exam(member=self.member)
        self.assertFalse(DeliberatorExamAttempt.objects.exists())

    def test_readiness_distinguishes_missing_policy_and_ready(self):
        self.assertEqual(deliberator_exam_readiness().code, "ready")
        self.policy.delete()
        result = deliberator_exam_readiness()
        self.assertEqual(result.code, "no_active_policy")
        self.assertIsNone(result.required_question_count)

    def test_simulation_baseline_is_idempotent_and_real_is_rejected(self):
        DeliberatorExamPolicy.objects.all().delete()
        DeliberatorExamQuestion.objects.all().delete()
        first = ensure_simulation_exam_baseline(world_type=WorldRegistry.WorldType.SIMULATION)
        second = ensure_simulation_exam_baseline(world_type=WorldRegistry.WorldType.SIMULATION)
        self.assertTrue(first["created_question"])
        self.assertTrue(first["created_policy"])
        self.assertFalse(second["created_question"])
        self.assertFalse(second["created_policy"])
        self.assertEqual(DeliberatorExamQuestion.objects.count(), 1)
        self.assertEqual(DeliberatorExamPolicy.objects.count(), 1)
        with self.assertRaisesRegex(DomainError, "只能用于仿真世界"):
            ensure_simulation_exam_baseline(world_type=WorldRegistry.WorldType.REAL)

    def test_simulation_baseline_preserves_usable_configuration_and_history(self):
        attempt = start_deliberator_exam(member=self.member)
        original_policy_id = self.policy.pk
        original_question_id = self.question.pk
        result = ensure_simulation_exam_baseline(world_type=WorldRegistry.WorldType.SIMULATION)
        self.assertFalse(result["created_question"])
        self.assertFalse(result["created_policy"])
        self.assertTrue(DeliberatorExamPolicy.objects.filter(pk=original_policy_id, status="active").exists())
        self.assertTrue(DeliberatorExamQuestion.objects.filter(pk=original_question_id, status="published").exists())
        self.assertTrue(DeliberatorExamAttempt.objects.filter(pk=attempt.pk).exists())

    def test_qualification_loss_during_exam_is_retained_as_invalidated(self):
        attempt = start_deliberator_exam(member=self.member)
        assignment = self.member.role_assignments.get(role__name=ROLE_COVENANTER)
        assignment.status = assignment.Status.REVOKED
        assignment.save(update_fields=("status", "updated_at"))

        result = submit_deliberator_exam(member=self.member, attempt=attempt, answers={"q1": "a"})

        self.assertEqual(result.status, DeliberatorExamAttempt.Status.INVALIDATED)
        self.assertFalse(member_has_role(self.member, ROLE_DELIBERATOR))

    def test_disabled_login_during_exam_invalidates_attempt(self):
        user = ensure_login_user_for_member(self.member)
        attempt = start_deliberator_exam(member=self.member)
        user.is_active = False
        user.save(update_fields=("is_active",))

        result = submit_deliberator_exam(member=self.member, attempt=attempt, answers={"q1": "a"})

        self.assertEqual(result.status, DeliberatorExamAttempt.Status.INVALIDATED)
        self.assertFalse(member_has_role(self.member, ROLE_DELIBERATOR))

    def test_role_assignment_failure_rolls_back_exam_result(self):
        attempt = start_deliberator_exam(member=self.member)

        with patch("core.deliberator_exam_services.create_role_assignment", side_effect=DomainError("任命失败")):
            with self.assertRaisesRegex(DomainError, "任命失败"):
                submit_deliberator_exam(member=self.member, attempt=attempt, answers={"q1": "a"})

        attempt.refresh_from_db()
        self.assertEqual(attempt.status, DeliberatorExamAttempt.Status.IN_PROGRESS)
        self.assertIsNone(attempt.submitted_at)
        self.assertFalse(member_has_role(self.member, ROLE_DELIBERATOR))

    def test_two_started_attempts_create_only_one_active_term(self):
        first = start_deliberator_exam(member=self.member)
        second = start_deliberator_exam(member=self.member)

        first_result = submit_deliberator_exam(member=self.member, attempt=first, answers={"q1": "a"})
        second_result = submit_deliberator_exam(member=self.member, attempt=second, answers={"q1": "a"})

        self.assertEqual(first_result.status, DeliberatorExamAttempt.Status.PASSED)
        self.assertEqual(second_result.status, DeliberatorExamAttempt.Status.INVALIDATED)
        self.assertEqual(
            self.member.role_assignments.filter(role__name=ROLE_DELIBERATOR, status="active").count(),
            1,
        )

    def test_attempt_cannot_be_submitted_twice(self):
        attempt = start_deliberator_exam(member=self.member)
        submit_deliberator_exam(member=self.member, attempt=attempt, answers={"q1": "a"})

        with self.assertRaisesRegex(DomainError, "不能重复评分"):
            submit_deliberator_exam(member=self.member, attempt=attempt, answers={"q1": "a"})

        self.assertEqual(
            self.member.role_assignments.filter(role__name=ROLE_DELIBERATOR, status="active").count(),
            1,
        )

    def test_first_exam_pass_unlocks_member_admission_without_granting_finance(self):
        attempt = start_deliberator_exam(member=self.member)
        submit_deliberator_exam(member=self.member, attempt=attempt, answers={"q1": "a"})
        application = submit_member_application(
            applicant_name="新申请人",
            contact="new@example.test",
            motivation="参与社区",
            role_gap="ai_engineer",
            requested_member_no="new-covenanter",
        )

        proposal = application.admission_proposal
        self.assertEqual(proposal.status, Proposal.Status.VOTING)
        cast_proposal_vote(proposal=proposal, voter_member=self.member, choice=ProposalVote.Choice.YES)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.Status.PASSED)
        execute_proposal(proposal=proposal, executor_member=self.member)

        application.refresh_from_db()
        admitted = application.linked_member
        self.assertTrue(member_has_role(admitted, ROLE_COVENANTER))
        self.assertFalse(admitted.role_assignments.filter(role__role_permissions__permission__code="finance.review").exists())

    def test_first_exam_reopens_application_created_with_zero_electorate(self):
        application = submit_member_application(
            applicant_name="先报名者",
            contact="before-exam@example.test",
            motivation="在首位执衡者产生前报名",
            role_gap="ai_engineer",
            requested_member_no="before-exam-applicant",
        )
        old_proposal_id = application.admission_proposal_id
        self.assertEqual(application.admission_proposal.eligible_voters_snapshot_json, [])

        attempt = start_deliberator_exam(member=self.member)
        submit_deliberator_exam(member=self.member, attempt=attempt, answers={"q1": "a"})

        application.refresh_from_db()
        self.assertNotEqual(application.admission_proposal_id, old_proposal_id)
        self.assertEqual(application.admission_proposal.eligible_voters_snapshot_json, [self.member.pk])
        self.assertEqual(Proposal.objects.get(pk=old_proposal_id).status, Proposal.Status.CANCELLED)
