from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import connection


def is_case_sensitive_collation(collation: str) -> bool:
    normalized = collation.lower()
    return normalized.endswith("_bin") or "_as_cs" in normalized


class Command(BaseCommand):
    help = "检查目标 MySQL 是否满足 Big Apple Live OS 的迁移和运行要求。"

    def handle(self, *args, **options):
        if connection.vendor != "mysql":
            raise CommandError(
                f"当前数据库后端是 {connection.vendor}，请通过 MySQL 本地配置运行此命令。"
            )

        connection.ensure_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    VERSION(),
                    @@default_storage_engine,
                    @@character_set_database,
                    @@collation_database,
                    @@sql_mode,
                    @@transaction_isolation
                """
            )
            (
                version,
                default_engine,
                database_charset,
                database_collation,
                sql_mode,
                isolation_level,
            ) = cursor.fetchone()
            cursor.execute(
                """
                SELECT TABLE_NAME, ENGINE
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = DATABASE()
                  AND ENGINE IS NOT NULL
                  AND ENGINE <> 'InnoDB'
                ORDER BY TABLE_NAME
                """
            )
            non_innodb_tables = list(cursor.fetchall())
            cursor.execute(
                """
                SELECT TABLE_NAME, TABLE_COLLATION
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_COLLATION IS NOT NULL
                ORDER BY TABLE_NAME
                """
            )
            table_collations = list(cursor.fetchall())

        failures: list[str] = []
        warnings: list[str] = []
        major_version = int(str(version).split(".", 1)[0])

        if major_version < 8:
            failures.append(f"MySQL 版本必须为 8.0 或更高，当前为 {version}。")
        if str(default_engine).lower() != "innodb":
            failures.append(f"默认存储引擎必须为 InnoDB，当前为 {default_engine}。")
        if str(database_charset).lower() != "utf8mb4":
            failures.append(f"数据库字符集必须为 utf8mb4，当前为 {database_charset}。")
        if not is_case_sensitive_collation(str(database_collation)):
            failures.append(
                f"数据库排序规则必须区分大小写，当前为 {database_collation}；"
                "建议使用 utf8mb4_0900_as_cs。"
            )
        if "STRICT_TRANS_TABLES" not in str(sql_mode) and "STRICT_ALL_TABLES" not in str(sql_mode):
            failures.append("MySQL sql_mode 必须启用 STRICT_TRANS_TABLES 或 STRICT_ALL_TABLES。")
        if str(isolation_level).upper().replace("_", "-") != "READ-COMMITTED":
            failures.append(f"事务隔离级别必须为 READ-COMMITTED，当前为 {isolation_level}。")

        if non_innodb_tables:
            failures.append(
                "以下表不是 InnoDB：" + ", ".join(f"{name}({engine})" for name, engine in non_innodb_tables)
            )
        non_case_sensitive_tables = [
            (name, collation)
            for name, collation in table_collations
            if not is_case_sensitive_collation(str(collation))
        ]
        if non_case_sensitive_tables:
            failures.append(
                "以下表使用不区分大小写的排序规则："
                + ", ".join(f"{name}({collation})" for name, collation in non_case_sensitive_tables)
            )

        feature_checks = [
            ("事务", connection.features.supports_transactions),
            ("SELECT FOR UPDATE", connection.features.has_select_for_update),
            ("JSONField", connection.features.supports_json_field),
        ]
        for label, supported in feature_checks:
            if not supported:
                failures.append(f"当前 MySQL 后端不支持必需能力：{label}。")

        if getattr(connection, "mysql_is_mariadb", False):
            warnings.append("当前服务识别为 MariaDB；本项目本轮迁移目标是 MySQL 8，需要单独评估。")

        self.stdout.write(f"MySQL 版本：{version}")
        self.stdout.write(f"默认引擎：{default_engine}")
        self.stdout.write(f"数据库字符集：{database_charset}")
        self.stdout.write(f"数据库排序规则：{database_collation}")
        self.stdout.write(f"事务隔离级别：{isolation_level}")
        for warning in warnings:
            self.stdout.write(self.style.WARNING(f"警告：{warning}"))
        for failure in failures:
            self.stdout.write(self.style.ERROR(f"不满足：{failure}"))

        if failures:
            raise CommandError("MySQL 就绪检查未通过，请修正以上问题后再迁移数据。")

        self.stdout.write(self.style.SUCCESS("MySQL 就绪检查通过，可以进入建表和数据导入阶段。"))
