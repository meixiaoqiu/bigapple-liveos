"""Domain-level exceptions shared across app boundaries."""

from __future__ import annotations


class DomainError(ValueError):
    """Raised when a requested business transition is not allowed."""
