"""Capacity assessment contract serializers."""

from __future__ import annotations

from typing import Any

from core.models import CapacityAssessment

from .base import drop_none, encode_value


def capacity_assessment_to_contract(assessment: CapacityAssessment) -> dict[str, Any]:
    return drop_none(
        {
            "assessment_id": assessment.assessment_id,
            "simulation_day": assessment.simulation_day,
            "current_formal_members": assessment.current_formal_members,
            "current_candidate_members": assessment.current_candidate_members,
            "maximum_admissible_members": assessment.maximum_admissible_members,
            "recommended_new_members": assessment.recommended_new_members,
            "bottlenecks": assessment.bottlenecks,
            "risk_indicators": assessment.risk_indicators,
            "reasons": assessment.reasons,
            "rule_version": assessment.rule_version,
            "created_at": encode_value(assessment.created_at),
            "metadata": assessment.metadata,
        }
    )


def public_capacity_assessment_to_contract(assessment: CapacityAssessment) -> dict[str, Any]:
    return drop_none(
        {
            "assessment_id": assessment.assessment_id,
            "simulation_day": assessment.simulation_day,
            "current_formal_members": assessment.current_formal_members,
            "current_candidate_members": assessment.current_candidate_members,
            "maximum_admissible_members": assessment.maximum_admissible_members,
            "recommended_new_members": assessment.recommended_new_members,
            "bottlenecks": assessment.bottlenecks,
            "risk_indicators": assessment.risk_indicators,
            "reasons": assessment.reasons,
            "rule_version": assessment.rule_version,
            "created_at": encode_value(assessment.created_at),
        }
    )
