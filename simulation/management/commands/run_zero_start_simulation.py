from __future__ import annotations

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from core.models import Event, Member, MemberApplication, PartnerApplication, PlanRevision, SimulationFailure, SimulationRun, SimulationTurn
from simulation.disposition import (
    UnresolvedSimulationRunError,
    ensure_no_unresolved_finished_runs,
)
from simulation.zero_start import run_zero_start_recruitment_simulation
from worlds.context import DEFAULT_REALWORLD_ID, context_from_registry
from worlds.lifecycle import get_world_or_error
from worlds.models import WorldRegistry
from worlds.state import reset_current_world, set_current_world


class Command(BaseCommand):
    help = "Run the zero-start hourly recruitment and screening simulation inside one simulation world."

    def add_arguments(self, parser):
        parser.add_argument(
            "--world-id",
            default="simulation0001",
            help="Simulation world id. Defaults to simulation0001.",
        )
        parser.add_argument(
            "--hours",
            type=int,
            default=168,
            help="Virtual hours to advance. Defaults to 168.",
        )
        parser.add_argument(
            "--skip-seed",
            action="store_true",
            help="Use existing zero_start baseline instead of running seed_world first.",
        )

    def handle(self, *args, **options):
        hours = options["hours"]
        if hours <= 0:
            raise CommandError("--hours must be greater than 0.")

        world = self._simulation_world(options["world_id"])
        realworld_before = self._realworld_counts()
        try:
            ensure_no_unresolved_finished_runs(world=world)
        except UnresolvedSimulationRunError as exc:
            raise CommandError(str(exc)) from exc
        if not options["skip_seed"]:
            call_command("seed_world", world.world_id, "--template", "zero_start", stdout=self.stdout, stderr=self.stderr)

        context = context_from_registry(world)
        token = set_current_world(context)
        try:
            before_run_ids = set(SimulationRun.objects.values_list("run_id", flat=True))
            before_runs = len(before_run_ids)
            try:
                result = run_zero_start_recruitment_simulation(hours=hours, ensure_seed=False)
            except PlanRevision.DoesNotExist as exc:
                raise CommandError("Zero-start baseline is missing. Run seed_world with --template zero_start first.") from exc
            run = result["run"]
            if not isinstance(run, SimulationRun):
                raise CommandError("Zero-start engine did not return a SimulationRun.")
            expected_runs = before_runs if run.run_id in before_run_ids else before_runs + 1
            if SimulationRun.objects.count() != expected_runs:
                raise CommandError("Zero-start simulation created an unexpected number of SimulationRun records.")
            turns = SimulationTurn.objects.filter(run=run).count()
            events = Event.objects.filter(simulation_run=run, generated_by=Event.GeneratedBy.SIMULATION_ENGINE).count()
            applicants = MemberApplication.objects.filter(metadata__simulation_run_id=run.run_id).count()
            partners = PartnerApplication.objects.filter(metadata__simulation_run_id=run.run_id).count()
            failures = SimulationFailure.objects.filter(run=run).count()
            if turns < hours:
                raise CommandError("Zero-start simulation did not create one turn per virtual hour.")
            if not events:
                raise CommandError("Zero-start simulation did not create public simulation events.")
            if not applicants:
                raise CommandError("Zero-start simulation did not create member applications.")
            pre_engineering_can_continue = (
                run.status == SimulationRun.Status.RUNNING
                and run.metadata.get("can_continue")
                and run.metadata.get("startup_gate_satisfied")
                and run.metadata.get("project_phase") == "pre_engineering"
            )
            if run.status != SimulationRun.Status.COMPLETED and not failures and not pre_engineering_can_continue:
                raise CommandError("Zero-start simulation stopped without completion, failure, or valid continuation state.")
        finally:
            reset_current_world(token)

        isolation_status = self._realworld_isolation_status(realworld_before)
        self.stdout.write(
            self.style.SUCCESS(
                "Zero-start simulation passed: "
                f"world={world.world_id}, "
                f"run={run.run_id}, "
                f"status={run.status}, "
                f"hours={hours}, "
                f"turns={turns}, "
                f"events={events}, "
                f"applicants={applicants}, "
                f"partners={partners}, "
                f"failures={failures}, "
                f"isolation={isolation_status}"
            )
        )

    def _simulation_world(self, world_id: str) -> WorldRegistry:
        world = get_world_or_error(world_id)
        if world.status != WorldRegistry.Status.ACTIVE:
            raise CommandError(f"World is not active: {world.world_id} ({world.status})")
        if world.world_type != WorldRegistry.WorldType.SIMULATION:
            raise CommandError(f"Refusing to run zero-start simulation for non-simulation world: {world.world_id}")
        return world

    def _business_counts(self) -> tuple[int, int, int, int]:
        return (
            SimulationRun.objects.count(),
            SimulationTurn.objects.count(),
            Event.objects.filter(generated_by=Event.GeneratedBy.SIMULATION_ENGINE).count(),
            Member.objects.count(),
        )

    def _realworld_counts(self) -> tuple[int, int, int, int] | None:
        if not getattr(settings, "WORLD_DATABASE_ROUTING_ENABLED", True):
            return None
        try:
            realworld = WorldRegistry.objects.using("default").get(
                world_id=DEFAULT_REALWORLD_ID,
                status=WorldRegistry.Status.ACTIVE,
            )
        except WorldRegistry.DoesNotExist:
            return None
        context = context_from_registry(realworld)
        token = set_current_world(context)
        try:
            return self._business_counts()
        finally:
            reset_current_world(token)

    def _realworld_isolation_status(self, before: tuple[int, int, int, int] | None) -> str:
        if not getattr(settings, "WORLD_DATABASE_ROUTING_ENABLED", True):
            return "not_applicable"
        if before is None:
            return "realworld_missing"
        try:
            realworld = WorldRegistry.objects.using("default").get(
                world_id=DEFAULT_REALWORLD_ID,
                status=WorldRegistry.Status.ACTIVE,
            )
        except WorldRegistry.DoesNotExist:
            return "realworld_missing"
        context = context_from_registry(realworld)
        token = set_current_world(context)
        try:
            after = self._business_counts()
        finally:
            reset_current_world(token)
        if before != after:
            raise CommandError("Zero-start simulation changed realworld business table counts.")
        return "unchanged"
