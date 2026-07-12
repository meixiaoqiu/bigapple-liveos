from __future__ import annotations

from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from worlds.lifecycle import validate_world_database_alias, get_world_or_error
from worlds.models import WorldRegistry


class Command(BaseCommand):
    help = "Run Django migrations against the database registered for one active world."

    def add_arguments(self, parser):
        parser.add_argument("world_id")
        parser.add_argument("--noinput", action="store_true")

    def handle(self, *args, **options):
        world = get_world_or_error(options["world_id"])
        if world.status != WorldRegistry.Status.ACTIVE:
            raise CommandError(f"World is not active: {world.world_id} ({world.status})")
        database_alias = validate_world_database_alias(world.database_alias)
        call_command(
            "migrate",
            database=database_alias,
            interactive=not options["noinput"],
            stdout=self.stdout,
            stderr=self.stderr,
        )
        self._ensure_world_session_table(database_alias, interactive=not options["noinput"])
        self.stdout.write(
            self.style.SUCCESS(f"migrated: world_id={world.world_id}, database_alias={database_alias}")
        )

    def _ensure_world_session_table(self, database_alias: str, *, interactive: bool) -> None:
        connection = connections[database_alias]
        session_table = Session._meta.db_table
        if session_table in connection.introspection.table_names():
            return

        self.stdout.write(
            self.style.WARNING(
                f"{session_table} is missing on {database_alias}; repairing sessions migration state."
            )
        )
        call_command(
            "migrate",
            "sessions",
            "zero",
            database=database_alias,
            fake=True,
            interactive=False,
            stdout=self.stdout,
            stderr=self.stderr,
        )
        call_command(
            "migrate",
            "sessions",
            database=database_alias,
            interactive=interactive,
            stdout=self.stdout,
            stderr=self.stderr,
        )
