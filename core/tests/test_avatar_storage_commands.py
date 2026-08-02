from io import StringIO

from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.management import call_command
from django.test import TestCase

from core.file_storage.keys import avatar_prefix
from core.management.commands.audit_avatar_storage import Command as AuditCommand
from core.models import MemberPublicProfile
from core.tests.helpers import create_member
from worlds.models import WorldRegistry


class AvatarStorageCommandTests(TestCase):
    databases = {"default", "realworld"}

    def setUp(self):
        for alias in ("avatars", "avatar_temporary"):
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

    def test_probe_uses_temporary_prefix_and_cleans_its_object(self):
        output = StringIO()
        call_command("probe_avatar_storage", world_id="realworld", stdout=output)
        self.assertIn("头像存储探针通过", output.getvalue())
        self.assertEqual(storages["avatar_temporary"].listdir("worlds/realworld/temporary/avatar-uploads")[1], [])

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
