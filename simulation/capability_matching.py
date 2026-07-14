"""Shared pure function for capability/skill requirement matching.

This module has no imports from zero_start, projections, or strategy so
both the projection layer and the strategy layer can depend on it without
circular imports.
"""

from __future__ import annotations


def skills_match_requirement(skills: dict[str, int], requirement: dict[str, object]) -> bool:
    """Return True when *skills* covers at least one alias of *requirement*
    with a score >= 50.
    """
    aliases = [str(a) for a in requirement["skill_aliases"]]
    return any(int(skills.get(a, 0) or 0) >= 50 for a in aliases)
