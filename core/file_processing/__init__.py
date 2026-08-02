"""Reusable validation and transformation primitives for untrusted files."""

from .images import ProcessedAvatar, process_avatar

__all__ = ["ProcessedAvatar", "process_avatar"]
