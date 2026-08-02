"""Audit and optionally clean replaceable avatar objects for one world."""

from __future__ import annotations

from datetime import timedelta
from hashlib import sha256

from django.conf import settings
from django.core.files.storage import storages
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.file_storage.keys import (
    avatar_prefix,
    avatar_temporary_prefix,
    require_deletable_avatar_key,
)
from core.models import MemberPublicProfile
from worlds.command_context import command_world_context


def _list_keys(storage, prefix: str) -> list[str]:
    root = prefix.rstrip("/")
    try:
        directories, files = storage.listdir(root)
    except FileNotFoundError:
        return []
    result = [f"{root}/{name}" for name in files]
    for directory in directories:
        result.extend(_list_keys(storage, f"{root}/{directory}/"))
    return result


class Command(BaseCommand):
    help = "检查一个 world 的当前头像与临时对象；默认 dry-run。"

    def add_arguments(self, parser):
        parser.add_argument("--world-id", required=True)
        parser.add_argument("--clean", action="store_true", help="删除已证明无引用或过期的头像当前资产。")
        parser.add_argument("--verify-hash", action="store_true")

    def handle(self, *args, **options):
        with command_world_context(options["world_id"], command_name="audit_avatar_storage") as world:
            if world is None:
                raise CommandError("必须绑定有效 world。")
            report = self._audit(world.world_id, clean=options["clean"], verify_hash=options["verify_hash"])
        self.stdout.write(
            f"头像存储检查：world_id={options['world_id']} "
            f"missing={report['missing']} orphan={report['orphan']} "
            f"expired_temporary={report['expired_temporary']} mismatch={report['mismatch']} "
            f"deleted={report['deleted']} mode={'clean' if options['clean'] else 'dry-run'}"
        )

    def _audit(self, world_id: str, *, clean: bool, verify_hash: bool) -> dict[str, int]:
        avatar_storage = storages["avatars"]
        temporary_storage = storages["avatar_temporary"]
        referenced = {
            row.avatar_key: row
            for row in MemberPublicProfile.objects.exclude(avatar_key="").only(
                "avatar_key", "avatar_sha256", "avatar_size"
            )
        }
        report = {"missing": 0, "orphan": 0, "expired_temporary": 0, "mismatch": 0, "deleted": 0}
        for key, profile in referenced.items():
            try:
                require_deletable_avatar_key(key, world_id=world_id)
            except Exception:
                report["mismatch"] += 1
                continue
            if not avatar_storage.exists(key):
                report["missing"] += 1
                continue
            if profile.avatar_size is not None and avatar_storage.size(key) != profile.avatar_size:
                report["mismatch"] += 1
            if verify_hash:
                with avatar_storage.open(key, "rb") as handle:
                    digest = sha256(handle.read()).hexdigest()
                if digest != profile.avatar_sha256:
                    report["mismatch"] += 1

        for key in _list_keys(avatar_storage, avatar_prefix(world_id)):
            if key not in referenced:
                require_deletable_avatar_key(key, world_id=world_id)
                report["orphan"] += 1
                if clean:
                    avatar_storage.delete(key)
                    report["deleted"] += 1

        cutoff = timezone.now() - timedelta(hours=settings.AVATAR_TEMPORARY_RETENTION_HOURS)
        for key in _list_keys(temporary_storage, avatar_temporary_prefix(world_id)):
            require_deletable_avatar_key(key, world_id=world_id, temporary=True)
            try:
                expired = temporary_storage.get_modified_time(key) < cutoff
            except (AttributeError, NotImplementedError):
                expired = False
            if expired:
                report["expired_temporary"] += 1
                if clean:
                    temporary_storage.delete(key)
                    report["deleted"] += 1
        return report
