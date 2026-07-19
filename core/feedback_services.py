"""Community feedback lifecycle services.

Feedback is public engagement, NOT governance.  Status changes
through these services do not alter RoleAssignment, RolePermission,
or any authoritative system state.
"""

from __future__ import annotations

from uuid import uuid4

from django.utils import timezone

from .access import is_governance_principal
from .db import atomic_for_model
from .exceptions import DomainError
from .models import CommunityFeedback, Event, Member, Proposal


def _event_suffix() -> str:
    return uuid4().hex[:8]


def _feedback_public_payload(
    feedback: CommunityFeedback,
    *,
    action: str,
    proposal: Proposal | None = None,
) -> dict[str, str]:
    payload = {
        "source": "community_feedback",
        "feedback_id": feedback.feedback_id,
        "feedback_category": feedback.category,
        "feedback_category_label": feedback.get_category_display(),
        "feedback_status": feedback.status,
        "feedback_status_label": feedback.get_status_display(),
        "public_author_label": feedback.author_member.member_no,
        "title": feedback.title,
        "action_type": action,
    }
    if proposal is not None:
        payload["proposal_no"] = proposal.proposal_no
    return payload


def _write_public_event(
    event_id: str,
    title: str,
    summary: str,
    *,
    payload: dict[str, str],
    simulation_day: int = 1,
) -> None:
    Event.objects.create(
        event_id=event_id,
        event_type="governance",
        visibility="public",
        title=title,
        summary=summary,
        simulation_day=simulation_day,
        occurred_at=timezone.now(),
        generated_by="live_os",
        severity="info",
        payload=payload,
    )


@atomic_for_model(CommunityFeedback)
def submit_feedback(
    *, author_member: Member, title: str, category: str, body: str,
) -> CommunityFeedback:
    """Create a new public community feedback entry.

    Raises DomainError for SUSPENDED / EXITED members.
    """
    if author_member.status in {Member.Status.SUSPENDED, Member.Status.EXITED}:
        raise DomainError("你的成员状态已停用，不能提交反馈。")
    if category not in CommunityFeedback.Category.values:
        raise DomainError("反馈类别无效。")
    feedback = CommunityFeedback.objects.create(
        author_member=author_member,
        title=title,
        category=category,
        body=body,
        status=CommunityFeedback.Status.OPEN,
    )
    _write_public_event(
        f"community-feedback-submitted-{feedback.feedback_id}",
        "收到公开反馈",
        f"成员提交了《{title}》（{feedback.get_category_display()}）。",
        payload=_feedback_public_payload(feedback, action="submitted"),
    )
    return feedback


@atomic_for_model(CommunityFeedback)
def respond_to_feedback(
    *,
    feedback: CommunityFeedback,
    responder_member: Member,
    response: str,
    status: str = CommunityFeedback.Status.ANSWERED,
) -> CommunityFeedback:
    """Record an official governance response to a feedback entry.

    *responder_member* must hold governance permission.
    """
    if not is_governance_principal(responder_member):
        raise DomainError("只有治理成员才能回应反馈。")
    if status not in CommunityFeedback.Status.values:
        raise DomainError("反馈状态无效。")
    if status == CommunityFeedback.Status.HIDDEN:
        raise DomainError("隐藏反馈必须使用 hide_feedback。")
    if status == CommunityFeedback.Status.LINKED:
        raise DomainError("转入治理流程必须使用 link_feedback_to_proposal。")
    if status == CommunityFeedback.Status.ANSWERED and not response.strip():
        raise DomainError("发布正式回应时必须填写回应内容。")
    feedback.official_response = response
    feedback.responded_by = responder_member
    feedback.responded_at = timezone.now()
    feedback.status = status
    feedback.save(update_fields=[
        "official_response", "responded_by", "responded_at", "status", "updated_at",
    ])
    if status != CommunityFeedback.Status.HIDDEN:
        _write_public_event(
            f"community-feedback-answered-{feedback.feedback_id}-{_event_suffix()}",
            "治理成员回应反馈",
            f"治理成员回应了《{feedback.title}》：{response[:120]}",
            payload=_feedback_public_payload(feedback, action="answered"),
        )
    return feedback


@atomic_for_model(CommunityFeedback)
def hide_feedback(
    *, feedback: CommunityFeedback, actor_member: Member, reason: str = "",
) -> CommunityFeedback:
    """Hide a feedback entry from public view.

    *actor_member* must hold governance permission.
    Does NOT write a public Event (avoids amplifying hidden content).
    """
    if not is_governance_principal(actor_member):
        raise DomainError("只有治理成员才能隐藏反馈。")
    feedback.status = CommunityFeedback.Status.HIDDEN
    feedback.responded_by = actor_member
    feedback.responded_at = timezone.now()
    feedback.official_response = reason or feedback.official_response
    feedback.save(update_fields=[
        "status", "responded_by", "responded_at", "official_response", "updated_at",
    ])
    Event.objects.filter(
        event_id__startswith="community-feedback-",
        event_id__contains=feedback.feedback_id,
    ).update(visibility=Event.Visibility.INTERNAL)
    return feedback


@atomic_for_model(CommunityFeedback)
def link_feedback_to_proposal(
    *,
    feedback: CommunityFeedback,
    proposal: Proposal,
    actor_member: Member,
) -> CommunityFeedback:
    """Link a feedback entry to a formal governance Proposal.

    *actor_member* must hold governance permission.
    """
    if not is_governance_principal(actor_member):
        raise DomainError("只有治理成员才能将反馈转入治理流程。")
    feedback.linked_proposal = proposal
    feedback.status = CommunityFeedback.Status.LINKED
    feedback.responded_by = actor_member
    feedback.responded_at = timezone.now()
    feedback.save(update_fields=[
        "linked_proposal", "status", "responded_by", "responded_at", "updated_at",
    ])
    _write_public_event(
        f"community-feedback-linked-{feedback.feedback_id}-{_event_suffix()}",
        "反馈已转入治理流程",
        f"《{feedback.title}》已关联提案 {proposal.proposal_no}。",
        payload=_feedback_public_payload(feedback, action="linked", proposal=proposal),
    )
    return feedback
