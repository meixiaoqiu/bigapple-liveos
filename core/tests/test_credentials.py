from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.db import IntegrityError
from django.test import TestCase

from core.credential_services import (
    _issue_credential_unlocked,
    credentials_for_member,
    ensure_builtin_credential_templates,
    issue_formal_member_number,
)
from core.exceptions import DomainError
from core.member_roles import ROLE_BIG_APPLE_MEMBER, ROLE_FORMAL_MEMBER, ensure_member_role, ensure_role_assignment, member_has_role
from core.models import CredentialGrant, CredentialTemplate, Member, RoleAssignment, SystemEvent
from core.role_assignment_services import create_role_assignment
from core.tests.helpers import create_member


class CredentialServicesTests(TestCase):
    def setUp(self):
        ensure_builtin_credential_templates()

    # ── template ───────────────────────────────────────────────────────

    def test_ensure_builtin_credential_templates_is_idempotent(self):
        first = ensure_builtin_credential_templates()
        second = ensure_builtin_credential_templates()
        self.assertEqual(second, 0)  # none created the second time
        t = CredentialTemplate.objects.get(code="formal_member_number")
        self.assertEqual(t.credential_type, CredentialTemplate.CredentialType.FORMAL_NUMBER)

    # ── formal member number ───────────────────────────────────────────

    def test_first_formal_member_gets_serial_no_1(self):
        member = create_member("cred-fml-1", role_name=ROLE_FORMAL_MEMBER)
        grant = issue_formal_member_number(member)
        self.assertEqual(grant.serial_no, 1)
        self.assertEqual(grant.display_no, "#1")

    def test_second_formal_member_gets_serial_no_2(self):
        m1 = create_member("cred-fml-2a", role_name=ROLE_FORMAL_MEMBER)
        m2 = create_member("cred-fml-2b", role_name=ROLE_FORMAL_MEMBER)
        g1 = issue_formal_member_number(m1)
        g2 = issue_formal_member_number(m2)
        self.assertEqual(g1.serial_no, 1)
        self.assertEqual(g2.serial_no, 2)

    def test_same_member_idempotent(self):
        """同一 member 重复调用不会重复发放。"""
        member = create_member("cred-fml-idem", role_name=ROLE_FORMAL_MEMBER)
        g1 = issue_formal_member_number(member)
        g2 = issue_formal_member_number(member)
        self.assertEqual(g1.pk, g2.pk)
        self.assertEqual(g1.serial_no, g2.serial_no)
        # 只创建了一条 grant
        self.assertEqual(
            CredentialGrant.objects.filter(member=member).count(), 1
        )

    def test_serial_no_increments_monotonically(self):
        """serial_no 1, 2, 3 连续递增。"""
        m1 = create_member("cred-incr-1", role_name=ROLE_FORMAL_MEMBER)
        m2 = create_member("cred-incr-2", role_name=ROLE_FORMAL_MEMBER)
        m3 = create_member("cred-incr-3", role_name=ROLE_FORMAL_MEMBER)
        g1 = issue_formal_member_number(m1)
        g2 = issue_formal_member_number(m2)
        g3 = issue_formal_member_number(m3)
        self.assertEqual(g1.serial_no, 1)
        self.assertEqual(g2.serial_no, 2)
        self.assertEqual(g3.serial_no, 3)

    # ── auto-issue via create_role_assignment ───────────────────────────

    def test_create_role_assignment_formal_triggers_credential(self):
        member = create_member("cred-fml-auto", role_name="")
        create_role_assignment(
            member=member,
            role=ensure_member_role(ROLE_FORMAL_MEMBER),
            source_type="system",
        )
        self.assertTrue(member.credential_grants.filter(
            template__code="formal_member_number"
        ).exists())

    def test_create_role_assignment_credential_failure_rolls_back_role(self):
        """patch issue_formal_member_number 抛 RuntimeError → CredentialGrant 和
        活跃 ROLE_FORMAL_MEMBER RoleAssignment 都不存在。"""
        member = create_member("cred-fml-rollback", role_name=ROLE_BIG_APPLE_MEMBER)
        formal_role = ensure_member_role(ROLE_FORMAL_MEMBER)
        with patch("core.credential_services._issue_credential_unlocked",
                   side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                create_role_assignment(
                    member=member,
                    role=formal_role,
                    source_type="system",
                )
        self.assertFalse(member.credential_grants.exists())
        # ROLE_FORMAL_MEMBER 的活跃 RoleAssignment 不应存在
        self.assertFalse(
            RoleAssignment.objects.filter(
                member=member,
                role=formal_role,
                status=RoleAssignment.Status.ACTIVE,
            ).exists()
        )

    def test_create_role_assignment_repairs_missing_credential(self):
        """RoleAssignment 已存在但 credential 缺失时，create_role_assignment 应补发。"""
        member = create_member("cred-repair-1", role_name=ROLE_FORMAL_MEMBER)
        # 删除已自动发放的 credential
        CredentialGrant.objects.filter(member=member).delete()
        self.assertFalse(member.credential_grants.exists())
        # 再次调用 create_role_assignment（幂等，assignment 已存在还会触发补发逻辑）
        formal_role = ensure_member_role(ROLE_FORMAL_MEMBER)
        create_role_assignment(
            member=member,
            role=formal_role,
            source_type="system",
        )
        self.assertTrue(member.credential_grants.filter(
            template__code="formal_member_number"
        ).exists())

    # ── SystemEvent ─────────────────────────────────────────────────────

    def test_credential_grant_writes_system_event(self):
        member = create_member("cred-fml-ev", role_name=ROLE_FORMAL_MEMBER)
        grant = issue_formal_member_number(member)
        self.assertTrue(
            SystemEvent.objects.filter(
                event_type=SystemEvent.EventType.CREDENTIAL_GRANTED,
                aggregate_id=grant.grant_id,
            ).exists()
        )

    def test_credential_payload_no_internal_pks(self):
        member = create_member("cred-fml-payload", role_name=ROLE_FORMAL_MEMBER)
        grant = issue_formal_member_number(member)
        event = SystemEvent.objects.get(
            event_type=SystemEvent.EventType.CREDENTIAL_GRANTED,
            aggregate_id=grant.grant_id,
        )
        payload = event.payload_json
        facts = payload.get("public_facts", {})
        self.assertEqual(facts.get("template_code"), "formal_member_number")
        self.assertEqual(facts.get("display_no"), "#1")
        # Public facts must NOT contain contact/email/User reference
        self.assertNotIn("email", str(facts).lower())
        self.assertNotIn("@", str(facts))
        self.assertNotIn("user_id", str(facts))
        self.assertNotIn("contact", str(facts))
        # Private commitments record the *fact* that IDs exist
        privates = payload.get("private_commitments", [])
        self.assertTrue(any(p.get("name") == "member_id" for p in privates))
        self.assertTrue(any(p.get("name") == "grant_id" for p in privates))

    # ── credentials_for_member ──────────────────────────────────────────

    def test_credentials_for_member_returns_public_active(self):
        member = create_member("cred-list", role_name=ROLE_FORMAL_MEMBER)
        issue_formal_member_number(member)
        creds = credentials_for_member(member)
        self.assertEqual(len(creds), 1)
        self.assertEqual(creds[0]["template_code"], "formal_member_number")

    # ── credential does NOT grant permissions ────────────────────────────

    def test_credential_does_not_replace_role_for_workspace(self):
        member = create_member("cred-no-perm", role_name="")
        issue_formal_member_number(member)
        from workspace.context import member_has_full_workspace_access
        self.assertFalse(member_has_full_workspace_access(member))

    # ── IntegrityError handling ─────────────────────────────────────────





class RepairCommandTests(TestCase):
    """Tests for repair_formal_member_credentials management command."""

    def test_missing_world_id_raises_command_error(self):
        """缺 --world-id 报 CommandError。"""
        with self.assertRaises(CommandError):
            call_command("repair_formal_member_credentials")

    def test_dry_run_does_not_create_credential_template_or_grant(self):
        """--dry-run 不创建 CredentialTemplate / CredentialGrant。"""
        from contextlib import contextmanager

        CredentialTemplate.objects.all().delete()
        CredentialGrant.objects.all().delete()
        self.assertEqual(CredentialTemplate.objects.count(), 0)
        self.assertEqual(CredentialGrant.objects.count(), 0)

        @contextmanager
        def _mock_world_context(world_id, command_name):
            yield None

        out = StringIO()
        with patch(
            "core.management.commands.repair_formal_member_credentials.command_world_context",
            _mock_world_context,
        ):
            call_command(
                "repair_formal_member_credentials",
                world_id="control",
                dry_run=True,
                stdout=out,
            )

        self.assertIn("Would issue", out.getvalue())
        # No templates or grants should have been created
        self.assertEqual(CredentialTemplate.objects.count(), 0)
        self.assertEqual(CredentialGrant.objects.count(), 0)

    def test_non_dry_run_creates_templates_and_grants(self):
        """指定 world 下有 ROLE_FORMAL_MEMBER 且无 credential 时能补发。"""
        from contextlib import contextmanager

        CredentialGrant.objects.all().delete()
        member = create_member("repair-member-1", role_name=ROLE_FORMAL_MEMBER)
        CredentialGrant.objects.filter(member=member).delete()
        self.assertFalse(member.credential_grants.exists())

        @contextmanager
        def _mock_world_context(world_id, command_name):
            yield None

        out = StringIO()
        with patch(
            "core.management.commands.repair_formal_member_credentials.command_world_context",
            _mock_world_context,
        ):
            call_command(
                "repair_formal_member_credentials",
                world_id="control",
                dry_run=False,
                stdout=out,
            )
        self.assertIn("Issued", out.getvalue())
        self.assertTrue(member.credential_grants.filter(
            template__code="formal_member_number"
        ).exists())

    def test_already_has_credential_no_duplicate(self):
        """已有 credential 时不重复。"""
        from contextlib import contextmanager

        member = create_member("repair-member-2", role_name=ROLE_FORMAL_MEMBER)
        self.assertEqual(
            member.credential_grants.filter(template__code="formal_member_number").count(), 1
        )

        @contextmanager
        def _mock_world_context(world_id, command_name):
            yield None

        out = StringIO()
        with patch(
            "core.management.commands.repair_formal_member_credentials.command_world_context",
            _mock_world_context,
        ):
            call_command(
                "repair_formal_member_credentials",
                world_id="control",
                dry_run=False,
                stdout=out,
            )
        self.assertIn("Issued 0", out.getvalue())
        self.assertEqual(
            member.credential_grants.filter(template__code="formal_member_number").count(), 1
        )
