"""Credential issuance and query services.

Credentials are public facts / honours / certificates.
They are NOT a permission source — runtime authorisation MUST go through
``Member → active RoleAssignment → RolePermission → Permission``.
"""

from __future__ import annotations

import re
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


# Recruitment management -------------------------------------------------

_RECRUITMENT_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")


def normalize_recruitment_template_code(raw: str) -> str:
    """Normalise a user-supplied recruitment template code.

    Rules:
      - strip whitespace
      - lowercase
      - whitespace / hyphens → ``_``
      - only ``a-z``, ``0-9``, ``_`` allowed
      - multiple consecutive ``_`` collapsed to single
      - leading / trailing ``_`` removed
      - must start with a letter
      - length 3-64

    Raises ``DomainError`` when the input cannot be normalised into a valid
    code, including raw Chinese characters.
    """
    if not isinstance(raw, str):
        raise DomainError("编码必须是非空字符串。")
    s = raw.strip().lower()
    if not s:
        raise DomainError("编码不能为空。")
    # Reject any character outside [a-z0-9 _-] – this catches Chinese, emoji etc.
    if not re.fullmatch(r"[a-z0-9 _\-]+", s):
        raise DomainError(
            "编码只能使用小写英文字母、数字和下划线，且必须以字母开头。"
        )
    s = re.sub(r"[\s\-]+", "_", s)
    s = re.sub(r"_+", "_", s)
    s = s.strip("_")
    if not _RECRUITMENT_CODE_RE.match(s):
        raise DomainError(
            "编码必须以小写英文字母开头，长度 3 到 64 个字符，且只能包含字母、数字和下划线。"
        )
    return s


def create_recruitment_template(
    *,
    actor_member: Member,
    code: str,
    public_label: str,
    public_description: str = "",
    required_count: int | str = 0,
    sort_order: int | str = 100,
) -> CredentialTemplate:
    """Create a restricted recruitment-direction ``CredentialTemplate``.

    Only governance principals may call this.  The new template is always
    ``certificate`` / ``public`` / ``active``.  No ``CredentialGrant`` is
    issued and no event is written.

    Raises ``DomainError`` when:
    - *actor_member* is not a governance principal.
    - *code* is invalid or normalises to ``formal_member_number``.
    - *code* already exists.
    - *public_label* is empty or exceeds 255 characters.
    - *public_description* exceeds 500 characters.
    - *required_count* or *sort_order* is not a valid integer.
    """
    from core.access import is_governance_principal

    if not is_governance_principal(actor_member):
        raise DomainError("只有治理成员可以新增招募方向。")

    norm_code = normalize_recruitment_template_code(code)
    if norm_code == "formal_member_number":
        raise DomainError("正式成员编号不能作为招募方向编码。")

    if CredentialTemplate.objects.filter(code=norm_code).exists():
        raise DomainError("招募方向编码已存在。")

    public_label = str(public_label or "").strip()
    if not public_label:
        raise DomainError("公开名称不能为空。")
    if len(public_label) > 255:
        raise DomainError("公开名称不能超过 255 个字符。")

    public_description = str(public_description or "").strip()
    if len(public_description) > 500:
        raise DomainError("公开说明不能超过 500 个字符。")

    try:
        required_count = int(required_count)
    except (TypeError, ValueError):
        raise DomainError("需要人数必须是整数。")
    if required_count < 0:
        raise DomainError("需要人数不能为负数。")

    try:
        sort_order = int(sort_order)
    except (TypeError, ValueError):
        raise DomainError("排序必须是整数。")

    from uuid import uuid4

    template_id = f"credential-template-{norm_code}"
    # If template_id is taken (unlikely but defensive), append a suffix.
    if CredentialTemplate.objects.filter(template_id=template_id).exists():
        template_id = f"credential-template-{norm_code}-{uuid4().hex[:6]}"

    template = CredentialTemplate.objects.create(
        template_id=template_id,
        code=norm_code,
        name=public_label,
        description=public_description,
        credential_type=CredentialTemplate.CredentialType.CERTIFICATE,
        status=CredentialTemplate.Status.ACTIVE,
        visibility=CredentialTemplate.Visibility.PUBLIC,
        display_order=sort_order,
        metadata={
            "recruitment": {
                "show_on_application": True,
                "public_label": public_label,
                "public_description": public_description,
                "required_count": required_count,
                "sort_order": sort_order,
            },
        },
    )
    return template


