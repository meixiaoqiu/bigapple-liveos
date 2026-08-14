"""Domain services for event-centered member feedback."""

from __future__ import annotations

from django.utils import timezone

from .access import member_can_administer
from .db import atomic_for_model
from .event_ledger import PUBLIC_LEDGER_SCHEMA, append_event
from .exceptions import DomainError
from .id_generators import generate_event_feedback_id
from .models import Event, EventFeedback, Member, SystemEvent


def _payload(feedback: EventFeedback, *, action: str, summary: str) -> dict:
    return {
        "schema": PUBLIC_LEDGER_SCHEMA,
        "subject": {"type": "event_feedback", "ref": f"feedback:{feedback.feedback_id}", "label": feedback.get_feedback_type_display()},
        "action": action,
        "stage": feedback.status,
        "summary": summary,
        "public_facts": {"feedback_type": feedback.feedback_type, "status": feedback.status},
        "private_commitments": [
            {"name": "submitted_by", "present": True, "reason": "内部实名责任记录"},
            {"name": "evidence", "present": bool(feedback.evidence_refs), "reason": "证据按独立隐私规则提供"},
        ],
    }


def _append(feedback: EventFeedback, event_type: str, actor: Member, action: str, summary: str) -> None:
    append_event(event_type=event_type, aggregate_type="EventFeedback", aggregate_id=feedback.pk, actor_member=actor, payload_json=_payload(feedback, action=action, summary=summary))


def _require_handler(actor: Member) -> None:
    if not member_can_administer(actor):
        raise DomainError("当前成员没有事件反馈处理权限。")


def _lock_feedback(feedback: EventFeedback) -> EventFeedback:
    """Reload and lock the authoritative feedback row for a transition."""
    return EventFeedback.objects.select_for_update().select_related(
        "submitted_by", "subject_member", "assigned_handler"
    ).get(pk=feedback.pk)


@atomic_for_model(EventFeedback)
def submit_event_feedback(*, related_event: Event, submitted_by: Member, feedback_type: str, statement: str, requested_outcome: str = "", evidence_refs: list[str] | None = None, subject_member: Member | None = None, submitter_visibility: str = EventFeedback.SubmitterVisibility.PUBLIC, privacy_reason: str = "", metadata: dict | None = None) -> EventFeedback:
    """Create real-name feedback fixed to one public Event."""
    if related_event.visibility != Event.Visibility.PUBLIC:
        raise DomainError("无权查看该事件。")
    if feedback_type not in EventFeedback.FeedbackType.values:
        raise DomainError("反馈类型无效。")
    if evidence_refs is not None and (
        not isinstance(evidence_refs, list)
        or any(not isinstance(item, str) or not item.strip() for item in evidence_refs)
    ):
        raise DomainError("证据引用必须是非空字符串数组。")
    if metadata is not None and not isinstance(metadata, dict):
        raise DomainError("反馈 metadata 必须是对象。")
    cleaned_statement = statement.strip()
    if not cleaned_statement:
        raise DomainError("事实陈述不能为空。")
    if submitter_visibility not in EventFeedback.SubmitterVisibility.values:
        raise DomainError("提交人身份展示范围无效。")
    cleaned_reason = privacy_reason.strip()
    if submitter_visibility != EventFeedback.SubmitterVisibility.PUBLIC and not cleaned_reason:
        raise DomainError("限制提交人身份展示时必须说明理由。")
    feedback = EventFeedback.objects.create(
        feedback_id=generate_event_feedback_id(), related_event=related_event, feedback_type=feedback_type,
        status=EventFeedback.Status.SUBMITTED, submitted_by=submitted_by, subject_member=subject_member,
        statement=cleaned_statement, requested_outcome=requested_outcome.strip(),
        evidence_refs=[item.strip() for item in (evidence_refs or [])],
        submitter_visibility=submitter_visibility, privacy_reason=cleaned_reason, submitted_at=timezone.now(), metadata=metadata or {},
    )
    _append(feedback, SystemEvent.EventType.EVENT_FEEDBACK_SUBMITTED, submitted_by, "submitted", "事件反馈已提交。")
    return feedback


@atomic_for_model(EventFeedback)
def start_event_feedback_verification(*, feedback: EventFeedback, handler: Member) -> EventFeedback:
    """Assign a handler and move submitted feedback into verification."""
    _require_handler(handler)
    feedback = _lock_feedback(feedback)
    if feedback.status != EventFeedback.Status.SUBMITTED:
        raise DomainError("只有已提交反馈可以开始核实。")
    feedback.status = EventFeedback.Status.VERIFYING
    feedback.assigned_handler = handler
    feedback.verification_started_at = timezone.now()
    feedback.save(update_fields=["status", "assigned_handler", "verification_started_at"])
    _append(feedback, SystemEvent.EventType.EVENT_FEEDBACK_VERIFICATION_STARTED, handler, "verification_started", "事件反馈已开始核实。")
    return feedback


