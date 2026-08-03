"""Migrate current avatars from legacy storage locations to world runtime keys."""

from __future__ import annotations

from hashlib import sha256

from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.file_storage.keys import legacy_avatar_prefix, migrate_legacy_avatar_key
from core.models import MemberPublicProfile
from worlds.command_context import command_world_context


class Command(BaseCommand):
    help = "把旧头像对象无损迁移到 <world-id>/runtime/ 布局；默认 dry-run。"

    def add_arguments(self, parser):
        parser.add_argument("--world-id", required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        with command_world_context(options["world_id"], command_name="migrate_avatar_storage_layout") as world:
            if world is None:
                raise CommandError("必须绑定有效 world。")
            report = self._migrate(world.world_id, apply=options["apply"])
        self.stdout.write(
            f"头像布局迁移：world_id={world.world_id} candidates={report['candidates']} "
            f"migrated={report['migrated']} mode={'apply' if options['apply'] else 'dry-run'}"
        )

    def _migrate(self, world_id: str, *, apply: bool) -> dict[str, int]:
        database_alias = MemberPublicProfile.objects.db
        legacy_storage = storages["avatar_legacy_current"]
        target_storage = storages["avatars"]
        profiles = list(
            MemberPublicProfile.objects.using(database_alias)
            .filter(avatar_key__startswith=legacy_avatar_prefix(world_id))
            .only("pk", "avatar_key", "avatar_sha256", "avatar_size")
        )
        report = {"candidates": len(profiles), "migrated": 0}
        if not apply:
            return report

        for profile in profiles:
            old_key = profile.avatar_key
            new_key = migrate_legacy_avatar_key(old_key, world_id=world_id)
            if not legacy_storage.exists(old_key):
                raise CommandError("旧头像对象缺失，已停止迁移。")
            with legacy_storage.open(old_key, "rb") as handle:
                content = handle.read()
            if profile.avatar_size is not None and len(content) != profile.avatar_size:
                raise CommandError("旧头像对象大小与数据库不一致，已停止迁移。")
            if profile.avatar_sha256 and sha256(content).hexdigest() != profile.avatar_sha256:
                raise CommandError("旧头像对象哈希与数据库不一致，已停止迁移。")

            created_new = False
            if target_storage.exists(new_key):
                with target_storage.open(new_key, "rb") as handle:
                    if sha256(handle.read()).hexdigest() != sha256(content).hexdigest():
                        raise CommandError("目标头像对象已存在但内容不一致。")
            else:
                saved_key = target_storage.save(new_key, ContentFile(content))
                if saved_key != new_key:
                    target_storage.delete(saved_key)
                    raise CommandError("存储后端改变了迁移目标 key。")
                created_new = True

            try:
                with transaction.atomic(using=database_alias):
                    locked = MemberPublicProfile.objects.using(database_alias).select_for_update().get(pk=profile.pk)
                    if locked.avatar_key != old_key:
                        raise CommandError("头像引用在迁移期间发生变化。")
                    locked.avatar_key = new_key
                    locked.save(update_fields=["avatar_key", "updated_at"], using=database_alias)
            except Exception:
                if created_new:
                    target_storage.delete(new_key)
                raise
            legacy_storage.delete(old_key)
            report["migrated"] += 1
        return report
