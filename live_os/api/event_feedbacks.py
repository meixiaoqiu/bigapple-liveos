"""Event-feedback JSON API views."""

from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods

from core.event_feedback_services import submit_event_feedback
from core.exceptions import DomainError
from core.models import Event, Member
from live_os.access import member_for_request

from .serializers import event_feedback_to_contract
from .utils import error_response, read_json


@require_http_methods(["POST"])
def create_event_feedback(request: HttpRequest, **_kwargs) -> JsonResponse:
    member = member_for_request(request)
    if member is None:
        return error_response("permission_denied", "需要已登录成员身份。", 403)
    try:
        payload = read_json(request)
    except (ValueError, UnicodeDecodeError):
        return error_response("invalid_request", "请求正文必须是有效 JSON 对象。", 400)
    if not isinstance(payload, dict):
        return error_response("invalid_request", "请求正文必须是 JSON 对象。", 400)
    allowed_fields = {
        "related_event_id", "feedback_type", "subject_member_no", "statement",
        "requested_outcome", "evidence_refs", "submitter_visibility",
        "privacy_reason", "metadata",
    }
    if set(payload) - allowed_fields:
        return error_response("invalid_request", "请求包含未知或由服务器管理的字段。", 400)
    string_fields = {
        "related_event_id", "feedback_type", "subject_member_no", "statement",
        "requested_outcome", "submitter_visibility", "privacy_reason",
    }
    if any(name in payload and not isinstance(payload[name], str) for name in string_fields):
        return error_response("invalid_request", "反馈文本和标识字段必须是字符串。", 400)
    evidence_refs = payload.get("evidence_refs", [])
    if not isinstance(evidence_refs, list) or any(
        not isinstance(item, str) or not item.strip() for item in evidence_refs
    ):
        return error_response("invalid_request", "evidence_refs 必须是非空字符串数组。", 400)
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        return error_response("invalid_request", "metadata 必须是 JSON 对象。", 400)
    event_id = payload.get("related_event_id", "").strip()
    feedback_type = payload.get("feedback_type", "").strip()
    statement = payload.get("statement", "")
    if not event_id or not feedback_type or not statement.strip():
        return error_response("invalid_request", "related_event_id、feedback_type 和 statement 为必填字段。", 400)
    event = get_object_or_404(Event.objects.filter(visibility=Event.Visibility.PUBLIC), event_id=event_id)
    subject = None
    subject_no = payload.get("subject_member_no", "").strip()
    if subject_no:
        subject = get_object_or_404(Member, member_no=subject_no)
    try:
        feedback = submit_event_feedback(
            related_event=event, submitted_by=member, feedback_type=feedback_type,
            subject_member=subject, statement=statement, requested_outcome=payload.get("requested_outcome", ""),
            evidence_refs=evidence_refs, submitter_visibility=payload.get("submitter_visibility") or "public",
            privacy_reason=payload.get("privacy_reason", ""), metadata=metadata,
        )
    except DomainError as exc:
        return error_response("state_conflict", str(exc), 409)
    return JsonResponse(event_feedback_to_contract(feedback, viewer=member), status=201)