def recruitment_templates_for_management() -> list[dict[str, Any]]:
    """Return all recruitment-direction templates with gap info for management.

    Ensures built-in templates exist, then returns every active
    ``CredentialTemplate`` except ``formal_member_number``, each annotated
    with its current recruitment metadata and gap counts.  Sorted by
    ``sort_order``, ``display_order``, ``code``.
    """
    ensure_builtin_credential_templates()
    templates = CredentialTemplate.objects.filter(
        status=CredentialTemplate.Status.ACTIVE,
    ).exclude(code="formal_member_number")

    rows: list[dict[str, Any]] = []
    for t in templates:
        gap = credential_recruitment_gap(t)
        meta = _recruitment_meta(t)
        rows.append({
            "code": t.code,
            "name": t.name,
            "credential_type": t.credential_type,
            "show_on_application": bool(meta.get("show_on_application")),
            "public_label": gap["public_label"],
            "public_description": gap["public_description"],
            "required_count": gap["required_count"],
            "current_count": gap["current_count"],
            "missing_count": gap["missing_count"],
            "sort_order": gap["sort_order"],
            "display_order": gap["display_order"],
            "is_open": gap["is_open"],
        })

    rows.sort(key=lambda r: (r["sort_order"], r.get("display_order", 100), r["code"]))
    return rows


def update_recruitment_template_config(
    *,
    actor_member: Member,
    template_code: str,
    show_on_application: bool = True,
    public_label: str = "",
    public_description: str = "",
    required_count: int | str = 0,
    sort_order: int | str = 100,
) -> dict[str, Any]:
    """Update the recruitment config of a credential template.

    Only governance principals may call this.  Updates are written into
    ``CredentialTemplate.metadata["recruitment"]`` — no new tables, no new
    migrations, no ``CredentialGrant`` issuance.

    Raises ``DomainError`` when:
    - *actor_member* is not a governance principal.
    - *template_code* is ``formal_member_number``.
    - *template_code* cannot be found.
    - *required_count* or *sort_order* is not a valid integer.

    Returns the full recruitment gap dict after the update so callers can
    re-render with fresh data.
    """
    from core.access import is_governance_principal

    if not is_governance_principal(actor_member):
        raise DomainError("只有治理成员可以维护招募方向配置。")

    if template_code == "formal_member_number":
        raise DomainError("正式成员编号不是招募方向，不能修改。")

    try:
        required_count = int(required_count)
    except (TypeError, ValueError):
        raise DomainError("需要人数必须是整数。")
    if required_count < 0:
        raise DomainError("需要人数不能为负数。")

    try:
        sort_order = int(sort_order)
    except (TypeError, ValueError):
        raise DomainError("排序必须是整数。")

    template = CredentialTemplate.objects.filter(
        code=template_code, status=CredentialTemplate.Status.ACTIVE,
    ).first()
    if template is None:
        raise DomainError(f"未找到招募方向模板：{template_code}")

    label = str(public_label or template.name).strip()
    if not label:
        raise DomainError("公开名称不能为空。")
    if len(label) > 255:
        raise DomainError("公开名称不能超过 255 个字符。")

    desc = str(public_description or "").strip()
    if len(desc) > 500:
        raise DomainError("公开说明不能超过 500 个字符。")

    current_metadata = dict(template.metadata or {})
    current_metadata["recruitment"] = {
        "show_on_application": bool(show_on_application),
        "public_label": label,
        "public_description": desc,
        "required_count": required_count,
        "sort_order": sort_order,
    }
    # Sync top-level name / description so the template table stays consistent.
    template.name = label
    template.description = desc
    template.metadata = current_metadata
    template.save(update_fields=["name", "description", "metadata", "updated_at"])

    return credential_recruitment_gap(template)