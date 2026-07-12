from __future__ import annotations

from django.core.management.base import BaseCommand

from worlds.lifecycle import create_world_registry
from worlds.models import WorldRegistry


class Command(BaseCommand):
    help = "Register or reactivate a configured world database in the control database."

    def add_arguments(self, parser):
        parser.add_argument("world_id")
        parser.add_argument("--name", default="")
        parser.add_argument(
            "--world-type",
            choices=[value for value, _label in WorldRegistry.WorldType.choices],
            default=WorldRegistry.WorldType.SIMULATION,
        )
        parser.add_argument("--database-alias", default="")
        parser.add_argument("--database-name", default="")

    def handle(self, *args, **options):
        world, created = create_world_registry(
            world_id=options["world_id"],
            name=options["name"],
            world_type=options["world_type"],
            database_alias=options["database_alias"] or options["world_id"],
            database_name=options["database_name"],
        )
        state = "created" if created else "updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{state}: world_id={world.world_id}, type={world.world_type}, "
                f"database_alias={world.database_alias}, status={world.status}"
            )
        )
