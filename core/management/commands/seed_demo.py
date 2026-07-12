"""?????? Django Admin ????????"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone
from worlds.command_context import command_world_context, command_world_label

from live_os.demo_seed.capacity import seed_capacity
from live_os.demo_seed.disputes import seed_disputes
from live_os.demo_seed.events import seed_events
from live_os.demo_seed.ledger import seed_ledger
from live_os.demo_seed.members import seed_members
from live_os.demo_seed.project_plan import seed_project_plan
from live_os.demo_seed.resources import seed_resources
from live_os.demo_seed.tasks import seed_tasks


class Command(BaseCommand):
    help = "???????????? Django Admin ??? Live OS ???????"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--world-id",
            help="目标 world。运行时启用 world 数据库路由后，直接执行 seed_demo 必须显式提供。",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        with command_world_context(options.get("world_id"), command_name="seed_demo") as world:
            now = timezone.now()
            created_count = 0
            updated_count = 0

            def mark(result: tuple[Any, bool]) -> Any:
                nonlocal created_count, updated_count
                obj, created = result
                if created:
                    created_count += 1
                else:
                    updated_count += 1
                return obj

            ruleset, _plan_revision, plan_nodes = seed_project_plan(now=now, mark=mark)
            members = seed_members(now=now, mark=mark)
            seed_resources(now=now, mark=mark, ruleset=ruleset)
            tasks = seed_tasks(now=now, mark=mark, ruleset=ruleset, plan_nodes=plan_nodes, members=members)
            seed_events(now=now, mark=mark, members=members, tasks=tasks)
            ledgers = seed_ledger(now=now, mark=mark, ruleset=ruleset, members=members, tasks=tasks)
            seed_disputes(now=now, mark=mark, members=members, tasks=tasks, ledgers=ledgers)
            seed_capacity(now=now, mark=mark, ruleset=ruleset)

            self.stdout.write(
                self.style.SUCCESS(
                    f"Demo seed completed: world_id={command_world_label(world)}, "
                    f"created={created_count}, updated={updated_count}."
                )
            )
