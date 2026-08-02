"""Write/read/head/delete probe for the configured private avatar storage."""

from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.management.base import BaseCommand, CommandError

from core.file_storage.keys import new_temporary_key, require_deletable_avatar_key
from worlds.command_context import command_world_context


class Command(BaseCommand):
    help = "验证头像对象存储的基础操作，不输出 endpoint 凭据或对象内容。"

    def add_arguments(self, parser):
        parser.add_argument("--world-id", required=True)

    def handle(self, *args, **options):
        with command_world_context(options["world_id"], command_name="probe_avatar_storage") as world:
            if world is None:
                raise CommandError("必须绑定有效 world。")
            storage = storages["avatar_temporary"]
            key = new_temporary_key(world.world_id)
            payload = b"big-apple-avatar-storage-probe"
            saved = ""
            try:
                saved = storage.save(key, ContentFile(payload))
                if saved != key:
                    raise CommandError("存储后端改变了随机对象 key。")
                if not storage.exists(key):
                    raise CommandError("Put 后 Head/exists 未发现测试对象。")
                if storage.size(key) != len(payload):
                    raise CommandError("测试对象大小不一致。")
                with storage.open(key, "rb") as handle:
                    if handle.read() != payload:
                        raise CommandError("Get 返回的测试对象内容不一致。")
            except CommandError:
                raise
            except Exception as exc:
                raise CommandError(f"头像存储探针失败：{type(exc).__name__}") from exc
            finally:
                if saved:
                    try:
                        storage.delete(require_deletable_avatar_key(saved, world_id=world.world_id, temporary=True))
                    except Exception as exc:
                        raise CommandError(f"头像存储探针清理失败：{type(exc).__name__}") from exc
            self.stdout.write(self.style.SUCCESS(f"头像存储探针通过：world_id={world.world_id}"))
