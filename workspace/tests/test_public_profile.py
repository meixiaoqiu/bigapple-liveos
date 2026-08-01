"""Tests for self-service public profile page."""

from __future__ import annotations

from django.test import TestCase

from core.member_roles import ROLE_DELIBERATOR, ROLE_COVENANTER, ensure_catalog_role
from core.models import Member, MemberPublicProfile
from core.role_assignment_services import create_role_assignment
from core.tests.helpers import create_member, login_as_member


class PublicProfilePageTests(TestCase):

    def setUp(self) -> None:
        self.member = create_member(
            member_no="mem-profile-01",
            status=Member.Status.ADMITTED,
            display_name="测试成员",
        )
        login_as_member(self.client, self.member)

    def test_member_can_open_public_profile_page(self):
        response = self.client.get("/workspace/profile/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "公开资料")
        self.assertContains(response, "保存")
        self.assertContains(response, "预览公开主页")
        # 预览链接应使用 /u/<member_no>/
        self.assertContains(response, "/u/mem-profile-01/")

    def test_workspace_profile_uses_the_same_membership_and_duty_labels(self):
        create_role_assignment(member=self.member, role=ensure_catalog_role(ROLE_COVENANTER))
        create_role_assignment(member=self.member, role=ensure_catalog_role(ROLE_DELIBERATOR))

        response = self.client.get("/workspace/profile/")

        self.assertContains(response, "守约者")
        self.assertContains(response, "执衡者")
        self.assertNotContains(response, "治理" + "成员")

    def test_member_can_update_own_public_profile(self):
        response = self.client.post("/workspace/profile/update/", {
            "public_name": "王梓尧",
            "avatar_url": "https://example.com/avatar.png",
        })
        self.assertEqual(response.status_code, 302)
        profile = MemberPublicProfile.objects.get(member=self.member)
        self.assertEqual(profile.public_name, "王梓尧")
        self.assertEqual(profile.avatar_url, "https://example.com/avatar.png")
        self.assertTrue(profile.is_visible)  # always visible from workspace

    def test_invalid_avatar_url_does_not_create_or_overwrite_profile(self):
        """Validation failure must not create a profile with bad URL, nor overwrite existing one."""
        response = self.client.post("/workspace/profile/update/", {
            "public_name": "test",
            "avatar_url": "not-a-url",
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            MemberPublicProfile.objects.filter(member=self.member).exists()
        )

    def test_invalid_avatar_url_does_not_overwrite_existing_profile(self):
        MemberPublicProfile.objects.create(member=self.member, public_name="旧名", avatar_url="https://old.com/pic.png")
        self.client.post("/workspace/profile/update/", {
            "public_name": "新名",
            "avatar_url": "not-a-url",
        })
        profile = MemberPublicProfile.objects.get(member=self.member)
        self.assertEqual(profile.public_name, "旧名")
        self.assertEqual(profile.avatar_url, "https://old.com/pic.png")

    def test_pending_applicant_can_edit_public_profile(self):
        applicant = create_member(
            member_no="mem-pending", status=Member.Status.PENDING_REVIEW,
            display_name="报名者",
        )
        login_as_member(self.client, applicant)
        response = self.client.get("/workspace/profile/")
        self.assertEqual(response.status_code, 200)
        self.client.post("/workspace/profile/update/", {
            "public_name": "报名者公开名", "avatar_url": "",
        })
        profile = MemberPublicProfile.objects.get(member=applicant)
        self.assertEqual(profile.public_name, "报名者公开名")

    def test_staff_without_member_cannot_edit_public_profile(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        staff = User.objects.create_user(username="staffonly", password="pass")
        self.client.force_login(staff)
        response = self.client.get("/workspace/profile/")
        self.assertEqual(response.status_code, 403)

    def test_public_profile_page_only_updates_current_member(self):
        other = create_member(member_no="other-01", status=Member.Status.ADMITTED)
        self.client.post("/workspace/profile/update/", {
            "public_name": "我的名字", "avatar_url": "",
        })
        self.assertFalse(
            MemberPublicProfile.objects.filter(member=other).exists()
        )

    def test_workspace_links_public_profile_page(self):
        response = self.client.get("/workspace/")
        self.assertContains(response, "/workspace/profile/")
        applicant = create_member(member_no="mem-applicant", status=Member.Status.PENDING_REVIEW)
        login_as_member(self.client, applicant)
        response = self.client.get("/workspace/")
        self.assertContains(response, "/workspace/profile/")

    def test_workspace_profile_shows_covenanter_number(self):
        """Workspace profile 显示自己的守约者编号。"""
        from core.credential_services import ensure_builtin_credential_templates, issue_covenanter_number
        from core.member_roles import ROLE_COVENANTER

        ensure_builtin_credential_templates()
        member = create_member(
            member_no="cred-ws-01",
            role_name=ROLE_COVENANTER,
            status=Member.Status.ADMITTED,
            display_name="凭证成员",
        )
        issue_covenanter_number(member)
        login_as_member(self.client, member)
        response = self.client.get("/workspace/profile/")
        self.assertContains(response, "守约者编号")
        self.assertContains(response, "#1")

    def test_workspace_profile_does_not_leak_internal_pks(self):
        """Workpace profile 不泄露 CredentialGrant.pk / Member.pk / User.id。"""
        from core.credential_services import ensure_builtin_credential_templates, issue_covenanter_number
        from core.member_roles import ROLE_COVENANTER

        ensure_builtin_credential_templates()
        member = create_member(
            member_no="cred-ws-safe",
            role_name=ROLE_COVENANTER,
            status=Member.Status.ADMITTED,
            display_name="安全成员",
        )
        issue_covenanter_number(member)
        login_as_member(self.client, member)
        response = self.client.get("/workspace/profile/")
        content = response.content.decode()
        # Must not expose grant PKs (credential-grant-xxx ids)
        self.assertNotIn("credential-grant-", content.lower())
        # Must not expose internal database User ids
        self.assertNotIn('user_id', content.lower())
        self.assertNotIn('"id":', content.lower())
