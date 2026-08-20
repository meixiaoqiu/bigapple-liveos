from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.db.migrations.exceptions import InconsistentMigrationHistory
from django.db.migrations.executor import MigrationExecutor


class Command(BaseCommand):
    help = "在执行迁移前检查数据库迁移历史是否符合当前依赖图"

    def add_arguments(self, parser):
        parser.add_argument("--database", default="default")

    def handle(self, *args, **options):
        database = options["database"]
        connection = connections[database]
        try:
            executor = MigrationExecutor(connection)
            executor.loader.check_consistent_history(connection)
        except InconsistentMigrationHistory as exc:
            raise CommandError(
                "INCONSISTENT_MIGRATION_HISTORY_DETECTED\n"
                f"数据库 {database} 的迁移历史与当前代码依赖图不一致：{exc}"
            ) from exc

        self.stdout.write(self.style.SUCCESS(f"数据库 {database} 的迁移历史一致。"))
