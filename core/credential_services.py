"""Credential issuance and query services.

Credentials are public facts / honours / certificates.
They are NOT a permission source — runtime authorisation MUST go through
``Member → active RoleAssignment → RolePermission → Permission``.
"""

from __future__ import annotations

from typing import Any

from django.db import IntegrityError
from django.db.models import Max
from django.utils import timezone

from .db import atomic_for_model
from .event_ledger import append_event
from .exceptions import DomainError
from .models import (
    CredentialGrant,
    CredentialTemplate,
    Member,
    SystemEvent,
)


def ensure_builtin_credential_templates():
    """Idempotently create built-in credential templates."""
    builtins = [
        {
            "template_id": "credential-template-formal-member-number",
            "code": "formal_member_number",
            "name": "正式成员编号",
            "credential_type": CredentialTemplate.CredentialType.FORMAL_NUMBER,
            "visibility": CredentialTemplate.Visibility.PUBLIC,
            "display_order": 1,
        },
        # Recruitment-direction credentials — these are competence / role areas
        # the community needs filled.  They are NOT permission sources.
        {
            "template_id": "credential-template-company-legal-rep",
            "code": "company_legal_representative",
            "name": "公司法人方向",
            "credential_type": CredentialTemplate.CredentialType.CERTIFICATE,
            "visibility": CredentialTemplate.Visibility.PUBLIC,
            "display_order": 100,
            "description": "需要愿意承担主体责任、参与公司治理的成员。",
            "metadata": {
                "recruitment": {
                    "show_on_application": True,
                    "required_count": 2,
                    "public_label": "公司法人方向",
                    "public_description": "需要愿意承担主体责任、参与公司治理的人",
                    "sort_order": 10,
                },
            },
        },
        {
            "template_id": "credential-template-finance-responsible",
            "code": "finance_responsible_person",
            "name": "财务负责人方向",
            "credential_type": CredentialTemplate.CredentialType.CERTIFICATE,
            "visibility": CredentialTemplate.Visibility.PUBLIC,
            "display_order": 100,
            "description": "负责社区财务审核、预算和公开财务记录。",
            "metadata": {
                "recruitment": {
                    "show_on_application": True,
                    "required_count": 1,
                    "public_label": "财务负责人方向",
                    "public_description": "负责社区财务审核、预算和公开记录",
                    "sort_order": 20,
                },
            },
        },
        {
            "template_id": "credential-template-legal-advisor",
            "code": "legal_advisor",
            "name": "律师/法律顾问方向",
            "credential_type": CredentialTemplate.CredentialType.CERTIFICATE,
            "visibility": CredentialTemplate.Visibility.PUBLIC,
            "display_order": 100,
            "description": "为社区提供法律合规建议和责任文件审核。",
            "metadata": {
                "recruitment": {
                    "show_on_application": True,
                    "required_count": 1,
                    "public_label": "律师/法律顾问方向",
                    "public_description": "为社区提供法律合规建议和文件审核",
                    "sort_order": 30,
                },
            },
        },
        {
            "template_id": "credential-template-medical-support",
            "code": "medical_support",
            "name": "医生/健康支持方向",
            "credential_type": CredentialTemplate.CredentialType.CERTIFICATE,
            "visibility": CredentialTemplate.Visibility.PUBLIC,
            "display_order": 100,
            "description": "为社区成员提供基础健康咨询和急救支持。",
            "metadata": {
                "recruitment": {
                    "show_on_application": True,
                    "required_count": 1,
                    "public_label": "医生/健康支持方向",
                    "public_description": "为社区成员提供基础健康咨询和急救",
                    "sort_order": 40,
                },
            },
        },
        {
            "template_id": "credential-template-electrician-facility",
            "code": "electrician_facility",
            "name": "电工/设施维护方向",
            "credential_type": CredentialTemplate.CredentialType.CERTIFICATE,
            "visibility": CredentialTemplate.Visibility.PUBLIC,
            "display_order": 100,
            "description": "负责电气安全、设施日常维护和修缮。",
            "metadata": {
                "recruitment": {
                    "show_on_application": True,
                    "required_count": 1,
                    "public_label": "电工/设施维护方向",
                    "public_description": "负责电气安全和设施日常维护",
                    "sort_order": 50,
                },
            },
        },
        {
            "template_id": "credential-template-ai-engineer",
            "code": "ai_engineer",
            "name": "AI 工程师方向",
            "credential_type": CredentialTemplate.CredentialType.CERTIFICATE,
            "visibility": CredentialTemplate.Visibility.PUBLIC,
            "display_order": 100,
            "description": "负责社区 AI/自动化系统开发与维护。",
            "metadata": {
                "recruitment": {
                    "show_on_application": True,
                    "required_count": 2,
                    "public_label": "AI 工程师方向",
                    "public_description": "负责社区 AI/自动化系统开发与维护",
                    "sort_order": 60,
                },
            },
        },
        {
            "template_id": "credential-template-content-recorder",
            "code": "content_recorder",
            "name": "内容记录方向",
            "credential_type": CredentialTemplate.CredentialType.CERTIFICATE,
            "visibility": CredentialTemplate.Visibility.PUBLIC,
            "display_order": 100,
            "description": "负责社区事件记录、文档编写和信息公告。",
            "metadata": {
                "recruitment": {
                    "show_on_application": True,
                    "required_count": 2,
                    "public_label": "内容记录方向",
                    "public_description": "负责社区事件记录、文档编写和公告",
                    "sort_order": 70,
                },
            },
        },
        {
            "template_id": "credential-template-life-service",
            "code": "life_service",
            "name": "生活服务方向",
            "credential_type": CredentialTemplate.CredentialType.CERTIFICATE,
            "visibility": CredentialTemplate.Visibility.PUBLIC,
            "display_order": 100,
            "description": "承担餐饮、清洁等日常生活运转支持。",
            "metadata": {
                "recruitment": {
                    "show_on_application": True,
                    "required_count": 3,
                    "public_label": "生活服务方向",
                    "public_description": "承担餐饮、清洁等日常生活运转支持",
                    "sort_order": 80,
                },
            },
        },
    ]
    created = 0
    for spec in builtins:
        obj, was_created = CredentialTemplate.objects.get_or_create(
            code=spec["code"],
            defaults=spec,
        )
        if was_created:
            created += 1
        # Only fill recruitment metadata when the template is missing it — never overwrite
        # existing admin-configured recruitment.
        elif "metadata" in spec:
            current_metadata = dict(obj.metadata or {})
            if "recruitment" not in current_metadata and "recruitment" in spec["metadata"]:
                current_metadata["recruitment"] = spec["metadata"]["recruitment"]
                obj.metadata = current_metadata
                obj.save(update_fields=["metadata"])
    return created


