from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from core.models import SimulationRun
from simulation.disposition import FINISHED_RUN_STATUSES, record_discarded_disposition, source_alias_for_world
from worlds.lifecycle import get_world_or_error
from worlds.models import WorldRegistry


class Command(BaseCommand):
    help = "Mark a finished simulation run as manually discarded, without creating an archive snapshot."

    def add_arguments(self, parser):
        parser.add_argument("--world-id", default="simulation0001", help="Simulation world id.")
        parser.add_argument("--run-id", required=True, help="SimulationRun id to discard.")
        parser.add_argument("--reason", required=True, help="Why this run does not need a permanent snapshot.")
        parser.add_argument("--decided-by", default="command:discard_simulation_run", help="Who made this disposition.")

    def handle(self, *args, **options):
        world = get_world_or_error(options["world_id"])
        if world.world_type != WorldRegistry.WorldType.SIMULATION:
            raise CommandError(f"Refusing to discard a non-simulation world run: {world.world_id}")
        if world.status != WorldRegistry.Status.ACTIVE:
            raise CommandError(f"World is not active: {world.world_id} ({world.status})")

        source_alias = source_alias_for_world(world)
        try:
            run = SimulationRun.objects.using(source_alias).get(run_id=options["run_id"])
        except SimulationRun.DoesNotExist as exc:
            raise CommandError(f"SimulationRun not found: {options['run_id']}") from exc
        if run.status not in FINISHED_RUN_STATUSES:
            raise CommandError(f"Only finished simulation runs can be discarded: {run.run_id} ({run.status})")

        try:
            disposition = record_discarded_disposition(
                world=world,
                run=run,
                reason=options["reason"],
                decided_by=options["decided_by"],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                "Simulation run discarded: "
                f"disposition={disposition.disposition_id}, "
                f"round={disposition.simulation_round}, "
                f"world={world.world_id}, "
                f"run={run.run_id}"
            )
        )
