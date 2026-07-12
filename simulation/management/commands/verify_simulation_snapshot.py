from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from core.models import SimulationSnapshot
from simulation.archive import verify_simulation_snapshot


class Command(BaseCommand):
    help = "Verify a simulation snapshot raw archive package and normalized control-DB index."

    def add_arguments(self, parser):
        parser.add_argument("snapshot_id", help="SimulationSnapshot id, for example snapshot-xxxxxxxxxxxx.")

    def handle(self, *args, **options):
        snapshot_id = options["snapshot_id"]
        try:
            result = verify_simulation_snapshot(snapshot_id)
        except SimulationSnapshot.DoesNotExist as exc:
            raise CommandError(f"Simulation snapshot not found: {snapshot_id}") from exc

        for warning in result.warnings:
            self.stdout.write(self.style.WARNING(f"WARNING: {warning}"))
        if not result.ok:
            raise CommandError("Simulation snapshot verification failed:\n" + "\n".join(result.errors))

        self.stdout.write(
            self.style.SUCCESS(
                "Simulation snapshot verified: "
                f"snapshot={result.snapshot.snapshot_id}, "
                f"raw_models={result.raw_model_count}, "
                f"normalized_items={result.normalized_item_count}"
            )
        )
