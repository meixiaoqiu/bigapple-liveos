"""Stable id allocators for simulation-owned records."""

from __future__ import annotations

from uuid import uuid4

from core.exceptions import DomainError
from core.models import (
    Event,
    PlanChangeOperation,
    PlanChangeSet,
    PlanNodeRunState,
    PlanRevisionProposal,
    SimulationFailure,
    SimulationRun,
    SimulationTurn,
)


def generate_simulation_event_id() -> str:
    """Allocate an observable simulation event id without relying on database sequences."""

    for _ in range(5):
        event_id = f"event-sim-{uuid4().hex[:12]}"
        if not Event.objects.filter(event_id=event_id).exists():
            return event_id
    raise DomainError("无法生成仿真事件 ID，请重试。")


def generate_simulation_run_id() -> str:
    """Allocate a stable id for one automatic plan simulation run."""

    for _ in range(5):
        run_id = f"sim-run-{uuid4().hex[:12]}"
        if not SimulationRun.objects.filter(run_id=run_id).exists():
            return run_id
    raise DomainError("无法生成模拟运行 ID，请重试。")


def generate_plan_node_run_state_id() -> str:
    """Allocate a plan-node state id scoped to generated simulation history."""

    for _ in range(5):
        state_id = f"state-{uuid4().hex[:16]}"
        if not PlanNodeRunState.objects.filter(state_id=state_id).exists():
            return state_id
    raise DomainError("无法生成节点模拟状态 ID，请重试。")


def generate_simulation_turn_id() -> str:
    """Allocate a turn id for the MUD-style observable simulation log."""

    for _ in range(5):
        turn_id = f"turn-{uuid4().hex[:14]}"
        if not SimulationTurn.objects.filter(turn_id=turn_id).exists():
            return turn_id
    raise DomainError("无法生成模拟推进日志 ID，请重试。")


def generate_simulation_failure_id() -> str:
    """Allocate a simulation failure id."""

    for _ in range(5):
        failure_id = f"failure-{uuid4().hex[:12]}"
        if not SimulationFailure.objects.filter(failure_id=failure_id).exists():
            return failure_id
    raise DomainError("无法生成模拟失败 ID，请重试。")


def generate_plan_revision_proposal_id() -> str:
    """Allocate a plan revision proposal id."""

    for _ in range(5):
        proposal_id = f"proposal-{uuid4().hex[:12]}"
        if not PlanRevisionProposal.objects.filter(proposal_id=proposal_id).exists():
            return proposal_id
    raise DomainError("无法生成计划修订建议 ID，请重试。")


def generate_plan_change_set_id() -> str:
    """Allocate a structured plan change-set id."""

    for _ in range(5):
        change_set_id = f"changeset-{uuid4().hex[:12]}"
        if not PlanChangeSet.objects.filter(change_set_id=change_set_id).exists():
            return change_set_id
    raise DomainError("无法生成计划变更集 ID，请重试。")


def generate_plan_change_operation_id() -> str:
    """Allocate a structured plan change operation id."""

    for _ in range(5):
        operation_id = f"changeop-{uuid4().hex[:16]}"
        if not PlanChangeOperation.objects.filter(operation_id=operation_id).exists():
            return operation_id
    raise DomainError("无法生成计划变更操作 ID，请重试。")
