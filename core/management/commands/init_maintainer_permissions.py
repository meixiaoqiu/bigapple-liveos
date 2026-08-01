"""初始化典守者的基础权限与角色。"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from core.finance_setup import ensure_finance_roles
from core.governance_setup import ensure_maintainer_role
from worlds.command_context import command_world_context, command_world_label


class Command(BaseCommand):
    help = "创建典守者的基础权限、角色和角色权限绑定。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--world-id",
            help="目标世界。运行时启用世界数据库路由后，直接执行本命令必须显式提供。",
        )

    def handle(self, *args, **options):
        with command_world_context(options.get("world_id"), command_name="init_maintainer_permissions") as world:
            result = ensure_maintainer_role()
            finance_result = ensure_finance_roles()

            self.stdout.write(
                self.style.SUCCESS(
                    "已初始化典守者权限："
                    f"world_id={command_world_label(world)}, "
                    f"permissions_created={result['permissions_created']}, "
                    f"role_created={result['role_created']}, "
                    f"role_permissions_created={result['role_permissions_created']}, "
                    f"finance_permissions_created={finance_result['permissions_created']}, "
                    f"finance_role_permissions_created={finance_result['role_permissions_created']}"
                )
            )
