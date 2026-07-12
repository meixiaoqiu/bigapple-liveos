from __future__ import annotations

from contextvars import ContextVar, Token
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .context import WorldContext


_current_world: ContextVar[WorldContext | None] = ContextVar("current_world", default=None)


def get_current_world() -> WorldContext | None:
    return _current_world.get()


def set_current_world(world: WorldContext | None) -> Token[WorldContext | None]:
    return _current_world.set(world)


def reset_current_world(token: Token[WorldContext | None]) -> None:
    _current_world.reset(token)
