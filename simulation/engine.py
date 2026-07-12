"""Automatic plan simulation engine."""

from __future__ import annotations

from core.db import atomic_for_model
from core.models import SimulationRun

from .feasibility import feasibility_failure_for_node
from .failure_handling import fail_simulation_node
from .run_progress import (
    complete_simulation_node,
    complete_simulation_run,
    next_executable_state,
    pause_simulation_run_at_limit,
)
from .run_state import create_simulation_run, ensure_plan_node_run_states


@atomic_for_model(SimulationRun)
def advance_plan_simulation_run(run: SimulationRun) -> dict[str, object]:
    """Advance one plan node in an automatic simulation run."""

    run = SimulationRun.objects.select_for_update().get(run_id=run.run_id)
    if run.status in {SimulationRun.Status.FAILED, SimulationRun.Status.COMPLETED}:
        return {"run": run, "advanced": False, "failure": run.failures.first()}
    ensure_plan_node_run_states(run)
    state = next_executable_state(run)
    if state is None:
        complete_simulation_run(run)
        return {"run": run, "advanced": True, "failure": None}

    failure_data = feasibility_failure_for_node(run, state.plan_node)
    if failure_data:
        failure, proposal = fail_simulation_node(run=run, state=state, failure_data=failure_data)
        return {"run": run, "advanced": True, "failure": failure, "proposal": proposal}

    complete_simulation_node(run=run, state=state)
    run.refresh_from_db()
    return {"run": run, "advanced": True, "failure": None}


def run_simulation_until_failure(*, run: SimulationRun, max_turns: int | None = None) -> dict[str, object]:
    """Run an automatic plan simulation until it fails, completes, or hits a step limit."""

    limit = max_turns or run.max_turns
    turns_run = 0
    latest_result: dict[str, object] = {"run": run, "advanced": False, "failure": None}
    while turns_run < limit:
        run.refresh_from_db()
        if run.status in {SimulationRun.Status.FAILED, SimulationRun.Status.COMPLETED, SimulationRun.Status.PAUSED}:
            break
        latest_result = advance_plan_simulation_run(run)
        turns_run += 1 if latest_result.get("advanced") else 0
        run = latest_result["run"]
        if run.status in {SimulationRun.Status.FAILED, SimulationRun.Status.COMPLETED}:
            break
    run.refresh_from_db()
    if turns_run >= limit and run.status == SimulationRun.Status.RUNNING:
        run = pause_simulation_run_at_limit(run)
    return {
        "run": run,
        "turns_run": turns_run,
        "failure": run.failures.order_by("-detected_at").first(),
        "proposal": run.proposals.order_by("-created_at").first(),
        **{key: value for key, value in latest_result.items() if key not in {"run", "failure", "proposal"}},
    }


def run_active_plan_until_failure(*, max_turns: int = 30) -> dict[str, object]:
    """Create a new run for the active plan and advance it until feedback is available."""

    run = create_simulation_run(max_turns=max_turns)
    return run_simulation_until_failure(run=run, max_turns=max_turns)
