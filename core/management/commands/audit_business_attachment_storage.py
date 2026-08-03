"""Audit immutable business evidence for one world; only proven orphans may be cleaned."""

from hashlib import sha256

from django.core.files.storage import storages
from django.core.management.base import BaseCommand, CommandError

from core.file_storage.keys import business_attachment_prefix, require_business_attachment_key
from core.models import Attachment
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
    help = "检查一个 world 的权威业务附件；默认 dry-run，只清理无数据库引用对象。"

    def add_arguments(self, parser):
        parser.add_argument("--world-id", required=True)
        parser.add_argument("--clean-orphans", action="store_true")
        parser.add_argument("--verify-hash", action="store_true")

    def handle(self, *args, **options):
        with command_world_context(options["world_id"], command_name="audit_business_attachment_storage") as world:
            if world is None:
                raise CommandError("必须绑定有效 world。")
            storage = storages["business_attachments"]
            referenced = {row.object_key: row for row in Attachment.objects.all()}
            report = {"missing": 0, "mismatch": 0, "orphan": 0, "deleted": 0}
            for key, attachment in referenced.items():
                try:
                    require_business_attachment_key(key, world_id=world.world_id)
                except Exception:
                    report["mismatch"] += 1
                    continue
                if not storage.exists(key):
                    report["missing"] += 1
                    continue
                if storage.size(key) != attachment.byte_size:
                    report["mismatch"] += 1
                if options["verify_hash"]:
                    with storage.open(key, "rb") as handle:
                        if sha256(handle.read()).hexdigest() != attachment.sha256:
                            report["mismatch"] += 1
            for key in _list_keys(storage, business_attachment_prefix(world.world_id)):
                require_business_attachment_key(key, world_id=world.world_id)
                if key not in referenced:
                    report["orphan"] += 1
                    if options["clean_orphans"]:
                        storage.delete(key)
                        report["deleted"] += 1
        self.stdout.write(
            f"业务附件存储检查：world_id={options['world_id']} missing={report['missing']} "
            f"mismatch={report['mismatch']} orphan={report['orphan']} deleted={report['deleted']} "
            f"mode={'clean-orphans' if options['clean_orphans'] else 'dry-run'}"
        )
