"""Application submission and review services."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from django.utils import timezone

from core.db import atomic_for_model
from core.event_ledger import append_event
from core.exceptions import DomainError
from core.member_roles import ROLE_CANDIDATE, ensure_member_role, ensure_role_assignment
from core.models import Member, MemberApplication, PartnerApplication, SystemEvent

from .event_payloads import member_display_name
from .identity_services import register_member


def _nonblank(value: object, field_label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise DomainError(f"{field_label}不能为空。")
    return text


def _list_payload(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.replace("\n", ",").split(",") if part.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(part).strip() for part in value if str(part).strip()]
    return [str(value).strip()] if str(value).strip() else []


def generate_member_application_id() -> str:
    for _ in range(5):
        application_id = f"member-application-{uuid4().hex[:12]}"
        if not MemberApplication.objects.filter(application_id=application_id).exists():
            return application_id
    raise DomainError("无法生成成员报名 ID，请重试。")


def generate_partner_application_id() -> str:
    for _ in range(5):
        application_id = f"partner-application-{uuid4().hex[:12]}"
        if not PartnerApplication.objects.filter(application_id=application_id).exists():
            return application_id
    raise DomainError("无法生成合作方报名 ID，请重试。")


def member_application_payload(application: MemberApplication) -> dict[str, Any]:
    return {
        "application_id": application.application_id,
        "applicant_name": application.applicant_name,
        "status": application.status,
        "requested_member_no": application.requested_member_no,
        "linked_member_no": application.linked_member.member_no if application.linked_member_id else "",
        "availability_hours_per_week": application.availability_hours_per_week,
        "capability_scores": application.capability_scores,
        "can_issue_responsibility_documents": application.can_issue_responsibility_documents,
        "document_authority_domains": application.document_authority_domains,
        "submitted_at": application.submitted_at.isoformat() if application.submitted_at else None,
        "reviewed_at": application.reviewed_at.isoformat() if application.reviewed_at else None,
        "metadata": application.metadata,
    }


def partner_application_payload(application: PartnerApplication) -> dict[str, Any]:
    return {
        "application_id": application.application_id,
        "organization_name": application.organization_name,
        "contact_name": application.contact_name,
        "status": application.status,
        "service_domains": application.service_domains,
        "can_issue_responsibility_documents": application.can_issue_responsibility_documents,
        "responsibility_document_domains": application.responsibility_document_domains,
        "qualification_summary": application.qualification_summary,
        "quote_summary": application.quote_summary,
        "service_area": application.service_area,
        "delivery_cycle_days": application.delivery_cycle_days,
        "constraints": application.constraints,
        "submitted_at": application.submitted_at.isoformat() if application.submitted_at else None,
        "reviewed_at": application.reviewed_at.isoformat() if application.reviewed_at else None,
        "metadata": application.metadata,
    }


@atomic_for_model(MemberApplication)
def submit_member_application(
    *,
    applicant_name: str,
    contact: str,
    motivation: str,
    availability_hours_per_week: int,
    capability_scores: dict[str, int] | None = None,
    can_issue_responsibility_documents: bool = False,
    document_authority_domains: object = None,
    requested_member_no: str = "",
    metadata: dict[str, Any] | None = None,
    submitted_at=None,
) -> MemberApplication:
    """Submit a member application through the same authority path used by UI and simulations."""

    if availability_hours_per_week < 0:
        raise DomainError("每周可投入小时不能为负数。")
    now = submitted_at or timezone.now()
    application = MemberApplication.objects.create(
        application_id=generate_member_application_id(),
        applicant_name=_nonblank(applicant_name, "报名人名称"),
        contact=_nonblank(contact, "联系方式"),
        motivation=_nonblank(motivation, "报名动机"),
        availability_hours_per_week=availability_hours_per_week,
        capability_scores=dict(capability_scores or {}),
        can_issue_responsibility_documents=can_issue_responsibility_documents,
        document_authority_domains=_list_payload(document_authority_domains),
        requested_member_no=str(requested_member_no or "").strip(),
        submitted_at=now,
        metadata=dict(metadata or {}),
    )
    append_event(
        event_type=SystemEvent.EventType.MEMBER_APPLICATION_SUBMITTED,
        aggregate_type="MemberApplication",
        aggregate_id=application.application_id,
        payload_json=member_application_payload(application),
        occurred_at=now,
    )
    return application


@atomic_for_model(PartnerApplication)
def submit_partner_application(
    *,
    organization_name: str,
    contact_name: str,
    contact: str,
    service_domains: object = None,
    can_issue_responsibility_documents: bool = False,
    responsibility_document_domains: object = None,
    qualification_summary: str = "",
    quote_summary: str = "",
    service_area: str = "",
    delivery_cycle_days: int | None = None,
    constraints: str = "",
    metadata: dict[str, Any] | None = None,
    submitted_at=None,
) -> PartnerApplication:
    """Submit a partner application through the same authority path used by UI and simulations."""

    if delivery_cycle_days is not None and delivery_cycle_days < 0:
        raise DomainError("交付周期天数不能为负数。")
    now = submitted_at or timezone.now()
    application = PartnerApplication.objects.create(
        application_id=generate_partner_application_id(),
        organization_name=_nonblank(organization_name, "合作方名称"),
        contact_name=_nonblank(contact_name, "联系人"),
        contact=_nonblank(contact, "联系方式"),
        service_domains=_list_payload(service_domains),
        can_issue_responsibility_documents=can_issue_responsibility_documents,
        responsibility_document_domains=_list_payload(responsibility_document_domains),
        qualification_summary=str(qualification_summary or "").strip(),
        quote_summary=str(quote_summary or "").strip(),
        service_area=str(service_area or "").strip(),
        delivery_cycle_days=delivery_cycle_days,
        constraints=str(constraints or "").strip(),
        submitted_at=now,
        metadata=dict(metadata or {}),
    )
    append_event(
        event_type=SystemEvent.EventType.PARTNER_APPLICATION_SUBMITTED,
        aggregate_type="PartnerApplication",
        aggregate_id=application.application_id,
        payload_json=partner_application_payload(application),
        occurred_at=now,
    )
    return application


@atomic_for_model(MemberApplication)
def review_member_application(
    *,
    application: MemberApplication,
    status: str,
    reviewed_by: Member | None = None,
    review_note: str = "",
    member_no: str = "",
) -> MemberApplication:
    """Review one member application and create a candidate member only when accepted."""

    valid_statuses = {
        MemberApplication.Status.CANDIDATE,
        MemberApplication.Status.STANDBY,
        MemberApplication.Status.REJECTED,
        MemberApplication.Status.WITHDREW,
        MemberApplication.Status.UNDER_REVIEW,
    }
    if status not in valid_statuses:
        raise DomainError("成员报名审核状态无效。")
    now = timezone.now()
    application.status = status
    application.reviewed_by = reviewed_by
    application.reviewed_at = now
    application.metadata = {
        **application.metadata,
        "review_note": str(review_note or "").strip(),
        "reviewed_by": member_display_name(reviewed_by) if reviewed_by else "",
    }
    if status == MemberApplication.Status.CANDIDATE and application.linked_member_id is None:
        cleaned_member_no = (member_no or application.requested_member_no or f"candidate-{application.application_id[-8:]}").strip()
        member = register_member(
            member_no=cleaned_member_no,
            display_name=application.applicant_name,
            status=Member.Status.PENDING_TRAINING,
            batch_id=str(application.metadata.get("batch_id") or ""),
            joined_simulation_day=None,
            credit_floor=-100,
            profile={
                "source": "member_application",
                "application_id": application.application_id,
                "motivation": application.motivation,
                "skills": application.capability_scores,
                "availability_hours_per_week": application.availability_hours_per_week,
                "document_authority_domains": application.document_authority_domains,
                "can_issue_responsibility_documents": application.can_issue_responsibility_documents,
            },
            created_by={"actor_type": "application_review", "display_name": member_display_name(reviewed_by) if reviewed_by else "system"},
        )
        ensure_role_assignment(member, ensure_member_role(ROLE_CANDIDATE))
        application.linked_member = member
    application.save(update_fields=["status", "reviewed_by", "reviewed_at", "metadata", "linked_member"])
    append_event(
        event_type=SystemEvent.EventType.MEMBER_APPLICATION_REVIEWED,
        aggregate_type="MemberApplication",
        aggregate_id=application.application_id,
        actor_member=reviewed_by,
        payload_json=member_application_payload(application),
        occurred_at=now,
    )
    return application


@atomic_for_model(PartnerApplication)
def review_partner_application(
    *,
    application: PartnerApplication,
    status: str,
    reviewed_by: Member | None = None,
    review_note: str = "",
) -> PartnerApplication:
    """Review one partner application without creating a separate partner master record yet."""

    valid_statuses = {
        PartnerApplication.Status.QUALIFIED,
        PartnerApplication.Status.STANDBY,
        PartnerApplication.Status.REJECTED,
        PartnerApplication.Status.WITHDREW,
        PartnerApplication.Status.UNDER_REVIEW,
    }
    if status not in valid_statuses:
        raise DomainError("合作方报名审核状态无效。")
    now = timezone.now()
    application.status = status
    application.reviewed_by = reviewed_by
    application.reviewed_at = now
    application.metadata = {
        **application.metadata,
        "review_note": str(review_note or "").strip(),
        "reviewed_by": member_display_name(reviewed_by) if reviewed_by else "",
    }
    application.save(update_fields=["status", "reviewed_by", "reviewed_at", "metadata"])
    append_event(
        event_type=SystemEvent.EventType.PARTNER_APPLICATION_REVIEWED,
        aggregate_type="PartnerApplication",
        aggregate_id=application.application_id,
        actor_member=reviewed_by,
        payload_json=partner_application_payload(application),
        occurred_at=now,
    )
    return application
