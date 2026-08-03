"""Safe Put/Head/Get/Delete probe for the business attachment storage alias."""

from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.management.base import BaseCommand, CommandError

from core.file_storage.keys import new_business_attachment_key, require_business_attachment_key
from core.management.commands.probe_avatar_storage import _safe_storage_error
from worlds.command_context import command_world_context


class Command(BaseCommand):
    help = "验证业务附件对象存储基础操作，不输出 endpoint、bucket、key 或内容。"

    def add_arguments(self, parser):
        parser.add_argument("--world-id", required=True)

    def handle(self, *args, **options):
        with command_world_context(options["world_id"], command_name="probe_business_attachment_storage") as world:
            if world is None:
                raise CommandError("必须绑定有效 world。")
            storage = storages["business_attachments"]
            key = new_business_attachment_key(world.world_id)
            payload = b"big-apple-business-attachment-probe"
            saved = ""
            try:
                saved = storage.save(key, ContentFile(payload))
                if saved != key or not storage.exists(key) or storage.size(key) != len(payload):
                    raise CommandError("业务附件存储探针校验失败。")
                with storage.open(key, "rb") as handle:
                    if handle.read() != payload:
                        raise CommandError("业务附件存储探针读取内容不一致。")
            except CommandError:
                raise
            except Exception as exc:
                raise CommandError(f"业务附件存储探针失败：{_safe_storage_error(exc)}") from exc
            finally:
                if saved:
                    try:
                        storage.delete(require_business_attachment_key(saved, world_id=world.world_id))
                    except Exception as exc:
                        raise CommandError(f"业务附件存储探针清理失败：{_safe_storage_error(exc)}") from exc
        self.stdout.write(self.style.SUCCESS(f"业务附件存储探针通过：world_id={options['world_id']}"))
