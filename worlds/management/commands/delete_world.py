from __future__ import annotations

from django.core.management.base import BaseCommand

from worlds.lifecycle import delete_world_registry


class Command(BaseCommand):
    help = "Mark an archived non-real world as deleted in the control database."

    def add_arguments(self, parser):
        parser.add_argument("world_id")

    def handle(self, *args, **options):
        world, changed = delete_world_registry(options["world_id"])
        state = "deleted" if changed else "already_deleted"
        self.stdout.write(
            self.style.SUCCESS(
                f"{state}: world_id={world.world_id}, database_alias={world.database_alias}, status={world.status}. "
                "Physical database dropping is intentionally not performed."
            )
        )
