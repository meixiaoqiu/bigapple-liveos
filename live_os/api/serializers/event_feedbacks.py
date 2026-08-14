"""Event-feedback contract serializers."""

from typing import Any

from core.event_feedback_services import can_view_feedback_private_content, can_view_submitter_identity
from core.access import member_can_administer
from core.models import EventFeedback, Member

from .base import drop_none, encode_value


def event_feedback_to_contract(feedback: EventFeedback, *, viewer: Member | None = None) -> dict[str, Any]:
    show_identity = can_view_submitter_identity(feedback, viewer)
    show_private_content = can_view_feedback_private_content(feedback, viewer)
    is_handler = bool(viewer and (viewer.pk == feedback.assigned_handler_id or member_can_administer(viewer)))
    show_subject = bool(viewer and (viewer.pk == feedback.subject_member_id or is_handler))
    return drop_none({
        "feedback_id": feedback.feedback_id,
        "related_event_id": feedback.related_event_id,
        "feedback_type": feedback.feedback_type,
        "status": feedback.status,
        "submitted_by_member_no": feedback.submitted_by.member_no if show_identity else None,
        "subject_member_no": feedback.subject_member.member_no if feedback.subject_member_id and show_subject else None,
        "statement": feedback.statement if show_private_content else "详细内容仅相关方和处理人可见。",
        "requested_outcome": feedback.requested_outcome if show_private_content else "",
        "evidence_refs": feedback.evidence_refs if show_private_content else [],
        "submitter_visibility": feedback.submitter_visibility,
        "privacy_reason": feedback.privacy_reason if is_handler else None,
        "assigned_handler_member_no": feedback.assigned_handler.member_no if feedback.assigned_handler_id else None,
        "response_statement": feedback.response_statement if show_private_content else "",
        "responded_by_member_no": feedback.responded_by.member_no if feedback.responded_by_id and show_private_content else None,
        "responded_at": encode_value(feedback.responded_at) if show_private_content else None,
        "conclusion": feedback.conclusion or None,
        "conclusion_reason": feedback.conclusion_reason,
        "resolution_event_id": feedback.resolution_event_id,
        "concluded_by_member_no": feedback.concluded_by.member_no if feedback.concluded_by_id else None,
        "submitted_at": encode_value(feedback.submitted_at),
        "verification_started_at": encode_value(feedback.verification_started_at),
        "concluded_at": encode_value(feedback.concluded_at),
        "closed_at": encode_value(feedback.closed_at),
        "metadata": feedback.metadata,
    })
