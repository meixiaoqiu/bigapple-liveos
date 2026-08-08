from __future__ import annotations

from datetime import datetime, timedelta

from django.test import TestCase
from django.utils import timezone

from core.deliberation_services import apply_for_deliberator_term, deliberator_term_end_at
from core.deliberator_exam_services import start_deliberator_exam, submit_deliberator_exam
from core.exceptions import DomainError
from core.member_roles import (
    ROLE_DELIBERATOR,
    ROLE_COVENANTER,
    ROLE_MAINTAINER,
    ensure_catalog_role,
    member_has_role,
)
from core.models import DeliberatorExamPolicy, DeliberatorExamQuestion, Member, RoleAssignment
from core.role_assignment_services import bootstrap_initial_maintainer, create_role_assignment


class DeliberationServiceTests(TestCase):
    def setUp(self):
        DeliberatorExamQuestion.objects.all().delete()
        DeliberatorExamPolicy.objects.all().delete()
        DeliberatorExamPolicy.objects.create(version=1, question_count=1, passing_percent=100, status="active")
        DeliberatorExamQuestion.objects.create(
            question_id="deliberation-test", version=1, prompt="规则题",
            options_json=[{"id": "a", "text": "正确"}, {"id": "b", "text": "错误"}],
            correct_option_id="a", status="published",
        )

    def create_member(self, member_no: str) -> Member:
        return Member.objects.create(
            member_no=member_no,
            status=Member.Status.ACTIVE,
            credit_floor=-100,
            created_at=timezone.now(),
        )

    def admit_covenanter(self, member: Member, *, start_at=None) -> None:
        create_role_assignment(
            member=member,
            role=ensure_catalog_role(ROLE_COVENANTER),
            start_at=start_at,
        )

    def pass_exam(self, member: Member, *, at_time=None):
        attempt = start_deliberator_exam(member=member)
        return submit_deliberator_exam(member=member, attempt=attempt, answers={"q1": "a"}, at_time=at_time).role_assignment

    def test_direct_application_is_rejected(self):
        member = self.create_member("deliberation-non-covenanter")

        with self.assertRaisesRegex(DomainError, "资格考试"):
            apply_for_deliberator_term(member=member)

    def test_covenanter_self_application_creates_immediate_one_year_term(self):
        member = self.create_member("deliberation-one-year")
        self.admit_covenanter(member)
        starts_at = timezone.now()

        assignment = self.pass_exam(member, at_time=starts_at)

        self.assertEqual(assignment.source_type, RoleAssignment.SourceType.SELF_APPLICATION)
        self.assertEqual(assignment.role.name, ROLE_DELIBERATOR)
        self.assertEqual(assignment.start_at, starts_at)
        self.assertEqual(assignment.end_at, deliberator_term_end_at(starts_at))
        self.assertTrue(member_has_role(member, ROLE_DELIBERATOR, checked_at=starts_at))

    def test_active_deliberator_term_cannot_be_reapplied_for(self):
        member = self.create_member("deliberation-no-overlap")
        self.admit_covenanter(member)
        self.pass_exam(member)

        with self.assertRaisesRegex(DomainError, "不能重复申请"):
            start_deliberator_exam(member=member)

    def test_expired_term_is_retained_and_reapplication_creates_new_term(self):
        member = self.create_member("deliberation-reapply")
        covenanter_start = timezone.now() - timedelta(days=400)
        self.admit_covenanter(member, start_at=covenanter_start)
        first = self.pass_exam(member, at_time=timezone.now() - timedelta(days=367))

        second = self.pass_exam(member)

        first.refresh_from_db()
        self.assertEqual(first.status, RoleAssignment.Status.EXPIRED)
        self.assertNotEqual(first.pk, second.pk)
        self.assertGreater(second.end_at, timezone.now())
        self.assertTrue(member_has_role(member, ROLE_DELIBERATOR))

    def test_leap_day_term_ends_on_following_february_twenty_eighth(self):
        starts_at = timezone.make_aware(datetime(2024, 2, 29, 12, 0, 0))

        self.assertEqual(deliberator_term_end_at(starts_at), timezone.make_aware(datetime(2025, 2, 28, 12, 0, 0)))

    def test_bootstrap_maintainer_does_not_create_deliberator_term(self):
        member = self.create_member("deliberation-maintainer")

        bootstrap_initial_maintainer(member)

        self.assertTrue(member_has_role(member, ROLE_MAINTAINER))
        self.assertFalse(member_has_role(member, ROLE_DELIBERATOR))
