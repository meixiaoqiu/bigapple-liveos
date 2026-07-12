"""Hard boundaries for simulation writes."""

from __future__ import annotations

from core.exceptions import DomainError


def run_simulation_turn(*, simulation_day: int) -> dict[str, object]:
    """Reject the old unscoped one-turn simulation path.

    A single-turn simulation must be implemented against SimulationRun/world
    state before it can write anything. The previous prototype mutated real
    Task, Resource, LedgerEntry, and Event rows, which breaks world isolation.
    """

    raise DomainError("单回合仿真必须先绑定 simulation world/run，不能默认写入真实世界数据。")
