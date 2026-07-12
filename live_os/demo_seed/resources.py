"""Resource demo seed data."""

from __future__ import annotations

from core.models import Resource, Ruleset

from .helpers import upsert
from .resource_specs import resource_specs


def seed_resources(*, now, mark, ruleset: Ruleset) -> None:
    for item in resource_specs():
        mark(
            upsert(
                Resource,
                {"resource_id": item["resource_id"]},
                {
                    **item,
                    "updated_at": now,
                    "rule_version": ruleset.version,
                    "metadata": {"seed": True},
                },
            )
        )
