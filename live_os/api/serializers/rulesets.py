"""Ruleset contract serializers."""

from __future__ import annotations

from typing import Any

from core.models import Ruleset

from .base import drop_none, encode_value


def ruleset_to_contract(ruleset: Ruleset) -> dict[str, Any]:
    return drop_none(
        {
            "ruleset_id": ruleset.ruleset_id,
            "version": ruleset.version,
            "status": ruleset.status,
            "effective_from": encode_value(ruleset.effective_from),
            "effective_to": encode_value(ruleset.effective_to),
            "negative_point_floor": ruleset.negative_point_floor,
            "task_point_rules": ruleset.task_point_rules,
            "created_at": encode_value(ruleset.created_at),
            "created_by": ruleset.created_by,
            "change_summary": ruleset.change_summary,
            "metadata": ruleset.metadata,
        }
    )
