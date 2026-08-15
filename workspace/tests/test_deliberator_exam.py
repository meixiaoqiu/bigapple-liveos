"""Workspace tests for deliberator qualification exams."""

from django.test import TestCase, override_settings

from core.member_roles import ROLE_COVENANTER, ROLE_DELIBERATOR, member_has_role
from core.models import DeliberatorExamPolicy, DeliberatorExamQuestion
from core.tests.helpers import create_administrator_member, create_member, login_as_member


@override_settings(
    SITE_FIXED_WORLD=True, SITE_WORLD_ID="realworld", SITE_WORLD_DATABASE_ALIAS="default",
    SITE_WORLD_DATABASE_NAME="test", SITE_WORLD_TYPE="real",
)
class DeliberatorExamWorkspaceTests(TestCase):
    def setUp(self):
        DeliberatorExamQuestion.objects.all().delete()
        DeliberatorExamPolicy.objects.all().delete()
        DeliberatorExamPolicy.objects.create(
            version=1, question_count=1, passing_percent=100, status="active",
        )
        DeliberatorExamQuestion.objects.create(
            question_id="workspace-exam", version=1, prompt="谁可以审核守约者申请？",
            options_json=[{"id": "a", "text": "合格执衡者"}, {"id": "b", "text": "任何账号"}],
            correct_option_id="a", status="published",
        )
        self.member = create_member("workspace-exam-member", role_name=ROLE_COVENANTER)
        login_as_member(self.client, self.member)

    def test_workspace_exposes_exam_entry(self):
        response = self.client.get("/workspace/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "申请执衡者")

    def test_correct_answer_grants_deliberator_without_leaking_answer(self):
        response = self.client.post("/workspace/deliberator-exam/")
        self.assertEqual(response.status_code, 302)
        attempt = self.member.deliberator_exam_attempts.get()
        page = self.client.get(response.url)
        self.assertContains(page, "谁可以审核守约者申请")
        self.assertNotContains(page, "correct_option_id")
        result = self.client.post(response.url, {"answer_q1": "a", "score": "999", "status": "passed"})
        self.assertEqual(result.status_code, 302)
        self.assertTrue(member_has_role(self.member, ROLE_DELIBERATOR))
        attempt.refresh_from_db()
        self.assertEqual(attempt.score, 1)

    def test_wrong_answer_does_not_grant_role_and_can_retry(self):
        start = self.client.post("/workspace/deliberator-exam/")
        result = self.client.post(start.url, {"answer_q1": "b"})
        self.assertEqual(result.status_code, 302)
        self.assertFalse(member_has_role(self.member, ROLE_DELIBERATOR))
        retry = self.client.post("/workspace/deliberator-exam/")
        self.assertEqual(retry.status_code, 302)
        self.assertEqual(self.member.deliberator_exam_attempts.count(), 2)

    def test_other_member_attempt_is_not_visible(self):
        start = self.client.post("/workspace/deliberator-exam/")
        other = create_member("workspace-exam-other", role_name=ROLE_COVENANTER)
        login_as_member(self.client, other)
        response = self.client.get(start.url)
        self.assertEqual(response.status_code, 404)

    def test_contributor_cannot_enter_full_workspace_exam(self):
        contributor = create_member("workspace-exam-contributor")
        login_as_member(self.client, contributor)
        response = self.client.get("/workspace/deliberator-exam/")
        self.assertEqual(response.status_code, 403)

    def test_anonymous_cannot_enter_exam(self):
        self.client.logout()
        response = self.client.get("/workspace/deliberator-exam/")
        self.assertIn(response.status_code, {302, 403})

    def test_suspended_member_cannot_enter_exam(self):
        self.member.status = self.member.Status.SUSPENDED
        self.member.save(update_fields=("status",))
        response = self.client.get("/workspace/deliberator-exam/")
        self.assertEqual(response.status_code, 403)

    def test_unavailable_exam_is_explained_and_cannot_create_attempt(self):
        DeliberatorExamPolicy.objects.all().delete()
        response = self.client.get("/workspace/deliberator-exam/")
        self.assertContains(response, "执衡者资格考试暂未开放，请稍后再试")
        self.assertContains(response, "disabled")
        response = self.client.post("/workspace/deliberator-exam/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.member.deliberator_exam_attempts.exists())

    def test_exam_configuration_requires_business_permission(self):
        response = self.client.get("/workspace/deliberator-exam/configuration/")
        self.assertEqual(response.status_code, 403)
        login_as_member(self.client, self.member, is_staff=True)
        user = self.member.user
        user.is_superuser = True
        user.save(update_fields=("is_superuser",))
        self.assertEqual(self.client.get("/workspace/deliberator-exam/configuration/").status_code, 403)

    def test_administrator_can_publish_question_and_policy_without_leaking_secrets(self):
        administrator = create_administrator_member("workspace-exam-administrator")
        login_as_member(self.client, administrator)
        response = self.client.post("/workspace/deliberator-exam/configuration/", {
            "action": "publish_question", "prompt": "私有题干", "option_a": "正确内容",
            "option_b": "错误内容", "correct_option_id": "a", "explanation": "私有解析",
        })
        self.assertEqual(response.status_code, 302)
        response = self.client.post("/workspace/deliberator-exam/configuration/", {
            "action": "publish_policy", "question_count": "1", "passing_percent": "80",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(DeliberatorExamPolicy.objects.filter(status="active").count(), 1)
        candidate_page = self.client.get("/workspace/deliberator-exam/")
        self.assertNotContains(candidate_page, "正确内容")
        self.assertNotContains(candidate_page, "私有解析")
        self.assertNotContains(candidate_page, "correct_option_id")
