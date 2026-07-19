"""Initialize baseline governance permissions and administrator role."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from core.finance_setup import ensure_finance_roles
from core.governance_setup import ensure_governance_admin_role
from worlds.command_context import command_world_context, command_world_label


class Command(BaseCommand):
    help = "Create baseline governance permissions, organization, role, and role-permission bindings."

    def add_arguments(self, parser):
        parser.add_argument(
            "--world-id",
            help="目标 world。运行时启用 world 数据库路由后，直接执行本命令必须显式提供。",
        )

    def handle(self, *args, **options):
        with command_world_context(options.get("world_id"), command_name="init_governance_permissions") as world:
            result = ensure_governance_admin_role()
            finance_result = ensure_finance_roles()

            self.stdout.write(
                self.style.SUCCESS(
                    "Initialized governance permissions: "
                    f"world_id={command_world_label(world)}, "
                    f"permissions_created={result['permissions_created']}, "
                    f"organization_created={result['organization_created']}, "
                    f"role_created={result['role_created']}, "
                    f"role_permissions_created={result['role_permissions_created']}, "
                    f"finance_permissions_created={finance_result['permissions_created']}, "
                    f"finance_role_permissions_created={finance_result['role_permissions_created']}"
                )
            )
