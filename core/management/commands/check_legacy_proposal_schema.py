from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from core.legacy_proposal_schema import find_legacy_proposal_schema


class Command(BaseCommand):
    help = "在迁移前拒绝仍含旧提案系统表或字段的数据库"

    def add_arguments(self, parser):
        parser.add_argument("--database", default="default")

    def handle(self, *args, **options):
        database = options["database"]
        findings = find_legacy_proposal_schema(connections[database])
        if findings:
            details = "、".join(findings)
            raise CommandError(
                "LEGACY_PROPOSAL_SCHEMA_DETECTED\n"
                "检测到旧提案数据库结构，不能在原库上应用新的干净迁移基线："
                f"{details}。本项目尚未上线，请先按启动脚本给出的命令重置对应数据库。"
            )
        self.stdout.write(self.style.SUCCESS(f"数据库 {database} 未发现旧提案结构。"))
