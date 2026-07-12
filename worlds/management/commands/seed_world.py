from __future__ import annotations

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from live_os.demo_seed.zero_start import seed_zero_start
from worlds.context import context_from_registry
from worlds.lifecycle import get_world_or_error
from worlds.models import WorldRegistry
from worlds.state import reset_current_world, set_current_world


class Command(BaseCommand):
    help = "Seed an active simulation world from a safe, idempotent template."

    def add_arguments(self, parser):
        parser.add_argument("world_id")
        parser.add_argument(
            "--template",
            choices=["demo", "zero_start"],
            default="demo",
            help="World seed template. Use zero_start for a founder-only baseline.",
        )

    def handle(self, *args, **options):
        world = get_world_or_error(options["world_id"])
        if world.status != WorldRegistry.Status.ACTIVE:
            raise CommandError(f"World is not active: {world.world_id} ({world.status})")
        if world.world_type != WorldRegistry.WorldType.SIMULATION:
            raise CommandError(f"Refusing to seed non-simulation world: {world.world_id}")

        template = options["template"]
        world_context = context_from_registry(world)
        database_alias = self._effective_world_alias(world_context.database_alias)

        token = set_current_world(world_context)
        try:
            if template == "demo":
                call_command("seed_demo", stdout=self.stdout, stderr=self.stderr)
            elif template == "zero_start":
                seed_zero_start()
            else:  # pragma: no cover - argparse choices prevent this.
                raise CommandError(f"Unsupported world seed template: {template}")
        finally:
            reset_current_world(token)

        self.stdout.write(
            self.style.SUCCESS(
                f"seeded: world_id={world.world_id}, template={template}, database_alias={database_alias}"
            )
        )

    def _effective_world_alias(self, database_alias: str) -> str:
        if not getattr(settings, "WORLD_DATABASE_ROUTING_ENABLED", True):
            return "default"
        if database_alias not in settings.DATABASES:
            raise CommandError(f"World database alias is not configured: {database_alias}")
        return database_alias