def _next_display_no(serial_no: int) -> str:
    return f"#{serial_no}"


def _issue_credential_unlocked(
    *,
    template: CredentialTemplate,
    member: Member,
    source_type: str = CredentialGrant.SourceType.SYSTEM,
    issued_by: Member | None = None,
    source_proposal=None,
    source_proposal_execution=None,
    serial_no: int | None = None,
    title: str = "",
    metadata: dict[str, Any] | None = None,
) -> CredentialGrant:
    """Create one credential grant *without* opening its own transaction.

    Caller must already be inside a suitable atomic block (e.g. a
    ``select_for_update`` lock transaction).
    """
    display_no = _next_display_no(serial_no) if serial_no is not None else ""
    try:
        grant = CredentialGrant.objects.create(
            template=template,
            member=member,
            serial_no=serial_no,
            display_no=display_no,
            title=title or template.name,
            source_type=source_type,
            issued_by=issued_by,
            issued_at=timezone.now(),
            source_proposal=source_proposal,
            source_proposal_execution=source_proposal_execution,
            metadata=dict(metadata or {}),
        )
    except IntegrityError:
        # Unique constraint violation — another concurrent caller won the race.
        # Re-read the existing grant.
        existing = CredentialGrant.objects.filter(
            template=template,
            member=member,
        ).first()
        if existing is not None:
            return existing
        raise DomainError("凭证发放冲突，请重试。")

    from .event_payloads import credential_grant_payload

    append_event(
        event_type=SystemEvent.EventType.CREDENTIAL_GRANTED,
        aggregate_type="CredentialGrant",
        aggregate_id=grant.grant_id,
        actor_member=issued_by,
        payload_json=credential_grant_payload(grant),
        occurred_at=grant.issued_at,
    )
    return grant


@atomic_for_model(CredentialGrant)
def issue_credential(
    *,
    template: CredentialTemplate,
    member: Member,
    source_type: str = CredentialGrant.SourceType.SYSTEM,
    issued_by: Member | None = None,
    source_proposal=None,
    source_proposal_execution=None,
    serial_no: int | None = None,
    title: str = "",
    metadata: dict[str, Any] | None = None,
) -> CredentialGrant:
    """Issue one credential to *member* under *template*."""
    return _issue_credential_unlocked(
        template=template,
        member=member,
        source_type=source_type,
        issued_by=issued_by,
        source_proposal=source_proposal,
        source_proposal_execution=source_proposal_execution,
        serial_no=serial_no,
        title=title,
        metadata=metadata,
    )


