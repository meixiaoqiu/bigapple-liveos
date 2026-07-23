"""Application submission and proposal-driven admission services."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.utils import timezone

from core.db import atomic_for_model
from core.event_ledger import PUBLIC_LEDGER_SCHEMA, append_event
from core.event_payloads import _private, member_display_name, public_member_label
from core.exceptions import DomainError
from core.member_roles import (
    ROLE_CANDIDATE,
    ROLE_FORMAL_MEMBER,
    ROLE_GOVERNANCE_MEMBER,
    ensure_member_role,
    ensure_role_assignment,
    member_has_role,
)
from core.models import Member, MemberApplication, PartnerApplication, Proposal, SystemEvent

from .identity_services import register_member
from .models.applications import ROLE_GAP_LABELS
from .models.events import Event


DISABLED_MEMBER_STATUSES: frozenset[str] = frozenset({
    Member.Status.SUSPENDED,
    Member.Status.EXITED,
})


def _nonblank(value: object, field_label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise DomainError(f"{field_label}不能为空。")
    return text


def _create_application_account(*, username: str, password: str):
    cleaned_username = _nonblank(username, "登录账号")
    cleaned_password = _nonblank(password, "登录密码")
    if Member.objects.filter(member_no=cleaned_username).exists():
        raise DomainError("该登录账号已被成员编号使用。")
    try:
        validate_password(cleaned_password)
    except DjangoValidationError as exc:
        raise DomainError(f"登录密码不符合要求：{'；'.join(exc.messages)}") from exc
    user_model = get_user_model()
    if user_model.objects.filter(username=cleaned_username).exists():
        raise DomainError("登录账号已存在。")
    try:
        return user_model.objects.create_user(username=cleaned_username, password=cleaned_password)
    except IntegrityError as exc:
        raise DomainError("登录账号已存在。") from exc


def _list_payload(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.replace("\n", ",").split(",") if part.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(part).strip() for part in value if str(part).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _json_answer_payload(value: object) -> list[dict[str, Any]]:
    if not value:
        return []
    if not isinstance(value, (list, tuple)):
        raise DomainError("动态问答必须是数组。")
    answers: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise DomainError("动态问答条目必须是对象。")
        answers.append(
            {
                "key": str(item.get("key") or "").strip(),
                "label": str(item.get("label") or "").strip(),
                "type": str(item.get("type") or "textarea").strip() or "textarea",
                "answer": str(item.get("answer") or "").strip(),
            }
        )
    return answers


def _application_member_profile(application: MemberApplication) -> dict[str, Any]:
    return {
        "source": "member_application",
        "application_id": application.application_id,
        "role_gap": application.role_gap,
        "motivation": application.motivation,
        "skills": application.capability_scores,
        "availability_hours_per_week": application.availability_hours_per_week,
        "availability_slots": application.availability_slots,
        "dynamic_answers": application.dynamic_answers,
        "document_authority_domains": application.document_authority_domains,
        "can_issue_responsibility_documents": application.can_issue_responsibility_documents,
    }


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


def _application_role_gap_label(application: MemberApplication) -> str:
    """Return the public-facing role-gap label, preferring snapshot metadata."""
    metadata = application.metadata or {}
    return (
        str(metadata.get("role_gap_label") or "").strip()
        or ROLE_GAP_LABELS.get(application.role_gap, application.role_gap or "")
    )


def member_application_payload(application: MemberApplication) -> dict[str, Any]:
    role_label = _application_role_gap_label(application)
    applicant_label = public_member_label(application.applicant_name)
    return {
        "schema": PUBLIC_LEDGER_SCHEMA,
        "subject": {
            "type": "member_application",
            "ref": application.application_id,
            "label": "成员报名",
        },
        "action": application.status,
        "stage": application.status,
        "summary": (
            f"收到成员报名，报名者 {applicant_label}，"
            f"意向角色 {role_label}（{application.get_status_display()}）。"
        ),
        "public_facts": {
            "application_id": application.application_id,
            "public_applicant_label": applicant_label,
            "role_gap": application.role_gap,
            "role_gap_label": role_label,
            "stage": application.status,
            "status": application.status,
        },
        "private_commitments": [
            _private("applicant_name_raw", reason="真实姓名属于隐私"),
            _private("contact", reason="联系方式属于隐私"),
            _private("account_user_id", present=bool(application.account_user_id), reason="账号ID属于隐私"),
            _private("requested_member_no", present=bool(application.requested_member_no), reason="成员编号属于隐私"),
            _private("linked_member_id", present=bool(application.linked_member_id), reason="关联成员内部ID"),
            _private("motivation", reason="报名动机属于隐私"),
            _private("availability_hours_per_week", reason="可用时长属于隐私"),
            _private("availability_slots", present=bool(application.availability_slots), reason="可用时段属于隐私"),
            _private("capability_scores", present=bool(application.capability_scores), reason="能力评分属于隐私"),
            _private("dynamic_answers", present=bool(application.dynamic_answers), reason="动态问答内容属于隐私"),
            _private("document_authority_domains", reason="文件签署域属于隐私"),
            _private("admission_proposal_id", present=bool(application.admission_proposal_id), reason="准入提案内部ID"),
            _private("frozen_at", reason="冻结时间"),
            _private("submitted_at", reason="提交时间"),
            _private("decided_at", reason="决定时间"),
            _private("metadata", present=bool(application.metadata), reason="元数据"),
        ],
    }


def partner_application_payload(application: PartnerApplication) -> dict[str, Any]:
    return {
        "schema": PUBLIC_LEDGER_SCHEMA,
        "subject": {
            "type": "partner_application",
            "ref": application.application_id,
            "label": "合作方报名",
        },
        "action": application.status,
        "stage": application.status,
        "summary": (
            f"收到合作方「{application.organization_name}」报名，"
            f"服务领域 {', '.join(application.service_domains) if application.service_domains else '未指定'}。"
        ),
        "public_facts": {
            "application_id": application.application_id,
            "organization_name": application.organization_name,
            "service_domains": application.service_domains,
            "status": application.status,
            "stage": application.status,
        },
        "private_commitments": [
            _private("contact_name", reason="联系人姓名属于隐私"),
            _private("contact_info", reason="联系方式属于隐私"),
            _private("qualification_summary", reason="资质摘要属于隐私"),
            _private("quote_summary", reason="报价摘要属于隐私"),
            _private("constraints", present=bool(application.constraints), reason="约束条件"),
            _private("submitted_at", reason="提交时间"),
            _private("reviewed_at", reason="审核时间"),
            _private("metadata", present=bool(application.metadata), reason="元数据"),
        ],
    }


def _append_member_application_public_event_once(
    *,
    event_id: str,
    title: str,
    summary: str,
    severity: str,
    payload: dict[str, Any],
    occurred_at=None,
) -> Event | None:
    """Idempotent public Event writer for the observer timeline.

    Returns the existing ``Event`` without modification when *event_id*
    already exists so repeated service calls never produce duplicate observer
    records.
    """
    existing = Event.objects.filter(event_id=event_id).first()
    if existing is not None:
        return existing
    return Event.objects.create(
        event_id=event_id,
        event_type=Event.EventType.GOVERNANCE,
        simulation_day=0,
        severity=severity,
        title=title,
        summary=summary,
        occurred_at=occurred_at or timezone.now(),
        generated_by=Event.GeneratedBy.LIVE_OS,
        visibility=Event.Visibility.PUBLIC,
        payload=payload,
    )


@atomic_for_model(MemberApplication)
def submit_member_application(
    *,
    applicant_name: str,
    contact: str,
    motivation: str,
    availability_hours_per_week: int = 0,
    role_gap: str = "",
    availability_slots: object = None,
    dynamic_answers: object = None,
    capability_scores: dict[str, int] | None = None,
    can_issue_responsibility_documents: bool = False,
    document_authority_domains: object = None,
    requested_member_no: str = "",
    account_username: str = "",
    account_password: str = "",
    account_user=None,
    metadata: dict[str, Any] | None = None,
    submitted_at=None,
) -> MemberApplication:
    """Submit a member application and create the applicant's minimal member identity.

    The account and ``Member`` are created before admission approval so the
    applicant can enter a restricted workspace. Full member capabilities still
    require proposal-driven admission.
    """

    if availability_hours_per_week < 0:
        raise DomainError("每周可投入小时不能为负数。")
    now = submitted_at or timezone.now()
    cleaned_requested_member_no = str(requested_member_no or "").strip()
    if account_user is None and account_username:
        cleaned_account_username = str(account_username or "").strip()
        if not cleaned_requested_member_no:
            cleaned_requested_member_no = cleaned_account_username
        if cleaned_requested_member_no != cleaned_account_username:
            raise DomainError("成员编号必须与报名登录账号一致。")
    elif account_user is not None:
        account_user_username = str(account_user.get_username() or "").strip()
        if not cleaned_requested_member_no:
            cleaned_requested_member_no = account_user_username
        if cleaned_requested_member_no != account_user_username:
            raise DomainError("成员编号必须与报名登录账号一致。")
    if account_user is None and (account_username or account_password):
        account_user = _create_application_account(username=account_username, password=account_password)
    existing_member = None
    if account_user is not None:
        existing_member = Member.objects.filter(user=account_user).first()
    if cleaned_requested_member_no:
        member_with_no = Member.objects.filter(member_no=cleaned_requested_member_no).first()
        if member_with_no is not None and member_with_no != existing_member:
            raise DomainError("成员编号已存在。")
        if existing_member is not None and existing_member.member_no != cleaned_requested_member_no:
            raise DomainError("当前账号已绑定其他成员编号。")
    active_application_statuses = {
        MemberApplication.Status.SUBMITTED,
        MemberApplication.Status.ADMISSION_VOTING,
        MemberApplication.Status.ADMITTED,
    }
    if existing_member is not None:
        if existing_member.status in DISABLED_MEMBER_STATUSES:
            raise DomainError("当前账号成员状态已停用，不能提交成员报名。")
        if member_has_role(existing_member, ROLE_FORMAL_MEMBER):
            raise DomainError("当前账号已经是正式成员，不能重复报名。")
        active_application_exists = MemberApplication.objects.filter(
            linked_member=existing_member,
            status__in=active_application_statuses,
        ).exists()
        if active_application_exists:
            raise DomainError("当前账号已有未结束的成员报名，不能重复提交。")
    # Validate and snapshot the recruitment option.
    from core.credential_services import ensure_builtin_credential_templates, recruitment_option_for_code

    ensure_builtin_credential_templates()
    role_gap_code = str(role_gap or "").strip()
    recruitment_opt = recruitment_option_for_code(role_gap_code)
    if recruitment_opt is None:
        raise DomainError("申请方向无效或暂未开放。")
    if not recruitment_opt["is_open"]:
        raise DomainError("该申请方向当前缺口已满，暂不能提交。")

    gap_snapshot = {
        "role_gap_label": recruitment_opt["label"],
        "role_gap_description": recruitment_opt.get("description", ""),
        "role_gap_required_count": recruitment_opt["required_count"],
        "role_gap_current_count": recruitment_opt["current_count"],
        "role_gap_missing_count": recruitment_opt["missing_count"],
        "role_gap_credential_template_code": role_gap_code,
    }

    application = MemberApplication.objects.create(
        application_id=generate_member_application_id(),
        applicant_name=_nonblank(applicant_name, "报名人名称"),
        contact=_nonblank(contact, "联系方式"),
        motivation=_nonblank(motivation, "报名动机"),
        availability_hours_per_week=availability_hours_per_week,
        role_gap=role_gap_code,
        availability_slots=_list_payload(availability_slots),
        capability_scores=dict(capability_scores or {}),
        can_issue_responsibility_documents=can_issue_responsibility_documents,
        document_authority_domains=_list_payload(document_authority_domains),
        dynamic_answers=_json_answer_payload(dynamic_answers),
        requested_member_no=cleaned_requested_member_no,
        account_user=account_user,
        submitted_at=now,
        frozen_at=now,
        metadata=dict(metadata or {}, **gap_snapshot),
    )
    if existing_member is None:
        if not cleaned_requested_member_no:
            cleaned_requested_member_no = f"applicant-{application.application_id[-8:]}"
            application.requested_member_no = cleaned_requested_member_no
        existing_member = register_member(
            member_no=cleaned_requested_member_no,
            display_name=application.applicant_name,
            status=Member.Status.PENDING_REVIEW,
            batch_id=str(application.metadata.get("batch_id") or ""),
            joined_simulation_day=None,
            credit_floor=-100,
            profile=_application_member_profile(application),
            created_by={"actor_type": "member_application", "display_name": application.applicant_name},
        )
        if account_user is not None:
            existing_member.user = account_user
            existing_member.save(update_fields=["user"])
    else:
        existing_member.status = Member.Status.PENDING_REVIEW
        existing_member.display_name = existing_member.display_name or application.applicant_name
        existing_member.profile = {
            **(existing_member.profile or {}),
            **_application_member_profile(application),
        }
        existing_member.save(update_fields=["status", "display_name", "profile"])
    ensure_role_assignment(existing_member, ensure_member_role(ROLE_CANDIDATE))
    application.linked_member = existing_member
    application.save(update_fields=["requested_member_no", "linked_member"])

    # SystemEvent first so seq order reflects: submitted → proposal created → vote → result
    append_event(
        event_type=SystemEvent.EventType.MEMBER_APPLICATION_SUBMITTED,
        aggregate_type="MemberApplication",
        aggregate_id=application.application_id,
        payload_json=member_application_payload(application),
        occurred_at=now,
    )
    # Auto-create the member_admission proposal so every application immediately
    # enters the governance voting pipeline. No manual "review" step exists.
    create_member_application_admission_proposal(
        application=application,
        reason=f"系统自动发起：接纳 {application.applicant_name} 成为大苹果正式成员。",
    )
    _append_member_application_public_event_once(
        event_id=f"member-application-submitted-{application.application_id}",
        title="收到成员报名",
        summary="收到一名成员报名，准入提案已进入治理表决。",
        severity=Event.Severity.INFO,
        payload={
            "source": "member_application",
            "stage": "submitted",
            "application_id": application.application_id,
            "proposal_no": application.admission_proposal.proposal_no if application.admission_proposal_id else "",
            "public_applicant_label": public_member_label(
                application.applicant_name,
                application.linked_member.member_no if application.linked_member_id else "",
            ),
            "role_gap": application.role_gap,
            "role_gap_label": _application_role_gap_label(application),
        },
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
def create_member_application_admission_proposal(
    *,
    application: MemberApplication,
    proposer_member: Member | None = None,
    reason: str = "",
    voter_scope_role=None,
    deadline_at=None,
) -> Proposal:
    """Create the governance proposal used to admit a submitted member application."""

    if application.status not in {
        MemberApplication.Status.SUBMITTED,
        MemberApplication.Status.ADMISSION_VOTING,
    }:
        raise DomainError("只有已提交或准入表决中的报名可以绑定准入提案。")
    if application.linked_member_id is None:
        raise DomainError("成员报名尚未绑定最小成员身份。")
    if application.admission_proposal_id:
        return application.admission_proposal

    from core.proposals.lifecycle import create_proposal

    voter_role = voter_scope_role or ensure_member_role(ROLE_GOVERNANCE_MEMBER)
    body = str(reason or "").strip() or f"接纳 {application.applicant_name} 成为大苹果正式成员。"
    proposal = create_proposal(
        title=f"接纳成员报名：{application.applicant_name}",
        body=body,
        proposal_type=Proposal.ProposalType.MEMBER_ADMISSION,
        proposer_member=proposer_member,
        organization=voter_role.organization,
        voter_scope_type=Proposal.VoterScopeType.ROLE,
        voter_scope_role=voter_role,
        pass_ratio=50,
        quorum_count=None,
        allow_vote_change=True,
        deadline_at=deadline_at,
        payload_json={
            "action": "admit_member_application",
            "application_id": application.application_id,
            "target_member_id": application.linked_member_id,
            "target_member_no": application.linked_member.member_no,
            "applicant_name": application.applicant_name,
            "role_gap": application.role_gap,
            "reason": body,
        },
        status=Proposal.Status.VOTING,
    )
    application.admission_proposal = proposal
    application.status = MemberApplication.Status.ADMISSION_VOTING
    application.save(update_fields=["admission_proposal", "status"])
    return proposal


@atomic_for_model(MemberApplication)
def admit_member_application_from_proposal(
    *,
    application: MemberApplication,
    proposal: Proposal,
    executor_member: Member | None = None,
    execution=None,
    admitted_at=None,
) -> MemberApplication:
    """Apply a passed member-admission proposal to the application and linked member."""

    if proposal.proposal_type != Proposal.ProposalType.MEMBER_ADMISSION:
        raise DomainError("提案类型不是成员准入。")
    if proposal.status != Proposal.Status.PASSED:
        raise DomainError("只有已通过的成员准入提案才能执行。")
    if application.linked_member_id is None:
        raise DomainError("成员报名尚未绑定最小成员身份。")
    if application.admission_proposal_id and application.admission_proposal_id != proposal.pk:
        raise DomainError("成员报名关联的准入提案不一致。")

    now = admitted_at or timezone.now()
    member = application.linked_member
    formal_role = ensure_member_role(ROLE_FORMAL_MEMBER)
    from core.role_assignment_services import create_role_assignment

    assignment = create_role_assignment(
        member=member,
        role=formal_role,
        granted_by=executor_member,
        source_type="proposal",
        source_proposal=proposal,
        source_proposal_execution=execution,
    )
    member.status = Member.Status.ADMITTED
    member.metadata = {
        **(member.metadata or {}),
        "application_status": MemberApplication.Status.ADMITTED,
        "latest_application_id": application.application_id,
        "admission_proposal_id": proposal.pk,
    }
    member.profile = {
        **(member.profile or {}),
        **_application_member_profile(application),
        "admission_status": MemberApplication.Status.ADMITTED,
    }
    member.save(update_fields=["status", "metadata", "profile"])

    application.status = MemberApplication.Status.ADMITTED
    application.decided_by = executor_member
    application.decided_at = now
    application.admission_proposal = proposal
    application.metadata = {
        **(application.metadata or {}),
        "decision_note": str(proposal.body or "准入提案已执行。").strip(),
        "decided_by_display": member_display_name(executor_member) if executor_member else "",
        "formal_role_assignment_id": assignment.pk,
    }
    application.save(update_fields=["status", "decided_by", "decided_at", "admission_proposal", "metadata"])
    append_event(
        event_type=SystemEvent.EventType.MEMBER_APPLICATION_REVIEWED,
        aggregate_type="MemberApplication",
        aggregate_id=application.application_id,
        actor_member=executor_member,
        payload_json=member_application_payload(application),
        occurred_at=now,
    )
    _append_member_application_public_event_once(
        event_id=f"member-application-admitted-{application.application_id}",
        title="新成员已加入",
        summary=f"成员 {public_member_label(application.applicant_name, member.member_no)} 已通过准入表决并加入社区。",
        severity=Event.Severity.INFO,
        payload={
            "source": "member_application",
            "stage": "admitted",
            "application_id": application.application_id,
            "proposal_no": proposal.proposal_no,
            "public_member_label": public_member_label(application.applicant_name, member.member_no),
            "role_gap": application.role_gap,
            "role_gap_label": _application_role_gap_label(application),
        },
        occurred_at=now,
    )
    return application


@atomic_for_model(MemberApplication)
def reject_member_application_from_failed_proposal(
    *,
    application: MemberApplication,
    proposal: Proposal,
    at_time=None,
) -> MemberApplication:
    """Reject a member application when its member_admission proposal fails.

    Called from the voting lifecycle when a MEMBER_ADMISSION proposal
    transitions to FAILED (deadline expired without sufficient yes votes).
    This is the ONLY path that sets an application to REJECTED — there is
    no standalone "reject" action a governance member can trigger directly.
    """

    if proposal.proposal_type != Proposal.ProposalType.MEMBER_ADMISSION:
        raise DomainError("提案类型不是成员准入。")
    if proposal.status != Proposal.Status.FAILED:
        raise DomainError("只有未通过的成员准入提案才能触发报名拒绝。")
    if application.status == MemberApplication.Status.REJECTED:
        return application
    now = at_time or timezone.now()
    application.status = MemberApplication.Status.REJECTED
    application.decided_at = now
    application.metadata = {
        **(application.metadata or {}),
        "decision_note": f"准入提案 {proposal.proposal_no} 未通过（{proposal.get_status_display()}），报名自动拒绝。",
    }
    application.save(update_fields=["status", "decided_at", "metadata"])
    if application.linked_member_id:
        member = application.linked_member
        member.status = Member.Status.APPLICATION_REJECTED
        member.metadata = {
            **(member.metadata or {}),
            "application_status": MemberApplication.Status.REJECTED,
            "latest_application_id": application.application_id,
        }
        member.save(update_fields=["status", "metadata"])
    append_event(
        event_type=SystemEvent.EventType.MEMBER_APPLICATION_REVIEWED,
        aggregate_type="MemberApplication",
        aggregate_id=application.application_id,
        payload_json=member_application_payload(application),
        occurred_at=now,
    )
    raw_reason = str((application.metadata or {}).get("decision_note", "")).strip()
    sanitized_reason = raw_reason[:200]
    _append_member_application_public_event_once(
        event_id=f"member-application-rejected-{application.application_id}",
        title="成员报名未通过",
        summary=f"成员报名 {public_member_label(application.applicant_name, application.linked_member.member_no if application.linked_member_id else '')} 未通过准入表决。",
        severity=Event.Severity.WARNING,
        payload={
            "source": "member_application",
            "stage": "rejected",
            "application_id": application.application_id,
            "proposal_no": proposal.proposal_no,
            "public_applicant_label": public_member_label(
                application.applicant_name,
                application.linked_member.member_no if application.linked_member_id else "",
            ),
            "role_gap": application.role_gap,
            "role_gap_label": _application_role_gap_label(application),
            "reason": sanitized_reason,
        },
        occurred_at=now,
    )
    return application


@atomic_for_model(MemberApplication)
def create_approval_proposal_for_application(
    *,
    application: MemberApplication,
    submitted_by: Member,
) -> "ApprovalProposal":
    """Create an ``ApprovalProposal`` for this member application.
    Idempotent — returns existing if one already exists.
    """
    from core.models import ApprovalProposal
    from core.proposal_services import create_approval_proposal as _create_ap

    target_id = getattr(application, "application_id", str(application.pk))
    dedupe = f"member_application:{target_id}:approval"
    existing = ApprovalProposal.objects.filter(
        proposal_type=ApprovalProposal.ProposalType.MEMBER_APPLICATION,
        dedupe_key=dedupe,
    ).first()
    if existing:
        return existing

    return _create_ap(
        proposal_type=ApprovalProposal.ProposalType.MEMBER_APPLICATION,
        dedupe_key=dedupe,
        title=f"成员申请审批：{application.applicant_name}",
        submitted_by=submitted_by,
        target_type="member_application",
        target_id=target_id,
        summary=_application_role_gap_label(application),
        approval_tier=ApprovalProposal.Tier.SINGLE,
    )


@atomic_for_model(MemberApplication)
def admit_member_application_from_approval_proposal(
    *,
    proposal,
    actor: Member,
) -> MemberApplication:
    """Execute callback for an approved MEMBER_APPLICATION ``ApprovalProposal``."""
    from core.models import ApprovalProposal as AP, MemberApplication as MA

    application = MemberApplication.objects.get(
        **{MA._meta.pk.name: proposal.target_id}
    )
    if application.status == MA.Status.ADMITTED:
        return application
    if application.status == MA.Status.REJECTED:
        raise DomainError("该报名已被拒绝。")

    member = application.linked_member
    from core.member_roles import ensure_member_role, ROLE_FORMAL_MEMBER
    from core.role_assignment_services import create_role_assignment as _create_ra

    formal_role = ensure_member_role(ROLE_FORMAL_MEMBER)
    _create_ra(
        member=member,
        role=formal_role,
        granted_by=actor,
        source_type="proposal",
    )
    member.status = Member.Status.ADMITTED
    member.metadata = {**(member.metadata or {}),
                       "application_status": MA.Status.ADMITTED,
                       "latest_application_id": application.application_id}
    member.profile = {**(member.profile or {}),
                      **_application_member_profile(application),
                      "admission_status": MA.Status.ADMITTED}
    member.save(update_fields=["status", "metadata", "profile"])
    application.status = MA.Status.ADMITTED
    application.decided_by = actor
    application.decided_at = timezone.now()
    application.save(update_fields=["status", "decided_by", "decided_at"])
    append_event(
        event_type=SystemEvent.EventType.MEMBER_APPLICATION_REVIEWED,
        aggregate_type="MemberApplication",
        aggregate_id=application.application_id,
        actor_member=actor,
        payload_json=member_application_payload(application),
        occurred_at=timezone.now(),
    )
    return application


@atomic_for_model(MemberApplication)
def reject_member_application_from_approval_proposal(
    *,
    proposal,
    reason: str = "",
) -> MemberApplication:
    """Reject callback for a rejected MEMBER_APPLICATION ``ApprovalProposal``."""
    from core.models import MemberApplication as MA

    application = MemberApplication.objects.get(
        **{MA._meta.pk.name: proposal.target_id}
    )
    if application.status in (MA.Status.REJECTED, MA.Status.ADMITTED):
        return application

    application.status = MA.Status.REJECTED
    application.decided_at = timezone.now()
    application.metadata = {**(application.metadata or {}),
                            "decision_note": reason or "审批提案已拒绝。"}
    application.save(update_fields=["status", "decided_at", "metadata"])
    if application.linked_member_id:
        member = application.linked_member
        member.status = Member.Status.APPLICATION_REJECTED
        member.metadata = {**(member.metadata or {}),
                           "application_status": MA.Status.REJECTED}
        member.save(update_fields=["status", "metadata"])
    append_event(
        event_type=SystemEvent.EventType.MEMBER_APPLICATION_REVIEWED,
        aggregate_type="MemberApplication",
        aggregate_id=application.application_id,
        payload_json=member_application_payload(application),
        occurred_at=timezone.now(),
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
