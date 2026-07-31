"""输出当前世界的只读角色、权限与任命盘点。"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from core.role_audit import build_role_inventory
from worlds.command_context import command_world_context


class Command(BaseCommand):
    help = "只读盘点当前世界的角色、权限、任命来源和前置条件符合情况。"

    def add_arguments(self, parser):
        parser.add_argument("--world-id", default="", help="要盘点的世界；启用世界路由时必须提供。")
        parser.add_argument(
            "--format",
            choices=("text", "json"),
            default="text",
            help="输出格式，默认为 text。",
        )

    def handle(self, *args, **options):
        with command_world_context(options["world_id"], command_name="audit_role_catalog") as world:
            report = build_role_inventory(world=world)

        if options["format"] == "json":
            self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
            return
        self._write_text_report(report)

    def _write_text_report(self, report: dict) -> None:
        scope = report["scope"]
        summary = report["summary"]
        self.stdout.write(
            "角色盘点："
            f"world_id={scope['world_id']} world_type={scope['world_type']} "
            f"database_alias={scope['database_alias']}"
        )
        self.stdout.write(
            "汇总："
            f"内置定义={summary['builtin_role_definitions']} "
            f"数据库角色={summary['database_roles']} "
            f"报告角色={summary['reported_roles']} "
            f"任命总数={summary['role_assignments']} "
            f"有效任命={summary['active_role_assignments']}"
        )
        for entry in report["roles"]:
            role = entry["role"]
            catalog = entry["catalog"]
            counts = entry["assignment_counts"]
            compliance = entry["prerequisite_compliance"]
            permissions = entry["permission_bindings"]
            self.stdout.write(
                "角色："
                f"{role['organization']} / {role['name']} "
                f"存在={role['exists']} 状态={role['status']} "
                f"维度={catalog['dimension']} "
                f"当前有效任命={counts['currently_effective']} "
                f"总任命={counts['total']}"
            )
            self.stdout.write(
                "  前置条件："
                f"要求正式成员={compliance['requires_formal_member']} "
                f"缺失={compliance['missing_formal_member']} "
                f"已停用={compliance['disabled_member']} "
                f"账号停用={compliance['inactive_user']}"
            )
            self.stdout.write(
                "  任命来源："
                + " ".join(f"{source}={count}" for source, count in counts["by_source"].items())
            )
            self.stdout.write(
                "  权限："
                + ("、".join(binding["permission_code"] for binding in permissions) or "无")
            )

        self.stdout.write("角色任命创建路径：")
        for path in report["assignment_creation_paths"]:
            self.stdout.write(
                f"- {path['id']}：{path['category']}；"
                f"入口 {'、'.join(path['entry_points'])}；"
                f"直接事实 {'、'.join(path['direct_role_facts']) or '无'}；"
                f"后续任务 {path['follow_up_task']}。"
            )

        self.stdout.write("角色展示与载荷界面：")
        for surface in report["presentation_surfaces"]:
            self.stdout.write(
                f"- {surface['id']}：{surface['surface']}；"
                f"{surface['current_behavior']}；"
                f"需先更新技术契约 {'是' if surface['requires_contract_update'] else '否'}；"
                f"后续任务 {surface['change_target']}。"
            )
