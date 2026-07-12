"""通过 Live OS HTTP API 跑通第一条任务闭环。"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.test import Client, override_settings
from django.utils import timezone

from core.models import Member, Task
from worlds.context import DEFAULT_REALWORLD_ID, context_from_registry
from worlds.lifecycle import get_world_or_error
from worlds.models import WorldRegistry
from worlds.state import reset_current_world, set_current_world


def actor(actor_id: str, display_name: str, actor_type: str = "human_member") -> dict[str, str]:
    return {
        "actor_id": actor_id,
        "actor_type": actor_type,
        "display_name": display_name,
    }


class Command(BaseCommand):
    help = "通过 HTTP API 验证领取、提交、验收、账本和事件闭环。"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--world-id",
            default=DEFAULT_REALWORLD_ID,
            help="要验证的 world ID；默认 realworld。",
        )
        parser.add_argument(
            "--task-id",
            default="",
            help="可选。指定 smoke 任务 ID；默认使用当前时间生成唯一 ID。",
        )
        parser.add_argument(
            "--seed-demo",
            action="store_true",
            help="允许在 realworld 写入幂等演示数据。仿真 world 会自动使用 seed_world。",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        world = self.get_active_world(str(options["world_id"]).strip())
        world_context = context_from_registry(world)
        token = set_current_world(world_context)
        try:
            if world.world_type == WorldRegistry.WorldType.SIMULATION:
                call_command("seed_world", world.world_id, stdout=self.stdout)
            elif options["seed_demo"]:
                if world.world_id != DEFAULT_REALWORLD_ID:
                    raise CommandError(f"Refusing to seed demo data into non-simulation world: {world.world_id}")
                self.stdout.write("Seeding demo data into realworld because --seed-demo was provided.")
                call_command("seed_demo", stdout=self.stdout)

            self.run_workflow(options=options, world_id=world.world_id)
        finally:
            reset_current_world(token)

    def get_active_world(self, world_id: str) -> WorldRegistry:
        world = get_world_or_error(world_id)
        if world.status != WorldRegistry.Status.ACTIVE:
            raise CommandError(f"World is not active: {world.world_id} ({world.status})")
        if getattr(settings, "WORLD_DATABASE_ROUTING_ENABLED", True) and world.database_alias not in settings.DATABASES:
            raise CommandError(f"World database alias is not configured: {world.database_alias}")
        return world

    def run_workflow(self, *, options: dict[str, Any], world_id: str) -> None:
        now = timezone.now()
        task_id = options["task_id"] or timezone.localtime(now).strftime("task-smoke-%Y%m%d%H%M%S")
        member_no = "mem-0001"
        reviewer_id = "member-admin-0001"

        member = Member.objects.filter(member_no=member_no).first()
        reviewer = Member.objects.filter(member_no=reviewer_id).first()
        if member is None:
            raise CommandError(f"缺少演示成员：{member_no}。请先为目标 world 运行 seed_demo 或 seed_world。")
        if reviewer is None:
            raise CommandError(f"缺少演示治理成员：{reviewer_id}。请先为目标 world 运行 seed_demo 或 seed_world。")
        if Task.objects.filter(task_id=task_id).exists():
            raise CommandError(f"任务 {task_id} 已存在。请换一个 --task-id 或使用默认自动生成。")

        member_user = self.ensure_member_user(member)
        reviewer_user = self.ensure_member_user(reviewer)

        Task.objects.create(
            task_id=task_id,
            title="Smoke 流程验证任务",
            task_type=Task.TaskType.COOKING,
            status=Task.Status.OPEN,
            standard_hours=Decimal("1.50"),
            base_points=10,
            role_coefficient=Decimal("1.000"),
            physical_load=Decimal("20"),
            dirty_level=Decimal("15"),
            psychological_load=Decimal("10"),
            urgency=Decimal("30"),
            can_be_delayed=True,
            requires_review=True,
            failure_consequence=Task.FailureConsequence.LOW,
            rule_version="ruleset-v0.1.0",
            created_at=now,
            due_at=now + timedelta(hours=2),
            metadata={"simulation_day": 1, "smoke": True},
        )

        client = Client(SERVER_NAME="localhost")
        api_base = "/api/v0.1"
        self._fixed_world_settings = self.fixed_world_settings(world_id)

        open_tasks = self.get_json(client, f"{api_base}/tasks", {"status": Task.Status.OPEN}, "query open tasks")
        if task_id not in {item["task_id"] for item in open_tasks}:
            raise CommandError(f"开放任务列表中没有找到 {task_id}。")

        client.force_login(member_user)
        claimed = self.post_json(
            client,
            f"{api_base}/tasks/{task_id}/claim",
            {"member_no": member_no},
            "领取任务",
        )
        if claimed["status"] != Task.Status.CLAIMED:
            raise CommandError(f"领取任务后状态异常：{claimed['status']}")

        submitted = self.post_json(
            client,
            f"{api_base}/tasks/{task_id}/submit-labor",
            {
                "member_no": member_no,
                "labor_note": "Smoke 命令自动提交的劳动记录。",
                "evidence_refs": ["smoke-evidence-0001"],
            },
            "提交劳动",
        )
        if submitted["status"] != Task.Status.PENDING_REVIEW:
            raise CommandError(f"提交劳动后状态异常：{submitted['status']}")

        client.force_login(reviewer_user)
        reviewed = self.post_json(
            client,
            f"{api_base}/tasks/{task_id}/review",
            {
                "reviewer": actor(reviewer_id, "开荒队治理成员"),
                "accepted": True,
                "reason": "Smoke 流程验收通过。",
            },
            "验收任务",
        )
        ledger_entries = reviewed["ledger_entries"]
        if reviewed["task"]["status"] != Task.Status.ACCEPTED or len(ledger_entries) != 1:
            raise CommandError("验收结果未产生预期任务状态或积分流水。")

        client.force_login(member_user)
        ledger_list = self.get_json(client, f"{api_base}/ledger-entries", {"member_no": member_no}, "query ledger entries")
        events = self.get_json(client, f"{api_base}/events", {"simulation_day": 1}, "query events")
        summary = self.get_json(client, f"{api_base}/observer/summary", {}, "query observer summary")

        self.stdout.write(
            self.style.SUCCESS(
                "Smoke workflow passed: "
                f"world={world_id}, "
                f"task={task_id}, "
                f"ledger={ledger_entries[0]['ledger_entry_id']}, "
                f"member_ledger_count={len(ledger_list)}, "
                f"day1_event_count={len(events)}, "
                f"observer_day={summary['simulation_day']}"
            )
        )

    def ensure_member_user(self, member: Member):
        user_model = get_user_model()
        user = member.user
        if user is None:
            user, _created = user_model.objects.get_or_create(
                username=member.member_no,
                defaults={"is_active": True, "is_staff": False, "is_superuser": False},
            )
            if not user.is_active:
                user.is_active = True
                user.save(update_fields=["is_active"])
            member.user = user
            member.save(update_fields=["user"])
            return user

        if not user.is_active:
            user.is_active = True
            user.save(update_fields=["is_active"])
        return user

    def fixed_world_settings(self, world_id: str) -> dict[str, object]:
        database_alias = world_id if world_id in settings.DATABASES else "default"
        return {
            "ROOT_URLCONF": "live_os.urls_world",
            "SITE_FIXED_WORLD": True,
            "SITE_WORLD_ID": world_id,
            "SITE_WORLD_TYPE": "simulation" if world_id.startswith("simulation") else "real",
            "SITE_WORLD_DATABASE_ALIAS": database_alias,
            "SITE_WORLD_DATABASE_NAME": str(settings.DATABASES.get(database_alias, {}).get("NAME", "")),
        }

    def get_json(self, client: Client, path: str, query: dict[str, Any], label: str) -> Any:
        with override_settings(**self._fixed_world_settings):
            response = client.get(path, query)
        return self.expect(response, 200, label)

    def post_json(self, client: Client, path: str, payload: dict[str, Any], label: str) -> dict[str, Any]:
        with override_settings(**self._fixed_world_settings):
            response = client.post(path, data=json.dumps(payload), content_type="application/json")
        return self.expect(response, 200, label)

    def expect(self, response: Any, status_code: int, label: str) -> Any:
        if response.status_code != status_code:
            body = response.content.decode("utf-8", errors="replace")
            raise CommandError(f"{label}失败：HTTP {response.status_code}，响应：{body}")
        return response.json()