@atomic_for_model(EventFeedback)
def request_event_feedback_response(*, feedback: EventFeedback, handler: Member) -> EventFeedback:
    """Request a formal response from the explicitly related member."""
    _require_handler(handler)
    feedback = _lock_feedback(feedback)
    if feedback.status != EventFeedback.Status.VERIFYING or not feedback.subject_member_id:
        raise DomainError("当前反馈不能请求相关方回应。")
    feedback.status = EventFeedback.Status.AWAITING_RESPONSE
    feedback.assigned_handler = handler
    feedback.save(update_fields=["status", "assigned_handler"])
    _append(feedback, SystemEvent.EventType.EVENT_FEEDBACK_RESPONSE_REQUESTED, handler, "response_requested", "事件反馈已请求相关方回应。")
    return feedback


@atomic_for_model(EventFeedback)
def respond_to_event_feedback(*, feedback: EventFeedback, responder: Member, response_statement: str) -> EventFeedback:
    """Record the formal response of the explicitly related member."""
    feedback = _lock_feedback(feedback)
    if feedback.status != EventFeedback.Status.AWAITING_RESPONSE or responder.pk != feedback.subject_member_id:
        raise DomainError("当前成员不能回应该反馈。")
    response = response_statement.strip()
    if not response:
        raise DomainError("回应内容不能为空。")
    feedback.response_statement = response
    feedback.responded_by = responder
    feedback.responded_at = timezone.now()
    feedback.status = EventFeedback.Status.VERIFYING
    feedback.save(update_fields=["response_statement", "responded_by", "responded_at", "status"])
    _append(feedback, SystemEvent.EventType.EVENT_FEEDBACK_RESPONDED, responder, "responded", "相关方已回应事件反馈。")
    return feedback


@atomic_for_model(EventFeedback)
def conclude_event_feedback(*, feedback: EventFeedback, handler: Member, conclusion: str, conclusion_reason: str, resolution_event: Event | None = None) -> EventFeedback:
    """Publish a classified conclusion without mutating the original Event."""
    _require_handler(handler)
    feedback = _lock_feedback(feedback)
    if feedback.status not in {EventFeedback.Status.VERIFYING, EventFeedback.Status.AWAITING_RESPONSE}:
        raise DomainError("当前反馈不能形成结论。")
    if conclusion not in EventFeedback.Conclusion.values or not conclusion_reason.strip():
        raise DomainError("必须提供有效结论和结论依据。")
    feedback.status = EventFeedback.Status.CONCLUDED
    feedback.conclusion = conclusion
    feedback.conclusion_reason = conclusion_reason.strip()
    feedback.resolution_event = resolution_event
    feedback.concluded_by = handler
    feedback.concluded_at = timezone.now()
    feedback.save(update_fields=["status", "conclusion", "conclusion_reason", "resolution_event", "concluded_by", "concluded_at"])
    _append(feedback, SystemEvent.EventType.EVENT_FEEDBACK_CONCLUDED, handler, "concluded", "事件反馈已形成并公布结论。")
    return feedback


@atomic_for_model(EventFeedback)
def close_event_feedback(*, feedback: EventFeedback, handler: Member) -> EventFeedback:
    """Close feedback after a conclusion has been recorded."""
    _require_handler(handler)
    feedback = _lock_feedback(feedback)
    if feedback.status != EventFeedback.Status.CONCLUDED:
        raise DomainError("只有已形成结论的反馈可以结束。")
    feedback.status = EventFeedback.Status.CLOSED
    feedback.closed_at = timezone.now()
    feedback.save(update_fields=["status", "closed_at"])
    _append(feedback, SystemEvent.EventType.EVENT_FEEDBACK_CLOSED, handler, "closed", "事件反馈已结束。")
    return feedback


@atomic_for_model(EventFeedback)
def withdraw_event_feedback(*, feedback: EventFeedback, submitted_by: Member) -> EventFeedback:
    """Withdraw an unprocessed feedback while retaining its original record."""
    feedback = _lock_feedback(feedback)
    if feedback.status != EventFeedback.Status.SUBMITTED or feedback.submitted_by_id != submitted_by.pk:
        raise DomainError("当前反馈不能由该成员撤回。")
    feedback.status = EventFeedback.Status.WITHDRAWN
    feedback.closed_at = timezone.now()
    feedback.save(update_fields=["status", "closed_at"])
    _append(feedback, SystemEvent.EventType.EVENT_FEEDBACK_WITHDRAWN, submitted_by, "withdrawn", "事件反馈已由提交人撤回。")
    return feedback


def can_view_submitter_identity(feedback: EventFeedback, viewer: Member | None) -> bool:
    """Return whether a viewer may see the real submitter identity."""
    if feedback.submitter_visibility == EventFeedback.SubmitterVisibility.PUBLIC:
        return True
    if viewer is None:
        return False
    if viewer.pk == feedback.submitted_by_id or viewer.pk == feedback.assigned_handler_id or member_can_administer(viewer):
        return True
    return feedback.submitter_visibility == EventFeedback.SubmitterVisibility.PARTIES_AND_HANDLERS and viewer.pk == feedback.subject_member_id


def can_view_feedback_private_content(feedback: EventFeedback, viewer: Member | None) -> bool:
    """Restrict member-authored raw content independently from identity visibility."""
    if viewer is None:
        return False
    return bool(
        viewer.pk in {
            feedback.submitted_by_id,
            feedback.subject_member_id,
            feedback.assigned_handler_id,
        }
        or member_can_administer(viewer)
    )
