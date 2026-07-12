from __future__ import annotations

from django.test import TestCase, override_settings

from core.models import MemberApplication, PartnerApplication, SystemEvent
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
        response = self.client.get("/apply/member/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="applicant_name"')
        self.assertContains(response, 'name="capabilities_text"')

        response = self.client.post(
            "/apply/member/",
            {
                "applicant_name": "报名者 A",
                "contact": "applicant-a@example.test",
                "motivation": "想参加真实社区建设。",
                "availability_hours_per_week": "12",
                "capabilities_text": "做饭:80\n视频剪辑:70",
                "requested_member_no": "applicant-a",
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
        self.assertEqual(application.metadata, {"source": "public_form"})
        self.assertTrue(
            SystemEvent.objects.filter(
                event_type=SystemEvent.EventType.MEMBER_APPLICATION_SUBMITTED,
                aggregate_id=application.application_id,
            ).exists()
        )

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
                "applicant_name": "Rooted Path Applicant",
                "contact": "rooted-path@example.test",
                "motivation": "Verify rooted simulation application path.",
                "availability_hours_per_week": "8",
                "capabilities_text": "Documentation:70",
                "requested_member_no": "rooted-path-member",
            },
        )

        self.assertTrue(result.success, result.errors)
        self.assertEqual(result.path, "/apply/member/")
        self.assertEqual(driver.host, "bigsim.local")
        self.assertTrue(MemberApplication.objects.filter(metadata__external_ref="rooted-path-member-application").exists())
