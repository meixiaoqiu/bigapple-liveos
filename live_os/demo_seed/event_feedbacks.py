"""Event-feedback demo seed data."""

from datetime import timedelta

from core.models import Event, EventFeedback

from .helpers import upsert


def seed_event_feedbacks(*, now, mark, members: dict) -> None:
    admin = members["admin"]
    member_2 = members["member_2"]
    member_3 = members["member_3"]
    event = Event.objects.get(event_id="event-resource-0001")
    mark(upsert(EventFeedback, {"feedback_id": "feedback-0001"}, {
        "related_event": event, "feedback_type": EventFeedback.FeedbackType.RISK,
        "status": EventFeedback.Status.VERIFYING, "submitted_by": member_2,
        "subject_member": member_3, "statement": "药品库存差异可能造成后续供应风险。",
        "requested_outcome": "核实库存并提出预防措施。", "evidence_refs": ["event-resource-0001"],
        "submitter_visibility": EventFeedback.SubmitterVisibility.PUBLIC, "privacy_reason": "",
        "assigned_handler": admin, "submitted_at": now + timedelta(hours=10),
        "verification_started_at": now + timedelta(hours=11), "metadata": {"seed": True},
    }))
