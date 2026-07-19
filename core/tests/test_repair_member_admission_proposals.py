from __future__ import annotations

from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from core.application_services import submit_member_application
from core.models import Member, MemberApplication, Proposal
from core.tests.helpers import create_member
from worlds.models import WorldRegistry


class RepairMemberAdmissionProposalsTests(TestCase):
    """Tests for ``repair_member_admission_proposals`` management command."""

    WORLD_ID = "realworld"

    def setUp(self) -> None:
        self.now = timezone.now()
        WorldRegistry.objects.get_or_create(
            world_id=self.WORLD_ID,
            defaults={
                "database_alias": "default",
                "world_type": "real",
                "status": WorldRegistry.Status.ACTIVE,
            },
        )

    def _create_orphan_application(self, member_no: str = "orphan-applicant") -> MemberApplication:
        """Create a MemberApplication with a linked_member but no admission_proposal."""
        user_model = __import__("django.contrib.auth", fromlist=["get_user_model"]).get_user_model()
        user = user_model.objects.create_user(username=member_no, password="test-password-123")
        member = create_member(member_no=member_no, status=Member.Status.PENDING_REVIEW)
        member.user = user
        member.save(update_fields=["user"])
        return MemberApplication.objects.create(
            application_id=f"member-application-{member_no}",
            applicant_name="孤儿报名者",
            contact=f"{member_no}@example.test",
            motivation="测试修复命令。",
            role_gap="developer_ai_engineer",
            linked_member=member,
            account_user=user,
            submitted_at=self.now,
            frozen_at=self.now,
            status=MemberApplication.Status.ADMISSION_VOTING,
        )

    # --- 参数校验 ---------------------------------------------------------------

    def test_missing_world_id_raises_command_error(self) -> None:
        with self.assertRaises(CommandError):
            call_command("repair_member_admission_proposals", stdout=StringIO())

    # --- dry-run 不写入 ----------------------------------------------------------

    def test_dry_run_does_not_create_proposal(self) -> None:
        app = self._create_orphan_application("dry-run-test")
        self.assertIsNone(app.admission_proposal_id)
        out = StringIO()
        call_command(
            "repair_member_admission_proposals",
            f"--world-id={self.WORLD_ID}",
            "--dry-run",
            stdout=out,
        )
        app.refresh_from_db()
        self.assertIsNone(app.admission_proposal_id)
        self.assertIn("dry-run", out.getvalue())

    # --- 有 linked_member、无 proposal → 补建 ------------------------------------

    def test_repairs_orphan_application_with_linked_member(self) -> None:
        app = self._create_orphan_application("repair-orphan")
        self.assertIsNone(app.admission_proposal_id)
        out = StringIO()
        call_command(
            "repair_member_admission_proposals",
            f"--world-id={self.WORLD_ID}",
            stdout=out,
        )
        app.refresh_from_db()
        self.assertIsNotNone(app.admission_proposal_id)
        self.assertEqual(
            app.admission_proposal.proposal_type,
            Proposal.ProposalType.MEMBER_ADMISSION,
        )
        self.assertIn("已补建", out.getvalue())

    # --- 已有 proposal → 跳过 ----------------------------------------------------

    def test_skips_application_with_existing_proposal(self) -> None:
        application = submit_member_application(
            applicant_name="已有提案者",
            contact="has-proposal@example.test",
            motivation="已有提案。",
            role_gap="life_service",
            availability_slots=["weekend"],
            requested_member_no="has-proposal",
        )
        self.assertIsNotNone(application.admission_proposal_id)
        proposal_count_before = Proposal.objects.count()
        out = StringIO()
        call_command(
            "repair_member_admission_proposals",
            f"--world-id={self.WORLD_ID}",
            stdout=out,
        )
        self.assertEqual(Proposal.objects.count(), proposal_count_before)
        self.assertIn("无需修复", out.getvalue())

    # --- 无 linked_member → 跳过 -------------------------------------------------

    def test_skips_application_without_linked_member(self) -> None:
        MemberApplication.objects.create(
            application_id="member-application-no-linked",
            applicant_name="无关联成员",
            contact="no-link@example.test",
            motivation="没有 linked_member。",
            role_gap="developer_ai_engineer",
            submitted_at=self.now,
            frozen_at=self.now,
            status=MemberApplication.Status.SUBMITTED,
        )
        out = StringIO()
        call_command(
            "repair_member_admission_proposals",
            f"--world-id={self.WORLD_ID}",
            stdout=out,
        )
        self.assertIn("无需修复", out.getvalue())


class MetadataMigrationTests(TestCase):
    """Verify metadata migration handles old + new keys correctly."""

    def setUp(self) -> None:
        self.now = timezone.now()

    def _app_with_metadata(self, member_no: str, meta: dict) -> MemberApplication:
        return MemberApplication.objects.create(
            application_id=f"member-application-{member_no}",
            applicant_name=member_no,
            contact=f"{member_no}@example.test",
            motivation="metadata 迁移测试。",
            submitted_at=self.now,
            frozen_at=self.now,
            metadata=meta,
        )

    @staticmethod
    def _get_migrate_metadata_keys():
        migration_mod = __import__(
            "core.migrations.0015_remove_memberapplication_reviewed_at_and_more",
            fromlist=["migrate_metadata_keys"],
        )
        return migration_mod.migrate_metadata_keys

    class _FakeSchemaEditor:
        class connection:
            alias = "default"

    @override_settings(WORLD_DATABASE_ROUTING_ENABLED=False)
    def test_both_old_and_new_keys_preserve_new_delete_old(self) -> None:
        """When both old (review_note, reviewed_by) and new
        (decision_note, decided_by_display) keys exist, the new keys are
        preserved and the old keys are deleted.
        """
        self._app_with_metadata(
            "old-and-new",
            {
                "review_note": "old note",
                "decision_note": "existing new note",
                "reviewed_by": "old reviewer",
                "decided_by_display": "existing display name",
            },
        )
        from django.apps import apps as django_apps

        migrate_metadata_keys = self._get_migrate_metadata_keys()
        migrate_metadata_keys(django_apps, self._FakeSchemaEditor())  # type: ignore[arg-type]

        app = MemberApplication.objects.get(application_id="member-application-old-and-new")
        self.assertNotIn("review_note", app.metadata)
        self.assertNotIn("reviewed_by", app.metadata)
        self.assertEqual(app.metadata["decision_note"], "existing new note")
        self.assertEqual(app.metadata["decided_by_display"], "existing display name")

    @override_settings(WORLD_DATABASE_ROUTING_ENABLED=False)
    def test_only_old_keys_migrated_new_keys_not_overwritten(self) -> None:
        self._app_with_metadata(
            "only-old",
            {
                "review_note": "old note only",
                "reviewed_by": "old reviewer only",
            },
        )
        from django.apps import apps as django_apps

        migrate_metadata_keys = self._get_migrate_metadata_keys()
        migrate_metadata_keys(django_apps, self._FakeSchemaEditor())  # type: ignore[arg-type]

        app = MemberApplication.objects.get(application_id="member-application-only-old")
        self.assertNotIn("review_note", app.metadata)
        self.assertNotIn("reviewed_by", app.metadata)
        self.assertEqual(app.metadata["decision_note"], "old note only")
        self.assertEqual(app.metadata["decided_by_display"], "old reviewer only")
