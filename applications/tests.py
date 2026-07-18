from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from core.application_services import submit_member_application
from core.exceptions import DomainError
from core.identity_services import ensure_basic_member_for_user, register_participant_account
from core.member_roles import ROLE_BIG_APPLE_MEMBER, ROLE_FORMAL_MEMBER, member_has_role
from core.models import Event, MemberApplication, PartnerApplication, Proposal, SystemEvent
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
    """Member application flow: /register/ + authenticated /apply/."""

    def _register(self, username: str, password: str = "test-password-123", applicant_name: str = "") -> None:
        """Helper: POST /register/ to create account."""
        self.client.post(
            "/register/",
            {
                "username": username,
                "password1": password,
                "password2": password,
                "display_name": applicant_name or username,
                "contact": f"{username}@example.test",
            },
            follow=True,
        )

    def _apply_authenticated_post(self, username: str, applicant_name: str, contact: str,
                                   motivation: str, **overrides) -> object:
        """POST /apply/ as authenticated user (must have registered first)."""
        data = {
            "applicant_name": applicant_name,
            "contact": contact,
            "role_gap": overrides.get("role_gap", "developer_ai_engineer"),
            "availability_slots": overrides.get("availability_slots", ["off_hours", "weekend"]),
            "motivation_reasons": overrides.get("motivation_reasons", ["other"]),
            "motivation_other_text": motivation,
            "confirm_submit": "on",
        }
        return self.client.post("/apply/", data, follow=True)

    # ── /register/ tests ────────────────────────────────────────────────

    def test_get_register_shows_form(self) -> None:
        response = self.client.get("/register/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'name="password1"')
        self.assertContains(response, 'name="display_name"')

    def test_post_register_creates_user_member_role(self) -> None:
        event_count_before = Event.objects.count()
        response = self.client.post(
            "/register/",
            {
                "username": "reg-test-user",
                "password1": "test-pass-abc",
                "password2": "test-pass-abc",
                "display_name": "注册测试",
                "contact": "reg@example.test",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(get_user_model().objects.filter(username="reg-test-user").exists())
        member = Member.objects.get(member_no="reg-test-user")
        self.assertEqual(member.display_name, "注册测试")
        self.assertEqual(member.status, Member.Status.PENDING_REVIEW)
        self.assertEqual((member.metadata or {}).get("registration_contact"), "reg@example.test")
        self.assertEqual((member.metadata or {}).get("registration_source"), "public_register_form")
        self.assertTrue(member_has_role(member, ROLE_BIG_APPLE_MEMBER))
        # No MemberApplication created
        self.assertFalse(MemberApplication.objects.filter(linked_member=member).exists())
        # No public Event from registration
        self.assertEqual(Event.objects.count(), event_count_before)

    def test_authenticated_with_member_redirects_from_register(self) -> None:
        member = create_member(member_no="reg-redirect")
        login_as_member(self.client, member)
        response = self.client.get("/register/")
        self.assertEqual(response.status_code, 302)

    def test_authenticated_without_member_auto_creates_on_register(self) -> None:
        user = get_user_model().objects.create_user(username="reg-auto-mem", password="p")
        self.client.force_login(user)
        response = self.client.get("/register/", follow=True)
        self.assertEqual(response.status_code, 200)
        member = Member.objects.get(member_no="reg-auto-mem")
        self.assertTrue(member_has_role(member, ROLE_BIG_APPLE_MEMBER))

    # ── /apply/ unauthenticated → guide page ───────────────────────────

    def test_unauthenticated_get_apply_shows_guide_not_form(self) -> None:
        response = self.client.get("/apply/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "成员报名需要先注册账号")
        self.assertNotContains(response, 'name="applicant_name"')
        self.assertNotContains(response, 'name="username"')

    def test_unauthenticated_post_apply_redirects_to_login(self) -> None:
        data = member_application_post_data(
            username="no-reg-user",
            applicant_name="未注册报名",
            contact="no@example.test",
            motivation="不应成功。",
        )
        response = self.client.post("/apply/", data)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])
        self.assertIn("next=/apply/", response["Location"])
        self.assertFalse(MemberApplication.objects.filter(requested_member_no="no-reg-user").exists())
        self.assertFalse(get_user_model().objects.filter(username="no-reg-user").exists())

    # ── /apply/ authenticated flow ──────────────────────────────────────

    def test_authenticated_member_apply_form_no_account_fields(self) -> None:
        self._register("apply-auth", applicant_name="报名测试")
        response = self.client.get("/apply/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="username"')
        self.assertNotContains(response, 'name="password1"')
        self.assertContains(response, 'name="applicant_name"')
        self.assertContains(response, 'name="contact"')

    def test_authenticated_member_post_apply_creates_application(self) -> None:
        self._register("apply-post-user", applicant_name="POST 报名者")
        response = self._apply_authenticated_post(
            "apply-post-user", "POST 报名者", "post@example.test", "想参加测试。",
        )
        self.assertEqual(response.status_code, 200)
        app = MemberApplication.objects.filter(requested_member_no="apply-post-user").first()
        self.assertIsNotNone(app)
        self.assertEqual(app.applicant_name, "POST 报名者")
        self.assertEqual(app.status, MemberApplication.Status.ADMISSION_VOTING)
        self.assertTrue(
            SystemEvent.objects.filter(
                event_type=SystemEvent.EventType.MEMBER_APPLICATION_SUBMITTED,
                aggregate_id=app.application_id,
            ).exists()
        )

    def test_active_no_formal_role_can_post_apply_and_binds_member(self) -> None:
        self._register("act-no-role", applicant_name="角色测试")
        member = Member.objects.get(member_no="act-no-role")
        login_as_member(self.client, member)
        data = {
            **member_application_post_data(
                username="act-no-role",
                applicant_name="角色测试",
                contact="act@example.test",
                motivation="验证 ACTIVE 报名。",
            ),
            "password1": "",
            "password2": "",
        }
        response = self.client.post("/apply/", data, follow=True)
        self.assertEqual(response.status_code, 200)
        app = MemberApplication.objects.filter(linked_member=member).first()
        self.assertIsNotNone(app)
        member.refresh_from_db()
        self.assertEqual(member.status, Member.Status.PENDING_REVIEW)

    def test_existing_member_sees_member_status_instead_of_application_form(self) -> None:
        member = create_member(member_no="mem-apply-existing", role_name=ROLE_FORMAL_MEMBER, status=Member.Status.ACTIVE)
        login_as_member(self.client, member)

        response = self.client.get("/apply/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "你已经是成员")
        self.assertContains(response, "/workspace/")
        self.assertNotContains(response, 'name="password1"')

    def test_member_application_auto_creates_proposal_and_binds_account(self) -> None:
        self._register("candidate-a", applicant_name="候选成员 A")
        response = self._apply_authenticated_post(
            "candidate-a", "候选成员 A", "candidate-a@example.test", "愿意参加。",
        )
        self.assertEqual(response.status_code, 200)
        member_application = MemberApplication.objects.get(requested_member_no="candidate-a")
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

    def test_member_application_rejects_conflicting_availability_slots(self) -> None:
        self._register("slot-conflict", applicant_name="时段冲突")
        data = {
            "applicant_name": "时段冲突",
            "contact": "slot-conflict@example.test",
            "role_gap": "developer_ai_engineer",
            "availability_slots": ["any_time", "weekend"],
            "motivation_reasons": ["other"],
            "motivation_other_text": "验证时段冲突。",
            "confirm_submit": "on",
        }
        response = self.client.post("/apply/", data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "全天可用")
        self.assertFalse(MemberApplication.objects.filter(requested_member_no="slot-conflict").exists())

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

    def test_rejected_applicant_can_reapply_with_same_account_and_member(self) -> None:
        self._register("reapply-a", applicant_name="再次申请者")
        response = self._apply_authenticated_post(
            "reapply-a", "再次申请者", "reapply-a@example.test", "第一次申请。",
        )
        self.assertEqual(response.status_code, 200)
        first_application = MemberApplication.objects.get(requested_member_no="reapply-a")
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
        data = {
            "applicant_name": "再次申请者",
            "contact": "reapply-a@example.test",
            "role_gap": "service_resident",
            "availability_slots": ["weekend"],
            "motivation_reasons": ["other"],
            "motivation_other_text": "第二次申请。",
            "confirm_submit": "on",
        }
        response = self.client.post("/apply/", data, follow=True)
        self.assertEqual(response.status_code, 200)
        applications = list(MemberApplication.objects.filter(requested_member_no="reapply-a").order_by("submitted_at"))
        self.assertEqual(len(applications), 2)
        self.assertEqual(applications[-1].linked_member, member)
        member.refresh_from_db()
        self.assertEqual(member.status, Member.Status.PENDING_REVIEW)
        self.assertContains(response, "报名工作台")

    # ── service-layer direct tests ──────────────────────────────────────

    def test_register_participant_account_service_creates_baseline_identity(self) -> None:
        event_count = Event.objects.count()
        app_count = MemberApplication.objects.count()
        user, member = register_participant_account(
            username="svc-reg-user",
            password="svc-pass-123",
            display_name="Service 注册",
            contact="svc-reg@example.test",
        )
        self.assertEqual(user.username, "svc-reg-user")
        self.assertEqual(member.member_no, "svc-reg-user")
        self.assertEqual(member.display_name, "Service 注册")
        self.assertEqual(member.status, Member.Status.PENDING_REVIEW)
        self.assertEqual((member.metadata or {}).get("registration_contact"), "svc-reg@example.test")
        self.assertTrue(member_has_role(member, ROLE_BIG_APPLE_MEMBER))
        self.assertEqual(MemberApplication.objects.count(), app_count)
        self.assertEqual(Event.objects.count(), event_count)

    def test_ensure_basic_member_for_user_service_creates_baseline_identity(self) -> None:
        user = get_user_model().objects.create_user(username="svc-ens-user", password="p")
        member = ensure_basic_member_for_user(user)
        self.assertEqual(member.member_no, "svc-ens-user")
        self.assertEqual(member.user, user)
        self.assertTrue(member_has_role(member, ROLE_BIG_APPLE_MEMBER))
        # idempotent
        member2 = ensure_basic_member_for_user(user)
        self.assertEqual(member2.pk, member.pk)

    # ── transaction rollback tests ──────────────────────────────────────

    def test_register_participant_account_rolls_back_when_role_assignment_fails(self) -> None:
        with patch("core.identity_services.ensure_role_assignment", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                register_participant_account(
                    username="rollback-reg-user",
                    password="rollback-pass-123",
                    display_name="Rollback 注册",
                    contact="rollback@example.test",
                )
        self.assertFalse(get_user_model().objects.filter(username="rollback-reg-user").exists())
        self.assertFalse(Member.objects.filter(member_no="rollback-reg-user").exists())

    def test_ensure_basic_member_for_user_rolls_back_when_role_assignment_fails(self) -> None:
        user = get_user_model().objects.create_user(username="rollback-ens-user", password="p")
        with patch("core.identity_services.ensure_role_assignment", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                ensure_basic_member_for_user(user)
        self.assertFalse(Member.objects.filter(member_no="rollback-ens-user").exists())

    # ── legacy / other ──────────────────────────────────────────────────

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


class ApplyFormalMemberRoleTests(TestCase):
    """``/apply/`` formal-member detection is based on ROLE_FORMAL_MEMBER, not Member.status."""

    def _active_no_role(self, member_no: str):
        return create_member(member_no=member_no, status=Member.Status.ACTIVE)

    def _formal_member(self, member_no: str, status: str = Member.Status.ACTIVE):
        return create_member(member_no=member_no, role_name=ROLE_FORMAL_MEMBER, status=status)

    # ── ACTIVE without ROLE_FORMAL_MEMBER must NOT show "已是正式成员" ──

    def test_active_without_formal_role_sees_apply_not_status_page(self) -> None:
        member = self._active_no_role("mem-act-no-formal")
        login_as_member(self.client, member)
        response = self.client.get("/apply/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "你已经是成员")
        # should still show the application form (or applicant status)
        self.assertContains(response, "name=")

    # ── ROLE_FORMAL_MEMBER shows "已是正式成员" ──

    def test_formal_role_shows_already_member_status(self) -> None:
        member = self._formal_member("mem-formal-apply")
        login_as_member(self.client, member)
        response = self.client.get("/apply/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "你已经是成员")
        self.assertNotContains(response, 'name="password1"')

    # ── SUSPENDED / EXITED veto ──

    def test_formal_role_suspended_does_not_show_already_member(self) -> None:
        member = self._formal_member("mem-formal-susp-a", status=Member.Status.SUSPENDED)
        login_as_member(self.client, member)
        response = self.client.get("/apply/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "你已经是成员")
        self.assertContains(response, "当前账号暂不能提交成员报名")
        self.assertNotContains(response, 'name="applicant_name"')

    def test_formal_role_exited_does_not_show_already_member(self) -> None:
        member = self._formal_member("mem-formal-exit-a", status=Member.Status.EXITED)
        login_as_member(self.client, member)
        response = self.client.get("/apply/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "你已经是成员")
        self.assertContains(response, "当前账号暂不能提交成员报名")
        self.assertNotContains(response, 'name="applicant_name"')

    # ── service-layer enforcement ──────────────────────────────────────

    def test_active_no_formal_role_can_post_apply(self) -> None:
        """ACTIVE without ROLE_FORMAL_MEMBER can POST /apply/ and submit."""
        member = self._active_no_role("mem-act-apply-post")
        login_as_member(self.client, member)
        data = {
            **member_application_post_data(
                username="mem-act-apply-post",
                applicant_name="ACTIVE 报名测试",
                contact="active-test@example.test",
                motivation="验证 ACTIVE 无正式角色能报名。",
            ),
            "password1": "",
            "password2": "",
        }
        response = self.client.post("/apply/", data, follow=True)
        self.assertEqual(response.status_code, 200)
        app = MemberApplication.objects.filter(linked_member=member).first()
        self.assertIsNotNone(app, "应创建 MemberApplication")
        self.assertEqual(app.linked_member, member)
        member.refresh_from_db()
        self.assertEqual(member.status, Member.Status.PENDING_REVIEW)

    def test_formal_role_cannot_submit_duplicate_via_service(self) -> None:
        """ROLE_FORMAL_MEMBER rejects submit_member_application() directly."""
        member = self._formal_member("mem-formal-svc-dup")
        login_as_member(self.client, member)
        with self.assertRaises(DomainError):
            submit_member_application(
                account_user=member.user,
                applicant_name="重复报名者",
                contact="dup@example.test",
                motivation="应该被拒绝。",
                availability_hours_per_week=8,
                role_gap="developer_ai_engineer",
                availability_slots=["weekend"],
                capability_scores={"文档": 70},
                requested_member_no=member.member_no,
            )
        self.assertFalse(
            MemberApplication.objects.filter(linked_member=member).exists(),
            "不应创建 MemberApplication",
        )

    def test_suspended_formal_member_post_apply_rejected_status_unchanged(self) -> None:
        """SUSPENDED member POST /apply/ is rejected, status stays SUSPENDED."""
        member = self._formal_member("mem-formal-susp-post", status=Member.Status.SUSPENDED)
        login_as_member(self.client, member)
        data = {
            **member_application_post_data(
                username="mem-formal-susp-post",
                applicant_name="SUSPENDED 报名",
                contact="susp@example.test",
                motivation="应该被拒绝。",
            ),
            "password1": "",
            "password2": "",
        }
        app_count_before = MemberApplication.objects.count()
        self.client.post("/apply/", data)
        self.assertEqual(
            MemberApplication.objects.count(),
            app_count_before,
            "不应创建 MemberApplication",
        )
        member.refresh_from_db()
        self.assertEqual(member.status, Member.Status.SUSPENDED, "状态应仍为 SUSPENDED")

    def test_exited_formal_member_post_apply_rejected_status_unchanged(self) -> None:
        """EXITED member POST /apply/ is rejected, status stays EXITED."""
        member = self._formal_member("mem-formal-exit-post", status=Member.Status.EXITED)
        login_as_member(self.client, member)
        data = {
            **member_application_post_data(
                username="mem-formal-exit-post",
                applicant_name="EXITED 报名",
                contact="exit@example.test",
                motivation="应该被拒绝。",
            ),
            "password1": "",
            "password2": "",
        }
        app_count_before = MemberApplication.objects.count()
        self.client.post("/apply/", data)
        self.assertEqual(
            MemberApplication.objects.count(),
            app_count_before,
            "不应创建 MemberApplication",
        )
        member.refresh_from_db()
        self.assertEqual(member.status, Member.Status.EXITED, "状态应仍为 EXITED")
