"""Tests for observer member public profile pages."""

from __future__ import annotations

from django.test import TestCase
from django.utils import timezone

from core.credential_services import (
    _issue_credential_unlocked,
    credentials_for_member,
    ensure_builtin_credential_templates,
    issue_formal_member_number,
)
from core.models import CredentialTemplate, Member, MemberPublicProfile, Permission, Role, RolePermission, RoleAssignment
from core.tests.helpers import create_member


class MemberProfileTests(TestCase):

    def _create_member(self, member_no="test-profile-01", display_name="测试成员") -> Member:
        return create_member(member_no=member_no, display_name=display_name, status=Member.Status.ADMITTED)

    def test_member_profile_page_accessible_with_profile(self):
        member = self._create_member("test-profile-01", "王梓尧")
        MemberPublicProfile.objects.create(
            member=member,
            public_name="王梓尧",
            avatar_url="https://example.com/a.png",
            bio="项目发起人",
            is_visible=True,
        )
        response = self.client.get("/members/test-profile-01/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "王梓尧")
        self.assertContains(response, "项目发起人")
        self.assertContains(response, "https://example.com/a.png")

    def test_member_profile_page_fallback_without_profile(self):
        self._create_member("test-noprofile", "张三")
        response = self.client.get("/members/test-noprofile/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "张三")
        self.assertContains(response, "暂未填写公开简介")

    def test_member_profile_404_nonexistent(self):
        response = self.client.get("/members/nonexistent-no/")
        self.assertEqual(response.status_code, 404)

    def test_member_profile_shows_role_assignment_as_governance_identity(self):
        from core.models import Organization
        org = Organization.objects.create(name="治理委员会")
        role = Role.objects.create(name="Governance Member", organization=org, status=Role.Status.ACTIVE)
        perm = Permission.objects.create(code="governance.view_admin", name="查看管理后台", category="governance")
        RolePermission.objects.create(role=role, permission=perm, scope="*")
        member = self._create_member("test-gov-01", "治理成员")
        RoleAssignment.objects.create(
            member=member, role=role,
            status=RoleAssignment.Status.ACTIVE,
            start_at=timezone.now() - timezone.timedelta(days=1),
            end_at=timezone.now() + timezone.timedelta(days=365),
            source_type=RoleAssignment.SourceType.INITIALIZATION,
        )
        response = self.client.get("/members/test-gov-01/")
        self.assertContains(response, "治理委员会")
        self.assertContains(response, "Governance Member")
        self.assertContains(response, "governance.view_admin")
        self.assertContains(response, "以上身份来自系统角色任命，非用户自填")

    def test_member_profile_recent_actions(self):
        from core.event_ledger import PUBLIC_LEDGER_SCHEMA, append_event
        member = self._create_member("test-recent", "活跃成员")
        payload = {
            "schema": PUBLIC_LEDGER_SCHEMA,
            "subject": {"type": "test", "ref": "test:1", "label": "测试"},
            "action": "created",
            "stage": "created",
            "summary": "成员执行了测试操作。",
            "public_facts": {},
            "private_commitments": [],
        }
        append_event(
            event_type="member_created",
            aggregate_type="Test",
            aggregate_id="test-1",
            actor_member=member,
            payload_json=payload,
            occurred_at=timezone.now(),
        )
        response = self.client.get("/members/test-recent/")
        self.assertContains(response, "成员执行了测试操作")

    def test_member_application_timeline_links_voter_profile(self):
        member = self._create_member("voter-01", "投票人")
        MemberPublicProfile.objects.create(
            member=member, public_name="王梓尧", is_visible=True,
        )
        from core.event_ledger import PUBLIC_LEDGER_SCHEMA, append_event
        from core.models import Event, SystemEvent
        # Create a vote SystemEvent with this member as actor
        vote_payload = {
            "schema": PUBLIC_LEDGER_SCHEMA,
            "subject": {"type": "proposal_vote", "ref": "proposal:0001", "label": "member_admission"},
            "action": "no",
            "stage": "voting",
            "summary": "提案 0001 收到投票：反对（王梓尧）。",
            "public_facts": {
                "proposal_no": "0001",
                "vote_choice_label": "反对",
                "vote_choice": "no",
                "voter_public_name": "王梓尧",
                "application_id": "app-voter-link",
                "reason": "能力不足",
            },
            "private_commitments": [],
        }
        append_event(
            event_type=SystemEvent.EventType.PROPOSAL_VOTE_CAST,
            aggregate_type="ProposalVote",
            aggregate_id="vote-1",
            actor_member=member,
            payload_json=vote_payload,
            occurred_at=timezone.now(),
        )
        # Create a public Event so the MA detail page resolves
        Event.objects.create(
            event_id="member-application-submitted-app-voter-link",
            event_type="governance",
            visibility="public",
            title="收到成员报名",
            summary="测试。",
            payload={"source": "member_application", "stage": "submitted", "application_id": "app-voter-link"},
            simulation_day=1,
            occurred_at=timezone.now(),
            generated_by="live_os",
            severity="info",
        )
        response = self.client.get("/member-applications/app-voter-link/")
        self.assertContains(response, "/members/voter-01/")
        self.assertContains(response, "反对")
        self.assertContains(response, "能力不足")

    def test_proposal_vote_payload_uses_public_profile_name(self):
        from core.event_payloads import proposal_vote_payload
        from core.models import Proposal, ProposalVote
        member = self._create_member("pvoter-01", "原名")
        MemberPublicProfile.objects.create(
            member=member, public_name="王梓尧", is_visible=True,
        )
        org = __import__("core.models", fromlist=["Organization"]).Organization.objects.create(name="Test")
        role = Role.objects.create(name="TestRole", organization=org, status=Role.Status.ACTIVE)
        proposal = Proposal.objects.create(
            title="Test", proposal_type=Proposal.ProposalType.MEMBER_ADMISSION,
            status=Proposal.Status.VOTING, pass_ratio=50,
            start_at=timezone.now(), deadline_at=timezone.now() + timezone.timedelta(days=7),
            eligible_voters_snapshot_json=[str(member.pk)],
        )
        vote = ProposalVote.objects.create(
            proposal=proposal, voter_member=member,
            choice=ProposalVote.Choice.NO, reason="测试",
            voted_at=timezone.now(),
        )
        payload = proposal_vote_payload(vote)
        facts = payload["public_facts"]
        self.assertEqual(facts["voter_public_name"], "王梓尧")
        flat = str(payload)
        self.assertNotIn("avatar_url", flat)
        self.assertNotIn("bio", flat)

    def test_member_profile_shows_formal_member_number_credential(self):
        """Observer member profile 显示正式成员编号。"""
        from core.member_roles import ROLE_FORMAL_MEMBER

        ensure_builtin_credential_templates()
        member = create_member("cred-obs-01", display_name="凭证成员", role_name=ROLE_FORMAL_MEMBER)
        issue_formal_member_number(member)
        response = self.client.get("/members/cred-obs-01/")
        self.assertContains(response, "正式成员编号")
        self.assertContains(response, "#1")

    def test_member_profile_does_not_leak_internal_pks(self):
        """不泄露 CredentialGrant.pk / Member.pk / User.id。"""
        from core.member_roles import ROLE_FORMAL_MEMBER

        ensure_builtin_credential_templates()
        member = create_member("cred-obs-safe", display_name="安全成员", role_name=ROLE_FORMAL_MEMBER)
        issue_formal_member_number(member)
        response = self.client.get("/members/cred-obs-safe/")
        content = response.content.decode()
        # Must not expose grant PKs (credential-grant-xxx ids)
        self.assertNotIn("credential-grant-", content.lower())

    def test_multiple_credentials_sorted_stable(self):
        """多个 credential 排序稳定：template.display_order, serial_no, issued_at。"""
        from core.member_roles import ROLE_FORMAL_MEMBER

        ensure_builtin_credential_templates()
        member = create_member("cred-obs-sort", role_name=ROLE_FORMAL_MEMBER)
        issue_formal_member_number(member)
        # Create another template with higher display_order
        badge_template = CredentialTemplate.objects.create(
            template_id="credential-template-test-badge",
            code="test_badge",
            name="测试勋章",
            credential_type=CredentialTemplate.CredentialType.BADGE,
            visibility=CredentialTemplate.Visibility.PUBLIC,
            display_order=10,
        )
        _issue_credential_unlocked(
            template=badge_template,
            member=member,
            serial_no=1,
        )
        creds = credentials_for_member(member)
        self.assertGreaterEqual(len(creds), 2)
        # formal_member_number (display_order=1) before badge (display_order=10)
        self.assertEqual(creds[0]["template_code"], "formal_member_number")
        self.assertEqual(creds[-1]["template_code"], "test_badge")
