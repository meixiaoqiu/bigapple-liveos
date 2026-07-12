"""Dispute contract serializers."""

from __future__ import annotations

from typing import Any

from core.models import Dispute

from .base import drop_none, encode_value


def dispute_to_contract(dispute: Dispute) -> dict[str, Any]:
    return drop_none(
        {
            "dispute_id": dispute.dispute_id,
            "dispute_type": dispute.dispute_type,
            "status": dispute.status,
            "claimant_member_no": dispute.claimant_member.member_no,
            "respondent_member_no": dispute.respondent_member.member_no if dispute.respondent_member_id else None,
            "related_task_id": dispute.related_task_id,
            "related_ledger_entry_id": dispute.related_ledger_entry_id,
            "facts": dispute.facts,
            "evidence_refs": dispute.evidence_refs,
            "handler": dispute.handler or None,
            "reviewer": dispute.reviewer or None,
            "resolution": dispute.resolution,
            "appeal_path": dispute.appeal_path,
            "submitted_at": encode_value(dispute.submitted_at),
            "resolved_at": encode_value(dispute.resolved_at),
            "metadata": dispute.metadata,
        }
    )
