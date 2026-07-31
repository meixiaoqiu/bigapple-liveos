from __future__ import annotations

from importlib import import_module
from unittest.mock import Mock

from django.test import SimpleTestCase


class RoleMigrationTests(SimpleTestCase):
    def test_legacy_proposal_guard_blocks_schema_migration(self) -> None:
        migration = import_module("core.migrations.0039_replace_proposal_voter_scope")
        proposal_model = Mock()
        proposal_model.objects.exists.return_value = True
        apps = Mock()
        apps.get_model.return_value = proposal_model

        with self.assertRaisesRegex(RuntimeError, "旧制度提案数据"):
            migration.reject_legacy_proposal_data(apps, schema_editor=None)

    def test_legacy_proposal_guard_allows_clean_baseline(self) -> None:
        migration = import_module("core.migrations.0039_replace_proposal_voter_scope")
        proposal_model = Mock()
        proposal_model.objects.exists.return_value = False
        apps = Mock()
        apps.get_model.return_value = proposal_model

        migration.reject_legacy_proposal_data(apps, schema_editor=None)
