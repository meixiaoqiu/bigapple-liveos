"""重置一个仿真 world 的角色与权限基线。"""

from __future__ import annotations

import json
from io import StringIO

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.test.utils import override_settings

from core.authorization_services import openfga_context_for_world_kind
from core.openfga_client import OpenFGAClient, OpenFGARequestError
from core.role_baseline import clear_role_permission_baseline, load_role_permission_baseline
from worlds.command_context import command_world_context
from worlds.models import WorldRegistry


class Command(BaseCommand):
    help = "重置明确 simulation world 的角色与权限事实，并装载新制度最小基线。"

    def add_arguments(self, parser):
        parser.add_argument("--world-id", required=True)
        parser.add_argument("--format", choices=("text", "json"), default="text")

    def handle(self, *args, **options):
        world_id = str(options["world_id"]).strip()
        world = WorldRegistry.objects.using("default").filter(world_id=world_id).first()
        if world is None:
            raise CommandError(f"World 不存在：{world_id}")
        if world.world_type != WorldRegistry.WorldType.SIMULATION:
            raise CommandError(f"仅允许重置 simulation world：{world_id}")
        if world.status != WorldRegistry.Status.ACTIVE:
            raise CommandError(f"World 未启用：{world_id}")

        with command_world_context(world_id, command_name="reset_role_permission_baseline"):
            openfga_status = self._preflight_openfga()
            cleared = clear_role_permission_baseline()
            # OpenFGA tuple 只能在完整 Django 权威基线建立后重建。此处仅在受控
            # 初始化阶段依据新建的 Django 事实校验典守能力，避免专业资格装载
            # 依赖尚未重建的旧 tuple。
            with override_settings(BIG_APPLE_AUTHORIZATION_BACKEND="legacy"):
                seeded = load_role_permission_baseline()
            if openfga_status != "SKIP:not_configured":
                openfga_status = self._rebuild_openfga(world_id)

        report = {
            "world_id": world_id,
            "result": "PASS",
            "cleared": cleared,
            "seeded": seeded,
            "openfga": openfga_status,
        }
        if options["format"] == "json":
            self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
            return
        self.stdout.write(
            self.style.SUCCESS(
                "角色与权限基线：PASS "
                f"world_id={world_id} roles={seeded['roles']} "
                f"assignments={seeded['role_assignments']} openfga={openfga_status}"
            )
        )

    def _preflight_openfga(self) -> str:
        context = openfga_context_for_world_kind("sim")
        if not context.store_id and not context.authorization_model_id:
            return "SKIP:not_configured"
        if not context.store_id or not context.authorization_model_id:
            raise CommandError("OpenFGA 配置不完整；角色与权限基线未作任何修改。")

        try:
            OpenFGAClient(context.api_url).check(
                store_id=context.store_id,
                authorization_model_id=context.authorization_model_id,
                user="member:role-baseline-preflight",
                relation="covenanter",
                object_=context.platform_object,
            )
        except OpenFGARequestError as exc:
            raise CommandError(f"OpenFGA 新模型预检失败；角色与权限基线未作任何修改。{exc}") from exc
        return "PASS:ready"

    def _rebuild_openfga(self, world_id: str) -> str:
        output = StringIO()
        call_command(
            "openfga_rebuild_tuples",
            "--world-id",
            world_id,
            "--world-kind",
            "sim",
            stdout=output,
        )
        return "PASS:rebuilt"
