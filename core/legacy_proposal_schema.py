from __future__ import annotations

from django.db.backends.base.base import BaseDatabaseWrapper


LEGACY_TABLES = frozenset(
    {
        "core_proposal",
        "core_proposalvote",
        "core_proposalexecution",
        "core_electorateruletemplate",
        "core_electorateruleversion",
        "core_proposaltypeelectoraterule",
    }
)

LEGACY_COLUMNS = {
    "core_memberapplication": frozenset({"admission_proposal_id"}),
    "core_roleassignment": frozenset({"source_proposal_id", "source_proposal_execution_id"}),
    "core_task": frozenset({"source_proposal_id", "source_proposal_execution_id"}),
    "core_credentialgrant": frozenset({"source_proposal_id", "source_proposal_execution_id"}),
    "core_communityfeedback": frozenset({"linked_proposal_id"}),
}


def find_legacy_proposal_schema(connection: BaseDatabaseWrapper) -> list[str]:
    """返回数据库中仍属于旧提案系统的表和字段。"""

    with connection.cursor() as cursor:
        table_names = set(connection.introspection.table_names(cursor))
        findings = [f"表 {name}" for name in sorted(table_names & LEGACY_TABLES)]
        for table_name, legacy_columns in LEGACY_COLUMNS.items():
            if table_name not in table_names:
                continue
            description = connection.introspection.get_table_description(cursor, table_name)
            column_names = {column.name for column in description}
            findings.extend(
                f"字段 {table_name}.{column_name}"
                for column_name in sorted(column_names & legacy_columns)
            )
    return findings
