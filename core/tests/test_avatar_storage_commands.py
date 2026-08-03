from io import StringIO
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.management import call_command
from django.test import TestCase
from botocore.exceptions import ClientError

from core.file_storage.keys import avatar_prefix
from core.management.commands.audit_avatar_storage import Command as AuditCommand
from core.models import MemberPublicProfile
from core.tests.helpers import create_member
from worlds.models import WorldRegistry


class AvatarStorageCommandTests(TestCase):
    databases = {"default", "realworld"}

    def setUp(self):
        for alias in ("avatars", "avatar_temporary", "avatar_legacy_current", "avatar_legacy_temporary"):
            storages._storages.pop(alias, None)
        WorldRegistry.objects.update_or_create(
            world_id="realworld",
            defaults={
                "name": "真实世界",
                "world_type": WorldRegistry.WorldType.REAL,
                "database_alias": "realworld",
                "database_name": "test-realworld",
                "status": WorldRegistry.Status.ACTIVE,
            },
        )

    def test_probe_client_error_diagnostics_do_not_expose_request_details(self):
        from core.management.commands.probe_avatar_storage import _safe_storage_error

        exc = ClientError(
            {
                "Error": {"Code": "AccessDenied", "Message": "private bucket name"},
                "ResponseMetadata": {"HTTPStatusCode": 403},
            },
            "PutObject",
        )
        diagnostic = _safe_storage_error(exc)
        self.assertEqual(diagnostic, "ClientError code=AccessDenied http_status=403")
        self.assertNotIn("private bucket name", diagnostic)

    def test_probe_uses_temporary_prefix_and_cleans_its_object(self):
        output = StringIO()
        call_command("probe_avatar_storage", world_id="realworld", stdout=output)
        self.assertIn("头像存储探针通过", output.getvalue())
        self.assertEqual(storages["avatar_temporary"].listdir("realworld/runtime/temporary/avatar-uploads")[1], [])

    def test_legacy_layout_migration_preserves_content_and_switches_reference(self):
        member = create_member(member_no="mem-layout-migration")
        content = b"legacy-webp"
        old_key = "worlds/realworld/current-assets/avatars/legacy.webp"
        storages["avatar_legacy_current"].save(old_key, ContentFile(content))
        profile = MemberPublicProfile.objects.create(
            member=member,
            avatar_key=old_key,
            avatar_sha256=__import__("hashlib").sha256(content).hexdigest(),
            avatar_size=len(content),
        )

        call_command("migrate_avatar_storage_layout", world_id="realworld", apply=True)

        profile.refresh_from_db()
        self.assertEqual(profile.avatar_key, "realworld/runtime/current-assets/avatars/legacy.webp")
        self.assertTrue(storages["avatars"].exists(profile.avatar_key))
        self.assertFalse(storages["avatar_legacy_current"].exists(old_key))

    def test_legacy_layout_migration_is_idempotent(self):
        call_command("migrate_avatar_storage_layout", world_id="realworld", apply=True)
        call_command("migrate_avatar_storage_layout", world_id="realworld", apply=True)

    def test_legacy_layout_migration_dry_run_changes_nothing(self):
        member = create_member(member_no="mem-layout-dry-run")
        content = b"legacy-webp"
        old_key = "worlds/realworld/current-assets/avatars/dry-run.webp"
        new_key = "realworld/runtime/current-assets/avatars/dry-run.webp"
        storages["avatar_legacy_current"].save(old_key, ContentFile(content))
        profile = MemberPublicProfile.objects.create(
            member=member,
            avatar_key=old_key,
            avatar_sha256=__import__("hashlib").sha256(content).hexdigest(),
            avatar_size=len(content),
        )

        call_command("migrate_avatar_storage_layout", world_id="realworld")

        profile.refresh_from_db()
        self.assertEqual(profile.avatar_key, old_key)
        self.assertTrue(storages["avatar_legacy_current"].exists(old_key))
        self.assertFalse(storages["avatars"].exists(new_key))

    def test_legacy_layout_migration_compensates_when_database_switch_fails(self):
        member = create_member(member_no="mem-layout-compensation")
        content = b"legacy-webp"
        old_key = "worlds/realworld/current-assets/avatars/compensation.webp"
        new_key = "realworld/runtime/current-assets/avatars/compensation.webp"
        storages["avatar_legacy_current"].save(old_key, ContentFile(content))
        profile = MemberPublicProfile.objects.create(
            member=member,
            avatar_key=old_key,
            avatar_sha256=__import__("hashlib").sha256(content).hexdigest(),
            avatar_size=len(content),
        )

        with patch.object(MemberPublicProfile, "save", side_effect=RuntimeError("database down")):
            with self.assertRaises(RuntimeError):
                call_command("migrate_avatar_storage_layout", world_id="realworld", apply=True)

        profile.refresh_from_db()
        self.assertEqual(profile.avatar_key, old_key)
        self.assertTrue(storages["avatar_legacy_current"].exists(old_key))
        self.assertFalse(storages["avatars"].exists(new_key))

    def test_audit_dry_run_reports_orphan_without_deleting(self):
        storage = storages["avatars"]
        key = f"{avatar_prefix('realworld')}orphan.webp"
        storage.save(key, ContentFile(b"orphan"))
        report = AuditCommand()._audit("realworld", clean=False, verify_hash=False)
        self.assertEqual(report["orphan"], 1)
        self.assertTrue(storage.exists(key))

    def test_audit_clean_deletes_only_unreferenced_current_avatar(self):
        storage = storages["avatars"]
        orphan = f"{avatar_prefix('realworld')}orphan.webp"
        current = f"{avatar_prefix('realworld')}current.webp"
        storage.save(orphan, ContentFile(b"orphan"))
        storage.save(current, ContentFile(b"current"))
        member = create_member(member_no="mem-storage-audit")
        MemberPublicProfile.objects.create(
            member=member,
            avatar_key=current,
            avatar_sha256="e" * 64,
            avatar_size=7,
        )
        report = AuditCommand()._audit("realworld", clean=True, verify_hash=False)
        self.assertEqual(report["deleted"], 1)
        self.assertFalse(storage.exists(orphan))
        self.assertTrue(storage.exists(current))
