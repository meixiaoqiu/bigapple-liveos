from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from core.application_services import review_member_application, submit_member_application
from core.exceptions import DomainError
from core.models import MemberApplication, PartnerApplication, SystemEvent
from core.models import Member
from core.tests.helpers import create_member, login_as_member
from simulation.form_drivers import HttpFormDriver


FIXED_SIM_SETTINGS = {
    "ROOT_URLCONF": "live_os.urls_sim",
    "SITE_ROLE": "simulation",
    "SITE_FIXED_WORLD": True,
    "SITE_WORLD_ID": "simulation0001",
    "SITE_WORLD_TYPE": "simulation",
    "SITE_WORLD_DATABASE_ALIAS": "default",
    "SITE_WORLD_DATABASE_NAME": "test",
    "WORLD_DATABASE_ROUTING_ENABLED": False,
    "DEFAULT_WORLD_DATABASE_ALIAS": "default",
    "DATABASE_ROUTERS": [],
}


class PublicApplicationPageTests(TestCase):
    def test_member_application_page_submits_real_form_and_writes_event(self) -> None:
        response = self.client.get("/apply/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'name="password1"')
        self.assertContains(response, 'name="applicant_name"')
        self.assertContains(response, 'name="capabilities_text"')

        response = self.client.post(
            "/apply/",
            {
                "username": "applicant-a",
                "password1": "test-password-123",
                "password2": "test-password-123",
                "applicant_name": "报名者 A",
                "contact": "applicant-a@example.test",
                "motivation": "想参加真实社区建设。",
                "availability_hours_per_week": "12",
                "capabilities_text": "做饭:80\n视频剪辑:70",
                "external_ref": "test-member-application",
                "simulation_run_id": "forged-run-id",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        application = MemberApplication.objects.get(applicant_name="报名者 A")
        self.assertEqual(application.applicant_name, "报名者 A")
        self.assertEqual(application.capability_scores["做饭"], 80)
        self.assertEqual(application.status, MemberApplication.Status.SUBMITTED)
        self.assertEqual(application.requested_member_no, "applicant-a")
        self.assertEqual(application.account_user.username, "applicant-a")
        self.assertEqual(application.metadata, {"source": "public_form"})
        self.assertTrue(get_user_model().objects.get(username="applicant-a").check_password("test-password-123"))
        self.assertContains(response, "报名已提交")
        self.assertTrue(
            SystemEvent.objects.filter(
                event_type=SystemEvent.EventType.MEMBER_APPLICATION_SUBMITTED,
                aggregate_id=application.application_id,
            ).exists()
        )

    def test_member_application_review_binds_registered_account_to_candidate_member(self) -> None:
        application = self.client.post(
            "/apply/",
            {
                "username": "candidate-a",
                "password1": "test-password-123",
                "password2": "test-password-123",
                "applicant_name": "候选成员 A",
                "contact": "candidate-a@example.test",
                "motivation": "愿意参加。",
                "availability_hours_per_week": "10",
                "capabilities_text": "整理:70",
            },
        )
        self.assertEqual(application.status_code, 302)
        member_application = MemberApplication.objects.get(requested_member_no="candidate-a")

        review_member_application(
            application=member_application,
            status=MemberApplication.Status.CANDIDATE,
            review_note="测试通过。",
        )

        member_application.refresh_from_db()
        member = member_application.linked_member
        self.assertEqual(member.member_no, "candidate-a")
        self.assertEqual(member.status, Member.Status.PENDING_TRAINING)
        self.assertEqual(member.user, member_application.account_user)

    def test_member_application_service_rejects_account_and_member_no_mismatch(self) -> None:
        with self.assertRaises(DomainError):
            submit_member_application(
                account_username="account-a",
                account_password="test-password-123",
                applicant_name="报名者 A",
                contact="applicant-a@example.test",
                motivation="想参加。",
                availability_hours_per_week=12,
                capability_scores={"整理": 70},
                requested_member_no="different-member-no",
            )

        self.assertFalse(get_user_model().objects.filter(username="account-a").exists())
        self.assertFalse(MemberApplication.objects.filter(applicant_name="报名者 A").exists())

    def test_member_application_service_rejects_existing_member_no(self) -> None:
        create_member(member_no="existing-member-no")

        with self.assertRaises(DomainError):
            submit_member_application(
                account_username="existing-member-no",
                account_password="test-password-123",
                applicant_name="报名者 B",
                contact="applicant-b@example.test",
                motivation="想参加。",
                availability_hours_per_week=12,
                capability_scores={"整理": 70},
            )

        self.assertFalse(get_user_model().objects.filter(username="existing-member-no").exists())

    def test_existing_member_sees_member_status_instead_of_application_form(self) -> None:
        member = create_member(member_no="mem-apply-existing", status=Member.Status.ACTIVE)
        login_as_member(self.client, member)

        response = self.client.get("/apply/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "你已经是成员")
        self.assertContains(response, "/workspace/")
        self.assertNotContains(response, 'name="password1"')

    def test_legacy_member_application_path_is_not_exposed(self) -> None:
        response = self.client.get("/apply/member/")

        self.assertEqual(response.status_code, 404)

    def test_partner_application_page_submits_real_form_and_writes_event(self) -> None:
        response = self.client.get("/apply/partner/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="organization_name"')
        self.assertContains(response, 'name="service_domains_text"')

        response = self.client.post(
            "/apply/partner/",
            {
                "organization_name": "结构检测机构 A",
                "contact_name": "联系人 A",
                "contact": "partner-a@example.test",
                "service_domains_text": "结构检测\n屋顶荷载复核",
                "can_issue_responsibility_documents": "on",
                "responsibility_document_domains_text": "structural_safety_document",
                "qualification_summary": "可出具结构安全评估报告。",
                "quote_summary": "按项目报价。",
                "service_area": "本地",
                "delivery_cycle_days": "10",
                "constraints": "需现场踏勘。",
                "external_ref": "test-partner-application",
                "simulation_run_id": "forged-run-id",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        application = PartnerApplication.objects.get(organization_name="结构检测机构 A")
        self.assertEqual(application.organization_name, "结构检测机构 A")
        self.assertIn("结构检测", application.service_domains)
        self.assertTrue(application.can_issue_responsibility_documents)
        self.assertEqual(application.metadata, {"source": "public_form"})
        self.assertTrue(
            SystemEvent.objects.filter(
                event_type=SystemEvent.EventType.PARTNER_APPLICATION_SUBMITTED,
                aggregate_id=application.application_id,
            ).exists()
        )

    @override_settings(ALLOWED_HOSTS=["big.local"])
    def test_http_form_driver_uses_allowed_host_instead_of_testserver(self) -> None:
        driver = HttpFormDriver()

        result = driver.submit_member_application(
            world_id="realworld",
            run_id="sim-run-host-test",
            simulation_hour=1,
            external_ref="host-test-member-application",
            data={
                "username": "host-test-member",
                "password1": "test-password-123",
                "password2": "test-password-123",
                "applicant_name": "Host 测试报名者",
                "contact": "host-test@example.test",
                "motivation": "验证仿真表单 driver 使用允许的 Host。",
                "availability_hours_per_week": "8",
                "capabilities_text": "文档:70",
                "requested_member_no": "host-test-member",
            },
        )

        self.assertTrue(result.success, result.errors)
        self.assertEqual(driver.host, "big.local")
        self.assertTrue(MemberApplication.objects.filter(metadata__external_ref="host-test-member-application").exists())

    @override_settings(ALLOWED_HOSTS=["bigsim.local"], **FIXED_SIM_SETTINGS)
    def test_http_form_driver_uses_rooted_simulation_application_path(self) -> None:
        driver = HttpFormDriver()

        result = driver.submit_member_application(
            world_id="simulation0001",
            run_id="sim-run-rooted-path-test",
            simulation_hour=1,
            external_ref="rooted-path-member-application",
            data={
                "username": "rooted-path-member",
                "password1": "test-password-123",
                "password2": "test-password-123",
                "applicant_name": "Rooted Path Applicant",
                "contact": "rooted-path@example.test",
                "motivation": "Verify rooted simulation application path.",
                "availability_hours_per_week": "8",
                "capabilities_text": "Documentation:70",
                "requested_member_no": "rooted-path-member",
            },
        )

        self.assertTrue(result.success, result.errors)
        self.assertEqual(result.path, "/apply/")
        self.assertEqual(driver.host, "bigsim.local")
        self.assertTrue(MemberApplication.objects.filter(metadata__external_ref="rooted-path-member-application").exists())
