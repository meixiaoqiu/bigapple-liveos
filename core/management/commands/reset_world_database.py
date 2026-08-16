from django.core.management.base import BaseCommand, CommandError
from django.db import connections


class Command(BaseCommand):
    help = "删除指定未上线开发数据库中的全部表，以便重新应用干净迁移基线"

    def add_arguments(self, parser):
        parser.add_argument("--database", required=True)
        parser.add_argument("--confirm-reset", action="store_true")

    def handle(self, *args, **options):
        """仅在显式确认后删除目标开发数据库的全部表。"""

        database = options["database"]
        if not options["confirm_reset"]:
            raise CommandError("必须显式提供 --confirm-reset；此操作会不可恢复地删除目标数据库全部表。")

        connection = connections[database]
        if connection.vendor not in {"mysql", "sqlite"}:
            raise CommandError(f"暂不支持重置数据库后端：{connection.vendor}")

        with connection.cursor() as cursor:
            table_names = connection.introspection.table_names(cursor)
            if connection.vendor == "mysql":
                cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
            try:
                for table_name in table_names:
                    quoted_table = connection.ops.quote_name(table_name)
                    cursor.execute(f"DROP TABLE IF EXISTS {quoted_table}")
            finally:
                if connection.vendor == "mysql":
                    cursor.execute("SET FOREIGN_KEY_CHECKS = 1")

        self.stdout.write(self.style.SUCCESS(f"数据库 {database} 的全部表已删除，可重新运行迁移。"))
