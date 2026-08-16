from unittest.mock import MagicMock

from django.test import SimpleTestCase

from core.legacy_proposal_schema import find_legacy_proposal_schema


class LegacyProposalSchemaTests(SimpleTestCase):
    def test_reports_legacy_table_and_columns(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        connection.introspection.table_names.return_value = [
            "core_proposal",
            "core_roleassignment",
        ]
        source_column = MagicMock()
        source_column.name = "source_proposal_id"
        connection.introspection.get_table_description.return_value = [source_column]

        findings = find_legacy_proposal_schema(connection)

        self.assertEqual(
            findings,
            ["表 core_proposal", "字段 core_roleassignment.source_proposal_id"],
        )

    def test_accepts_clean_schema(self):
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = MagicMock()
        connection.introspection.table_names.return_value = ["core_roleassignment"]
        current_column = MagicMock()
        current_column.name = "source_type"
        connection.introspection.get_table_description.return_value = [current_column]

        self.assertEqual(find_legacy_proposal_schema(connection), [])
