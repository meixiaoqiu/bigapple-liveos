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

    # basic rendering

    def test_member_profile_page_accessible_with_profile(self):
        member = self._create_member("test-profile-01", "王梓尧")
        MemberPublicProfile.objects.create(
            member=member,
            public_name="王梓尧",
            avatar_url="https://example.com/a.png",
        )
        response = self.client.get("/u/test-profile-01/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "王梓尧")
        self.assertContains(response, "https://example.com/a.png")
        self.assertContains(response, "@test-profile-01")

    def test_old_members_path_returns_404(self):
        self._create_member("test-oldpath", "旧路径")
        self.assertEqual(self.client.get("/members/test-oldpath/").status_code, 404)

    def test_member_profile_page_fallback_without_profile(self):
        self._create_member("test-noprofile", "张三")
        response = self.client.get("/u/test-noprofile/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "张三")

    def test_member_profile_404_nonexistent(self):
        response = self.client.get("/u/nonexistent-no/")
        self.assertEqual(response.status_code, 404)

    def test_profile_with_is_visible_false_still_shows_public_name_and_avatar(self):
        """is_visible=False 时仍展示 public_name 和 avatar_url。"""
        member = self._create_member("test-invis", "隐藏名")
        MemberPublicProfile.objects.create(
            member=member,
            public_name="我的公开名",
            avatar_url="https://example.com/priv.png",
            is_visible=False,
        )
        response = self.client.get("/u/test-invis/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "我的公开名")
        self.assertContains(response, "https://example.com/priv.png")

    def test_profile_page_does_not_show_bio_or_is_visible(self):
        """页面不包含 bio 和 is_profile_visible。"""
        member = self._create_member("test-nobio", "无简介")
        MemberPublicProfile.objects.create(
            member=member,
            public_name="公开",
            bio="不应出现",
            is_visible=True,
        )
        response = self.client.get("/u/test-nobio/")
        self.assertContains(response, "公开")
        self.assertNotContains(response, "暂未填写公开简介")
        self.assertNotContains(response, "不应出现")
        self.assertNotContains(response, "is_profile_visible")

    # identity badges

    def test_member_profile_shows_identity_badges(self):
        from core.member_roles import ROLE_FORMAL_MEMBER
        member = create_member("badge-test-01", display_name="徽章人", role_name=ROLE_FORMAL_MEMBER)
        response = self.client.get("/u/badge-test-01/")
        self.assertContains(response, "注册参与者")
        self.assertContains(response, "正式成员")

    def test_regular_member_does_not_show_fake_formal_number(self):
        member = self._create_member("reg-only", "普通注册者")
        response = self.client.get("/u/reg-only/")
        self.assertContains(response, "注册参与者")
        self.assertNotContains(response, "正式成员")
        self.assertNotContains(response, "正式成员 #")

    # governance roles with Chinese labels

    def test_member_profile_shows_chinese_permission_labels(self):
        from core.models import Organization
        org = Organization.objects.create(name="治理委员会")
        role = Role.objects.create(name="Governance Member", organization=org, status=Role.Status.ACTIVE)
        perm = Permission.objects.create(code="governance.vote", name="投票", category="governance")
        RolePermission.objects.create(role=role, permission=perm, scope="*")
        member = self._create_member("test-gov-zh", "治理成员")
        RoleAssignment.objects.create(
            member=member, role=role,
            status=RoleAssignment.Status.ACTIVE,
            start_at=timezone.now() - timezone.timedelta(days=1),
            end_at=timezone.now() + timezone.timedelta(days=365),
            source_type=RoleAssignment.SourceType.INITIALIZATION,
        )
        response = self.client.get("/u/test-gov-zh/")
        self.assertContains(response, "治理委员会")
        self.assertContains(response, "Governance Member")
        self.assertContains(response, "参与治理投票")
        self.assertNotContains(response, "governance.vote")

    def test_unknown_governance_permission_shows_fallback_label(self):
        from core.models import Organization
        org = Organization.objects.create(name="TestOrg")
        role = Role.objects.create(name="TestRole", organization=org, status=Role.Status.ACTIVE)
        perm = Permission.objects.create(code="governance.custom_thing", name="Custom", category="governance")
        RolePermission.objects.create(role=role, permission=perm, scope="*")
        member = self._create_member("test-gov-unk", "未知权限")
        RoleAssignment.objects.create(
            member=member, role=role,
            status=RoleAssignment.Status.ACTIVE,
            start_at=timezone.now() - timezone.timedelta(days=1),
            end_at=timezone.now() + timezone.timedelta(days=365),
            source_type=RoleAssignment.SourceType.INITIALIZATION,
        )
        response = self.client.get("/u/test-gov-unk/")
        self.assertContains(response, "其他治理权限")

    # credentials

    def test_member_profile_shows_formal_member_number_credential(self):
        from core.member_roles import ROLE_FORMAL_MEMBER
        ensure_builtin_credential_templates()
        member = create_member("cred-obs-01", display_name="凭证成员", role_name=ROLE_FORMAL_MEMBER)
        issue_formal_member_number(member)
        response = self.client.get("/u/cred-obs-01/")
        self.assertContains(response, "正式成员编号")
        self.assertContains(response, "#1")
        self.assertContains(response, "正式成员 #1")

    def test_member_profile_does_not_leak_internal_pks(self):
        from core.member_roles import ROLE_FORMAL_MEMBER
        ensure_builtin_credential_templates()
        member = create_member("cred-obs-safe", display_name="安全成员", role_name=ROLE_FORMAL_MEMBER)
        issue_formal_member_number(member)
        response = self.client.get("/u/cred-obs-safe/")
        content = response.content.decode().lower()
        self.assertNotIn("credential-grant-", content)
        self.assertNotIn("email", content)
        self.assertNotIn("password", content)
        self.assertNotIn("user_id", content)
        self.assertNotIn("member_id", content)

    def test_multiple_credentials_sorted_stable(self):
        from core.member_roles import ROLE_FORMAL_MEMBER
        ensure_builtin_credential_templates()
        member = create_member("cred-obs-sort", role_name=ROLE_FORMAL_MEMBER)
        issue_formal_member_number(member)
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
            dedupe_key="test_badge:1",
            serial_no=1,
        )
        creds = credentials_for_member(member)
        self.assertGreaterEqual(len(creds), 2)
        self.assertEqual(creds[0]["template_code"], "formal_member_number")
        self.assertEqual(creds[-1]["template_code"], "test_badge")

    # recent governance activity

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
        response = self.client.get("/u/test-recent/")
        self.assertContains(response, "成员执行了测试操作")

    def test_member_profile_shows_vote_details_in_activity(self):
        from core.event_ledger import PUBLIC_LEDGER_SCHEMA, append_event
        from core.models import SystemEvent
        member = self._create_member("vote-actor", "投票演员")
        payload = {
            "schema": PUBLIC_LEDGER_SCHEMA,
            "subject": {"type": "proposal_vote", "ref": "proposal:0001", "label": "准入提案"},
            "action": "vote",
            "stage": "voting",
            "summary": "治理成员对提案 0001 投了反对票。",
            "public_facts": {
                "proposal_no": "0001",
                "vote_choice_label": "反对",
                "vote_choice": "no",
                "reason": "技能不匹配",
            },
            "private_commitments": [],
        }
        append_event(
            event_type=SystemEvent.EventType.PROPOSAL_VOTE_CAST,
            aggregate_type="ProposalVote",
            aggregate_id="vote-99",
            actor_member=member,
            payload_json=payload,
            occurred_at=timezone.now(),
        )
        response = self.client.get("/u/vote-actor/")
        self.assertContains(response, "反对")
        self.assertContains(response, "技能不匹配")
        self.assertContains(response, "投票")

    def test_member_application_timeline_links_voter_profile(self):
        member = self._create_member("voter-01", "投票人")
        MemberPublicProfile.objects.create(member=member, public_name="王梓尧")
        from core.event_ledger import PUBLIC_LEDGER_SCHEMA, append_event
        from core.models import Event, SystemEvent
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
        self.assertContains(response, "/u/voter-01/")
        self.assertContains(response, "反对")
        self.assertContains(response, "能力不足")

    def test_proposal_vote_payload_uses_public_profile_name(self):
        from core.event_payloads import proposal_vote_payload
        from core.models import Proposal, ProposalVote
        member = self._create_member("pvoter-01", "原名")
        MemberPublicProfile.objects.create(member=member, public_name="王梓尧")
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

    def test_page_does_not_contain_sensitive_fields(self):
        from core.member_roles import ROLE_FORMAL_MEMBER
        ensure_builtin_credential_templates()
        member = create_member("sensitive-test", display_name="敏感测试", role_name=ROLE_FORMAL_MEMBER)
        issue_formal_member_number(member)
        response = self.client.get("/u/sensitive-test/")
        content = response.content.decode()
        self.assertNotIn("contact", content.lower())
        self.assertNotIn("email", content.lower())
        self.assertNotIn("password", content.lower())
        self.assertNotIn("proposal_id", content.lower())
        self.assertNotIn("member_id", content.lower())

    # passive events: credential / role granted to member

    def test_credential_grant_appears_in_recent_actions(self):
        """成员获得正式成员编号后，治理记录包含"凭证发放"和正式编号。"""
        from core.event_ledger import PUBLIC_LEDGER_SCHEMA, append_event
        from core.models import SystemEvent, CredentialGrant
        from core.member_roles import ROLE_FORMAL_MEMBER

        ensure_builtin_credential_templates()
        member = create_member("passive-cred", display_name="被动凭证", role_name=ROLE_FORMAL_MEMBER)
        grant = issue_formal_member_number(member)

        payload = {
            "schema": PUBLIC_LEDGER_SCHEMA,
            "subject": {"type": "CredentialGrant", "ref": str(grant.grant_id), "label": "凭证发放"},
            "action": "granted",
            "stage": "granted",
            "summary": "发放正式成员编号 #1。",
            "public_facts": {
                "template_name": "正式成员编号",
                "display_no": "#1",
            },
            "private_commitments": [
                {"name": "member_id", "present": True, "reason": "关联成员"},
                {"name": "grant_id", "present": True, "reason": "关联凭证"},
            ],
        }
        append_event(
            event_type=SystemEvent.EventType.CREDENTIAL_GRANTED,
            aggregate_type="CredentialGrant",
            aggregate_id=grant.grant_id,
            actor_member=None,
            payload_json=payload,
            occurred_at=timezone.now(),
        )
        response = self.client.get("/u/passive-cred/")
        self.assertContains(response, "凭证发放")
        self.assertContains(response, "正式成员编号 #1")

    def test_role_assignment_appears_in_recent_actions(self):
        """成员被授予角色后，治理记录包含"角色任命"和角色名。"""
        from core.event_ledger import PUBLIC_LEDGER_SCHEMA, append_event
        from core.models import Organization, SystemEvent

        member = self._create_member("passive-role", "被动角色")
        org = Organization.objects.create(name="TestOrg")
        role = Role.objects.create(name="测试角色", organization=org, status=Role.Status.ACTIVE)
        ra = RoleAssignment.objects.create(
            member=member, role=role,
            status=RoleAssignment.Status.ACTIVE,
            start_at=timezone.now(),
            end_at=timezone.now() + timezone.timedelta(days=365),
            source_type=RoleAssignment.SourceType.DIRECT,
        )
        payload = {
            "schema": PUBLIC_LEDGER_SCHEMA,
            "subject": {"type": "RoleAssignment", "ref": str(ra.pk), "label": "角色任命"},
            "action": "assigned",
            "stage": "assigned",
            "summary": "授予测试角色给被动角色。",
            "public_facts": {
                "role_name": "测试角色",
            },
            "private_commitments": [
                {"name": "member_id", "present": True, "reason": "关联成员"},
            ],
        }
        append_event(
            event_type=SystemEvent.EventType.ROLE_ASSIGNED,
            aggregate_type="RoleAssignment",
            aggregate_id=str(ra.pk),
            actor_member=None,
            payload_json=payload,
            occurred_at=timezone.now(),
        )
        response = self.client.get("/u/passive-role/")
        self.assertContains(response, "角色任命")
        self.assertContains(response, "测试角色")

    def test_recent_actions_no_internal_ids(self):
        """治理记录不泄露 credential-grant-、role_assignment_id、grant_id、aggregate_id。"""
        from core.event_ledger import PUBLIC_LEDGER_SCHEMA, append_event
        from core.models import SystemEvent
        from core.member_roles import ROLE_FORMAL_MEMBER

        ensure_builtin_credential_templates()
        member = create_member("safe-actor", display_name="安全行动", role_name=ROLE_FORMAL_MEMBER)
        grant = issue_formal_member_number(member)
        payload = {
            "schema": PUBLIC_LEDGER_SCHEMA,
            "subject": {"type": "CredentialGrant", "ref": str(grant.grant_id), "label": "凭证"},
            "action": "granted",
            "stage": "granted",
            "summary": "发放凭证。",
            "public_facts": {"template_name": "正式成员编号", "display_no": "#1"},
            "private_commitments": [
                {"name": "grant_id", "present": True, "reason": "关联凭证"},
            ],
        }
        append_event(
            event_type=SystemEvent.EventType.CREDENTIAL_GRANTED,
            aggregate_type="CredentialGrant",
            aggregate_id=grant.grant_id,
            actor_member=None,
            payload_json=payload,
            occurred_at=timezone.now(),
        )
        response = self.client.get("/u/safe-actor/")
        content = response.content.decode().lower()
        self.assertNotIn("credential-grant-", content)
        self.assertNotIn("grant_id", content)
        self.assertNotIn("role_assignment_id", content)
        self.assertNotIn("aggregate_id", content)
