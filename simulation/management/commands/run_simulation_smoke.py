from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from core.exceptions import DomainError
from core.models import (
    Event,
    LedgerEntry,
    Member,
    PlanChangeOperation,
    PlanChangeSet,
    PlanNode,
    PlanNodeRunState,
    PlanRevision,
    PlanRevisionProposal,
    ProjectPlan,
    Resource,
    SimulationFailure,
    SimulationRun,
    SimulationTurn,
    Task,
)
from simulation.engine import run_active_plan_until_failure
from simulation.disposition import UnresolvedSimulationRunError, ensure_no_unresolved_finished_runs
from worlds.context import DEFAULT_REALWORLD_ID, context_from_registry
from worlds.lifecycle import get_world_or_error
from worlds.models import WorldRegistry
from worlds.state import reset_current_world, set_current_world


@dataclass(frozen=True)
class CountSnapshot:
    simulation_runs: int
    simulation_turns: int
    simulation_failures: int
    plan_revision_proposals: int
    plan_change_sets: int
    plan_change_operations: int
    simulation_events: int
    tasks: int
    ledger_entries: int
    members: int
    resources: int
    project_plans: int
    plan_revisions: int
    plan_nodes: int


class Command(BaseCommand):
    help = "Run a repeatable automatic simulation smoke check inside one simulation world."

    def add_arguments(self, parser):
        parser.add_argument(
            "--world-id",
            default="simulation0001",
            help="Simulation world id to seed and run. Defaults to simulation0001.",
        )
        parser.add_argument(
            "--max-turns",
            type=int,
            default=30,
            help="Maximum automatic simulation steps before the run is paused.",
        )
        parser.add_argument(
            "--skip-seed",
            action="store_true",
            help="Use existing world data instead of running the idempotent demo seed first.",
        )

    def handle(self, *args, **options):
        max_turns = options["max_turns"]
        if max_turns <= 0:
            raise CommandError("--max-turns must be greater than 0.")

        world = self._simulation_world(options["world_id"])
        realworld_before = self._realworld_snapshot()
        try:
            ensure_no_unresolved_finished_runs(world=world)
        except UnresolvedSimulationRunError as exc:
            raise CommandError(str(exc)) from exc
        if not options["skip_seed"]:
            call_command("seed_world", world.world_id, stdout=self.stdout, stderr=self.stderr)

        context = context_from_registry(world)
        token = set_current_world(context)
        try:
            business_before = self._snapshot_counts()
            try:
                result = run_active_plan_until_failure(max_turns=max_turns)
            except DomainError as exc:
                raise CommandError(str(exc)) from exc
            business_after = self._snapshot_counts()
            self._assert_run_result(result, business_before, business_after)
            run = result["run"]
            failure = result.get("failure")
            proposal = result.get("proposal")
            run_summary = {
                "run_id": run.run_id,
                "status": run.status,
                "turns": SimulationTurn.objects.filter(run=run).count(),
                "events": Event.objects.filter(simulation_run=run).count(),
                "failure_id": getattr(failure, "failure_id", "") or "none",
                "proposal_id": getattr(proposal, "proposal_id", "") or "none",
            }
        finally:
            reset_current_world(token)

        isolation_status = self._realworld_isolation_status(realworld_before)
        self.stdout.write(
            self.style.SUCCESS(
                "Simulation smoke passed: "
                f"world={world.world_id}, "
                f"run={run_summary['run_id']}, "
                f"status={run_summary['status']}, "
                f"turns={run_summary['turns']}, "
                f"events={run_summary['events']}, "
                f"failure={run_summary['failure_id']}, "
                f"proposal={run_summary['proposal_id']}, "
                f"isolation={isolation_status}"
            )
        )

    def _simulation_world(self, world_id: str) -> WorldRegistry:
        world = get_world_or_error(world_id)
        if world.status != WorldRegistry.Status.ACTIVE:
            raise CommandError(f"World is not active: {world.world_id} ({world.status})")
        if world.world_type != WorldRegistry.WorldType.SIMULATION:
            raise CommandError(f"Refusing to run simulation smoke for non-simulation world: {world.world_id}")
        return world

    def _snapshot_counts(self) -> CountSnapshot:
        return CountSnapshot(
            simulation_runs=SimulationRun.objects.count(),
            simulation_turns=SimulationTurn.objects.count(),
            simulation_failures=SimulationFailure.objects.count(),
            plan_revision_proposals=PlanRevisionProposal.objects.count(),
            plan_change_sets=PlanChangeSet.objects.count(),
            plan_change_operations=PlanChangeOperation.objects.count(),
            simulation_events=Event.objects.filter(generated_by=Event.GeneratedBy.SIMULATION_ENGINE).count(),
            tasks=Task.objects.count(),
            ledger_entries=LedgerEntry.objects.count(),
            members=Member.objects.count(),
            resources=Resource.objects.count(),
            project_plans=ProjectPlan.objects.count(),
            plan_revisions=PlanRevision.objects.count(),
            plan_nodes=PlanNode.objects.count(),
        )

    def _assert_run_result(
        self,
        result: dict[str, object],
        before: CountSnapshot,
        after: CountSnapshot,
    ) -> None:
        run = result["run"]
        if not isinstance(run, SimulationRun):
            raise CommandError("Simulation engine did not return a SimulationRun.")
        if run.status not in {SimulationRun.Status.FAILED, SimulationRun.Status.COMPLETED, SimulationRun.Status.PAUSED}:
            raise CommandError(f"Simulation run ended in an unexpected status: {run.status}")
        if after.simulation_runs != before.simulation_runs + 1:
            raise CommandError("Simulation smoke expected exactly one new SimulationRun.")

        turns = SimulationTurn.objects.filter(run=run)
        events = Event.objects.filter(simulation_run=run, generated_by=Event.GeneratedBy.SIMULATION_ENGINE)
        if not turns.exists():
            raise CommandError("Simulation smoke did not create any SimulationTurn records.")
        if not events.exists():
            raise CommandError("Simulation smoke did not create any simulation Event records.")
        if events.exclude(payload__run_id=run.run_id).exists():
            raise CommandError("Simulation smoke created an Event without the correct run_id payload.")
        if not PlanNodeRunState.objects.filter(run=run).exists():
            raise CommandError("Simulation smoke did not create per-node run states.")

        immutable_business_counts = {
            "Task": (before.tasks, after.tasks),
            "LedgerEntry": (before.ledger_entries, after.ledger_entries),
            "Member": (before.members, after.members),
            "Resource": (before.resources, after.resources),
            "ProjectPlan": (before.project_plans, after.project_plans),
            "PlanRevision": (before.plan_revisions, after.plan_revisions),
            "PlanNode": (before.plan_nodes, after.plan_nodes),
        }
        changed = [
            f"{name}:{old}->{new}"
            for name, (old, new) in immutable_business_counts.items()
            if old != new
        ]
        if changed:
            raise CommandError(
                "Simulation smoke changed live business table counts after seeding: " + ", ".join(changed)
            )

        if run.status == SimulationRun.Status.FAILED:
            failure = SimulationFailure.objects.filter(run=run).first()
            proposal = PlanRevisionProposal.objects.filter(run=run).first()
            change_set = PlanChangeSet.objects.filter(run=run).first()
            if failure is None or proposal is None or change_set is None:
                raise CommandError("Failed simulation run did not create failure feedback records.")
            if not PlanChangeOperation.objects.filter(change_set=change_set).exists():
                raise CommandError("Failed simulation run did not create plan change operations.")

    def _realworld_snapshot(self) -> CountSnapshot | None:
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
            return self._snapshot_counts()
        finally:
            reset_current_world(token)

    def _realworld_isolation_status(self, before: CountSnapshot | None) -> str:
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
            after = self._snapshot_counts()
        finally:
            reset_current_world(token)
        if before != after:
            raise CommandError("Simulation smoke changed realworld business table counts.")
        return "unchanged"