@atomic_for_model(CredentialGrant)
def issue_formal_member_number(
    member: Member,
    *,
    source_proposal=None,
    source_proposal_execution=None,
    issued_by: Member | None = None,
) -> CredentialGrant:
    """Issue or return the existing formal member number for *member*.

    Formal member numbers increment globally (1, 2, 3, …) and are never
    re-used, even if the member later exits or is suspended.

    The outer ``@atomic_for_model`` wraps the entire lock-scoped sequence:
    lock template row → re-check existing → query max_serial →
    create CredentialGrant → write SystemEvent.
    """
    ensure_builtin_credential_templates()
    template = CredentialTemplate.objects.get(code="formal_member_number")

    # Lock the template row to serialise concurrent issuers.
    locked = (
        CredentialTemplate.objects.select_for_update()
        .filter(pk=template.pk)
        .first()
    )
    if locked is None:
        raise DomainError("凭证模板不存在。")

    # Re-check existing *inside* the lock to avoid duplicate issuance.
    existing = CredentialGrant.objects.filter(
        template=template, member=member
    ).first()
    if existing is not None:
        return existing

    max_serial = (
        CredentialGrant.objects.filter(template=template)
        .aggregate(m=Max("serial_no"))["m"]
    )
    next_serial = (max_serial or 0) + 1

    return _issue_credential_unlocked(
        template=template,
        member=member,
        source_type=CredentialGrant.SourceType.PROPOSAL_EXECUTION
        if source_proposal
        else CredentialGrant.SourceType.SYSTEM,
        issued_by=issued_by,
        source_proposal=source_proposal,
        source_proposal_execution=source_proposal_execution,
        serial_no=next_serial,
    )


# ── recruitment helpers ────────────────────────────────────────────

def _recruitment_meta(template: CredentialTemplate) -> dict[str, Any]:
    return (template.metadata or {}).get("recruitment", {}) if template.metadata else {}


def credential_recruitment_gap(template: CredentialTemplate) -> dict[str, Any]:
    """Return full recruitment gap info for a single template.

    ``current_count`` counts only ACTIVE grants (revoked / archived excluded).
    ``missing_count`` floors at 0.  ``is_open`` is True when required_count=0
    (unlimited) or when missing_count > 0.
    """
    meta = _recruitment_meta(template)
    required = int(meta.get("required_count") or 0)
    current = CredentialGrant.objects.filter(
        template=template,
        status=CredentialGrant.Status.ACTIVE,
    ).count()
    missing = max(required - current, 0)
    is_open = (required <= 0) or (missing > 0)
    return {
        "code": template.code,
        "template_code": template.code,
        "label": meta.get("public_label") or template.name,
        "description": meta.get("public_description") or template.description or "",
        "public_label": meta.get("public_label") or template.name,
        "public_description": meta.get("public_description") or template.description or "",
        "required_count": required,
        "current_count": current,
        "missing_count": missing,
        "sort_order": int(meta.get("sort_order") or template.display_order),
        "display_order": template.display_order,
        "is_open": is_open,
    }


def recruitment_credential_options() -> list[dict[str, Any]]:
    """Return active recruitment direction options, each a full gap dict.

    Only templates where ``metadata.recruitment.show_on_application`` is True
    are returned.  The ``formal_member_number`` template is explicitly excluded.
    Sorted in Python by sort_order, display_order, code to avoid JSON-field
    ordering differences across databases.
    """
    templates = CredentialTemplate.objects.filter(
        status=CredentialTemplate.Status.ACTIVE,
    ).exclude(code="formal_member_number")

    rows: list[dict[str, Any]] = []
    for t in templates:
        meta = _recruitment_meta(t)
        if not meta.get("show_on_application"):
            continue
        rows.append(credential_recruitment_gap(t))

    rows.sort(key=lambda r: (r["sort_order"], r.get("display_order", 100), r["code"]))
    return rows


def recruitment_option_for_code(code: str) -> dict[str, Any] | None:
    """Return the full recruitment gap dict for *code* or None."""
    if code == "formal_member_number":
        return None
    t = CredentialTemplate.objects.filter(
        code=code, status=CredentialTemplate.Status.ACTIVE,
    ).first()
    if t is None:
        return None
    meta = _recruitment_meta(t)
    if not meta.get("show_on_application"):
        return None
    return credential_recruitment_gap(t)


def credentials_for_member(member: Member) -> list[dict[str, Any]]:
    """Return public active credentials for *member*."""
    grants = (
        CredentialGrant.objects.filter(
            member=member,
            status=CredentialGrant.Status.ACTIVE,
            template__visibility=CredentialTemplate.Visibility.PUBLIC,
        )
        .select_related("template")
        .order_by("template__display_order", "serial_no")
    )
    return [
        {
            "grant_id": g.grant_id,
            "template_code": g.template.code,
            "template_name": g.template.name,
            "credential_type": g.template.credential_type,
            "display_no": g.display_no,
            "serial_no": g.serial_no,
            "title": g.title,
            "status": g.status,
            "issued_at": g.issued_at,
            "source_type": g.source_type,
        }
        for g in grants
    ]