from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from core.application_services import submit_member_application
from core.exceptions import DomainError
from core.models import MemberApplication, PartnerApplication, Proposal, SystemEvent
from core.models import Member
from core.tests.helpers import create_governance_admin_member, create_member, login_as_member
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


def member_application_post_data(
    *,
    username: str,
    applicant_name: str,
    contact: str,
    motivation: str,
    password: str = "test-password-123",
    role_gap: str = "developer_ai_engineer",
    availability_slots: list[str] | None = None,
    motivation_reasons: list[str] | None = None,
    capabilities_text: str | None = None,
) -> dict[str, object]:
    data: dict[str, object] = {
        "username": username,
        "password1": password,
        "password2": password,
        "applicant_name": applicant_name,
        "contact": contact,
        "role_gap": role_gap,
        "availability_slots": availability_slots or ["off_hours", "weekend"],
        "motivation_reasons": motivation_reasons or ["other"],
        "motivation_other_text": motivation,
        "confirm_submit": "on",
    }
    if capabilities_text is not None:
        data["capabilities_text"] = capabilities_text
    return data


class PublicApplicationPageTests(TestCase):
    def test_member_application_page_submits_real_form_and_writes_event(self) -> None:
        response = self.client.get("/apply/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'name="password1"')
        self.assertContains(response, 'name="applicant_name"')
        self.assertContains(response, 'name="motivation_reasons"')
        self.assertContains(response, "联系方式（建议留微信或电话）")
        self.assertNotContains(response, "能力自述")
        self.assertNotContains(response, "我能出具责任文件")

        response = self.client.post(
            "/apply/",
            {
                **member_application_post_data(
                    username="applicant-a",
                    applicant_name="报名者 A",
                    contact="applicant-a@example.test",
                    motivation="想参加真实社区建设。",
                ),
                "availability_hours_per_week": "12",
                "external_ref": "test-member-application",
                "simulation_run_id": "forged-run-id",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        application = MemberApplication.objects.get(applicant_name="报名者 A")
        self.assertEqual(application.applicant_name, "报名者 A")
        self.assertEqual(application.capability_scores, {})
        self.assertFalse(application.can_issue_responsibility_documents)
        self.assertEqual(application.document_authority_domains, [])
        self.assertEqual(application.status, MemberApplication.Status.ADMISSION_VOTING)
        self.assertEqual(application.requested_member_no, "applicant-a")
        self.assertEqual(application.account_user.username, "applicant-a")
        self.assertEqual(application.linked_member.member_no, "applicant-a")
        self.assertEqual(application.linked_member.status, Member.Status.PENDING_REVIEW)
        self.assertEqual(application.role_gap, "developer_ai_engineer")
        self.assertEqual(application.availability_slots, ["off_hours", "weekend"])
        self.assertEqual(application.dynamic_answers[0]["key"], "motivation_reasons")
        self.assertIn("想参加真实社区建设。", application.motivation)
        self.assertIsNotNone(application.frozen_at)
        self.assertEqual(application.metadata, {"source": "public_form"})
        self.assertTrue(get_user_model().objects.get(username="applicant-a").check_password("test-password-123"))
        self.assertContains(response, "报名工作台")
        self.assertTrue(
            SystemEvent.objects.filter(
                event_type=SystemEvent.EventType.MEMBER_APPLICATION_SUBMITTED,
                aggregate_id=application.application_id,
            ).exists()
        )

    def test_member_application_auto_creates_proposal_and_binds_account(self) -> None:
        application = self.client.post(
            "/apply/",
            member_application_post_data(
                username="candidate-a",
                applicant_name="候选成员 A",
                contact="candidate-a@example.test",
                motivation="愿意参加。",
            ),
        )
        self.assertEqual(application.status_code, 302)
        member_application = MemberApplication.objects.get(requested_member_no="candidate-a")
        # After auto-proposal creation, status is ADMISSION_VOTING.
        self.assertEqual(member_application.status, MemberApplication.Status.ADMISSION_VOTING)
        self.assertIsNotNone(member_application.admission_proposal_id)
        self.assertEqual(
            member_application.admission_proposal.proposal_type,
            Proposal.ProposalType.MEMBER_ADMISSION,
        )

        member = member_application.linked_member
        self.assertEqual(member.member_no, "candidate-a")
        self.assertEqual(member.status, Member.Status.PENDING_REVIEW)
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
                role_gap="developer_ai_engineer",
                availability_slots=["off_hours"],
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
                role_gap="developer_ai_engineer",
                availability_slots=["weekend"],
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

    def test_member_application_rejects_conflicting_availability_slots(self) -> None:
        response = self.client.post(
            "/apply/",
            member_application_post_data(
                username="slot-conflict",
                applicant_name="时段冲突",
                contact="slot-conflict@example.test",
                motivation="验证时段冲突。",
                availability_slots=["any_time", "weekend"],
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "全天可用")
        self.assertFalse(MemberApplication.objects.filter(requested_member_no="slot-conflict").exists())

    def test_rejected_applicant_can_reapply_with_same_account_and_member(self) -> None:
        self.client.post(
            "/apply/",
            member_application_post_data(
                username="reapply-a",
                applicant_name="再次申请者",
                contact="reapply-a@example.test",
                motivation="第一次申请。",
            ),
        )
        first_application = MemberApplication.objects.get(requested_member_no="reapply-a")
        # Reject by having the auto-created proposal fail (expire past deadline).
        proposal = first_application.admission_proposal
        past_time = timezone.now() - timezone.timedelta(hours=2)
        proposal.start_at = past_time
        proposal.deadline_at = past_time + timezone.timedelta(hours=1)
        proposal.save(update_fields=["start_at", "deadline_at"])
        from core.proposals.voting import evaluate_proposal
        evaluate_proposal(proposal)
        first_application.refresh_from_db()
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.Status.FAILED)
        self.assertEqual(first_application.status, MemberApplication.Status.REJECTED)
        member = first_application.linked_member
        member.refresh_from_db()
        self.assertEqual(member.status, Member.Status.APPLICATION_REJECTED)

        self.client.force_login(first_application.account_user)
        response = self.client.post(
            "/apply/",
            {
                **member_application_post_data(
                    username="reapply-a",
                    applicant_name="再次申请者",
                    contact="reapply-a@example.test",
                    motivation="第二次申请。",
                    role_gap="service_resident",
                    availability_slots=["weekend"],
                ),
                "password1": "",
                "password2": "",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        applications = list(MemberApplication.objects.filter(requested_member_no="reapply-a").order_by("submitted_at"))
        self.assertEqual(len(applications), 2)
        self.assertEqual(applications[-1].linked_member, member)
        member.refresh_from_db()
        self.assertEqual(member.status, Member.Status.PENDING_REVIEW)
        self.assertContains(response, "报名工作台")

    def test_review_member_application_no_longer_importable(self) -> None:
        """The old review_member_application service has been removed."""
        with self.assertRaises(ImportError):
            from core.application_services import review_member_application  # noqa: F811

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
                **member_application_post_data(
                    username="host-test-member",
                    applicant_name="Host 测试报名者",
                    contact="host-test@example.test",
                    motivation="验证仿真表单 driver 使用允许的 Host。",
                    capabilities_text="文档:70",
                ),
                "availability_hours_per_week": "8",
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
                **member_application_post_data(
                    username="rooted-path-member",
                    applicant_name="Rooted Path Applicant",
                    contact="rooted-path@example.test",
                    motivation="Verify rooted simulation application path.",
                    capabilities_text="Documentation:70",
                ),
                "availability_hours_per_week": "8",
                "requested_member_no": "rooted-path-member",
            },
        )

        self.assertTrue(result.success, result.errors)
        self.assertEqual(result.path, "/apply/")
        self.assertEqual(driver.host, "bigsim.local")
        self.assertTrue(MemberApplication.objects.filter(metadata__external_ref="rooted-path-member-application").exists())
