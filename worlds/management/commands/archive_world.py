from __future__ import annotations

from django.core.management.base import BaseCommand

from worlds.lifecycle import archive_world_registry


class Command(BaseCommand):
    help = "Archive a non-real world and prevent normal world-scoped access."

    def add_arguments(self, parser):
        parser.add_argument("world_id")

    def handle(self, *args, **options):
        world, changed = archive_world_registry(options["world_id"])
        state = "archived" if changed else "already_archived"
        self.stdout.write(
            self.style.SUCCESS(
                f"{state}: world_id={world.world_id}, database_alias={world.database_alias}, status={world.status}"
            )
        )
