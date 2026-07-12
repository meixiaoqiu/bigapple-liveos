from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.models import SimulationRun
from simulation.archive import archive_simulation_run, archive_source_alias
from worlds.lifecycle import get_world_or_error
from worlds.models import WorldRegistry


class Command(BaseCommand):
    help = "Archive a simulation run into immutable raw files and a searchable control-DB snapshot."

    def add_arguments(self, parser):
        parser.add_argument("--world-id", default="simulation0001", help="Simulation world id.")
        parser.add_argument("--run-id", default="", help="SimulationRun id. Defaults to the latest finished run.")
        parser.add_argument("--archive-root", default="", help="Optional archive root directory.")
        parser.add_argument("--simulation-round", type=int, default=0, help="Optional official simulation round number.")
        parser.add_argument("--scenario", default="", help="Optional scenario code, for example zero_start.")
        parser.add_argument("--purpose", default="", help="Official purpose of this simulation run.")
        parser.add_argument("--hypothesis", default="", help="Main hypothesis tested by this simulation run.")
        parser.add_argument("--parameter-summary", default="", help="JSON object summarizing important parameters.")
        parser.add_argument("--public-title", default="", help="Public title for the archived report.")
        parser.add_argument("--public-summary", default="", help="Public summary for the archived report.")
        parser.add_argument("--review-conclusion", default="", help="Human review conclusion after the run.")
        parser.add_argument("--next-run-basis", default="", help="What this run should change in the next run.")
        parser.add_argument(
            "--publication-status",
            choices=["public", "internal", "hidden"],
            default="public",
            help="Publication status for the public archive index.",
        )
        parser.add_argument("--decided-by", default="command:archive_simulation_run", help="Who made this disposition.")
        parser.add_argument("--reason", default="", help="Disposition reason stored with the archive decision.")

    def handle(self, *args, **options):
        world = get_world_or_error(options["world_id"])
        if world.world_type != WorldRegistry.WorldType.SIMULATION:
            raise CommandError(f"Refusing to archive a non-simulation world run: {world.world_id}")
        if world.status != WorldRegistry.Status.ACTIVE:
            raise CommandError(f"World is not active: {world.world_id} ({world.status})")

        run_id = options["run_id"] or self._latest_finished_run_id(archive_source_alias(world.database_alias))
        archive_root = Path(options["archive_root"]) if options["archive_root"] else None
        result = archive_simulation_run(
            world=world,
            run_id=run_id,
            archive_root=archive_root,
            simulation_round=options["simulation_round"] or None,
            scenario=options["scenario"],
            purpose=options["purpose"],
            hypothesis=options["hypothesis"],
            parameter_summary=self._parameter_summary(options["parameter_summary"]),
            public_title=options["public_title"],
            public_summary=options["public_summary"],
            review_conclusion=options["review_conclusion"],
            next_run_basis=options["next_run_basis"],
            publication_status=options["publication_status"],
            decided_by=options["decided_by"],
            disposition_reason=options["reason"],
        )
        if result.created:
            self.stdout.write(
                self.style.SUCCESS(
                    "Simulation snapshot archived: "
                    f"snapshot={result.snapshot.snapshot_id}, "
                    f"round={result.snapshot.simulation_round}, "
                    f"world={world.world_id}, "
                    f"run={run_id}, "
                    f"path={result.snapshot.raw_archive_path}"
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "Simulation snapshot already exists: "
                    f"snapshot={result.snapshot.snapshot_id}, "
                    f"round={result.snapshot.simulation_round}, "
                    f"world={world.world_id}, "
                    f"run={run_id}"
                )
            )

    def _latest_finished_run_id(self, database_alias: str) -> str:
        run = (
            SimulationRun.objects.using(database_alias)
            .exclude(status__in=[SimulationRun.Status.DRAFT, SimulationRun.Status.RUNNING])
            .order_by("-started_at", "run_id")
            .first()
        )
        if run is None:
            raise CommandError("No finished simulation run found. Pass --run-id after running a simulation.")
        return run.run_id

    def _parameter_summary(self, raw_value: str) -> dict[str, object]:
        if not raw_value:
            return {}
        import json

        try:
            value = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise CommandError(f"--parameter-summary must be a JSON object: {exc}") from exc
        if not isinstance(value, dict):
            raise CommandError("--parameter-summary must be a JSON object.")
        return value
