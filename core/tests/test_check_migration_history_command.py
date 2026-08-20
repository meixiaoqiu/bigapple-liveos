from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.migrations.exceptions import InconsistentMigrationHistory
from django.test import SimpleTestCase


class CheckMigrationHistoryCommandTests(SimpleTestCase):
    @patch("core.management.commands.check_migration_history.MigrationExecutor")
    def test_consistent_history_passes(self, executor_class):
        output = StringIO()

        call_command("check_migration_history", stdout=output)

        executor_class.return_value.loader.check_consistent_history.assert_called_once()
        self.assertIn("迁移历史一致", output.getvalue())

    @patch("core.management.commands.check_migration_history.MigrationExecutor")
    def test_inconsistent_history_emits_dedicated_marker(self, executor_class):
        executor_class.return_value.loader.check_consistent_history.side_effect = (
            InconsistentMigrationHistory("core.0003 在依赖 core.0002 之前应用")
        )

        with self.assertRaisesMessage(CommandError, "INCONSISTENT_MIGRATION_HISTORY_DETECTED"):
            call_command("check_migration_history")

    @patch("core.management.commands.check_migration_history.MigrationExecutor")
    def test_other_database_errors_are_not_relabelled(self, executor_class):
        executor_class.side_effect = RuntimeError("数据库连接失败")

        with self.assertRaisesMessage(RuntimeError, "数据库连接失败"):
            call_command("check_migration_history")
