"""成员专业资格的录入、撤销与当前有效性查询。"""

from __future__ import annotations

from django.db.models import Q
from django.utils import timezone

from .access import member_can_administer
from .db import atomic_for_model
from .exceptions import DomainError
from .governance_setup import PROFESSIONAL_QUALIFICATION_MANAGE_PERMISSION
from .member_roles import ROLE_COVENANTER, member_allows_role_facts, member_has_role, member_role_filter
from .models import Member, MemberProfessionalQualification, ProfessionalDomain


def _normalised_domain_code(code: str) -> str:
    return str(code).strip().lower().replace(" ", "-")


@atomic_for_model(ProfessionalDomain)
def ensure_professional_domain(*, code: str, name: str, description: str = "") -> ProfessionalDomain:
    """幂等创建或更新启用中的专业领域定义。"""

    cleaned_code = _normalised_domain_code(code)
    cleaned_name = str(name).strip()
    if not cleaned_code or not cleaned_name:
        raise DomainError("专业领域代码和名称不能为空。")
    domain, _created = ProfessionalDomain.objects.get_or_create(
        code=cleaned_code,
        defaults={
            "name": cleaned_name,
            "description": str(description).strip(),
            "status": ProfessionalDomain.Status.ACTIVE,
        },
    )
    changed_fields: list[str] = []
    if domain.name != cleaned_name:
        domain.name = cleaned_name
        changed_fields.append("name")
    if domain.description != str(description).strip():
        domain.description = str(description).strip()
        changed_fields.append("description")
    if domain.status != ProfessionalDomain.Status.ACTIVE:
        domain.status = ProfessionalDomain.Status.ACTIVE
        changed_fields.append("status")
    if changed_fields:
        changed_fields.append("updated_at")
        domain.save(update_fields=changed_fields)
    return domain


def _require_qualification_subject(member: Member, *, at_time) -> None:
    if not member_allows_role_facts(member):
        raise DomainError("成员或登录账号当前不可持有专业资格。")
    if not member_has_role(member, ROLE_COVENANTER, checked_at=at_time):
        raise DomainError("只有当前有效的守约者可以录入专业资格。")


def _require_qualification_administrator(member: Member, *, action: str) -> None:
    """校验写入专业资格权威事实所需的明确维护能力。"""

    if not member_allows_role_facts(member):
        raise DomainError(f"{action}人当前不可用。")
    if not member_can_administer(member, PROFESSIONAL_QUALIFICATION_MANAGE_PERMISSION):
        raise DomainError(f"只有具备专业资格维护权限的管理员可以{action}专业资格。")


@atomic_for_model(MemberProfessionalQualification)
def record_external_professional_qualification(
    *,
    member: Member,
    domain: ProfessionalDomain,
    confirmed_by: Member,
    external_confirmation_source: str,
    confirmed_at=None,
    valid_from=None,
    valid_until=None,
    notes: str = "",
) -> MemberProfessionalQualification:
    """录入外部确认完成后的专业资格，不实现面试、考试或评估流程。"""

    now = timezone.now()
    starts_at = valid_from or now
    source = str(external_confirmation_source).strip()
    if domain.status != ProfessionalDomain.Status.ACTIVE:
        raise DomainError("专业领域未启用，不能录入资格。")
    _require_qualification_subject(member, at_time=starts_at)
    _require_qualification_administrator(confirmed_by, action="确认")
    if not source:
        raise DomainError("必须记录外部确认来源。")
    if valid_until is not None and valid_until <= starts_at:
        raise DomainError("专业资格失效时间必须晚于生效时间。")

    expire_elapsed_professional_qualifications(member=member, domain=domain, at_time=starts_at)
    if has_current_professional_qualification(member, domain=domain, at_time=starts_at):
        raise DomainError("该成员在此专业领域已有当前有效资格。")
    return MemberProfessionalQualification.objects.create(
        member=member,
        domain=domain,
        status=MemberProfessionalQualification.Status.ACTIVE,
        external_confirmation_source=source,
        confirmed_by=confirmed_by,
        confirmed_at=confirmed_at or now,
        valid_from=starts_at,
        valid_until=valid_until,
        notes=str(notes).strip(),
    )


def expire_elapsed_professional_qualifications(
    *,
    member: Member | None = None,
    domain: ProfessionalDomain | None = None,
    at_time=None,
) -> int:
    """将到期仍标记有效的资格转为已过期，并保留完整记录。"""

    checked_at = at_time or timezone.now()
    queryset = MemberProfessionalQualification.objects.filter(
        status=MemberProfessionalQualification.Status.ACTIVE,
        valid_until__isnull=False,
        valid_until__lte=checked_at,
    )
    if member is not None:
        queryset = queryset.filter(member=member)
    if domain is not None:
        queryset = queryset.filter(domain=domain)
    return queryset.update(status=MemberProfessionalQualification.Status.EXPIRED)


def has_current_professional_qualification(
    member: Member,
    *,
    domain: ProfessionalDomain | None = None,
    domain_code: str = "",
    at_time=None,
) -> bool:
    """判断成员当前是否可将某项专业资格用于授权或投票。"""

    checked_at = at_time or timezone.now()
    if not member_allows_role_facts(member):
        return False
    if not member_has_role(member, ROLE_COVENANTER, checked_at=checked_at):
        return False
    queryset = MemberProfessionalQualification.objects.filter(
        member=member,
        status=MemberProfessionalQualification.Status.ACTIVE,
        domain__status=ProfessionalDomain.Status.ACTIVE,
        valid_from__lte=checked_at,
    ).filter(Q(valid_until__isnull=True) | Q(valid_until__gt=checked_at))
    if domain is not None:
        queryset = queryset.filter(domain=domain)
    elif domain_code:
        queryset = queryset.filter(domain__code=_normalised_domain_code(domain_code))
    else:
        return False
    return queryset.exists()


def members_with_current_professional_qualification(
    *,
    domain: ProfessionalDomain,
    at_time=None,
):
    """返回当前可将指定专业资格用于授权的成员查询集。"""

    checked_at = at_time or timezone.now()
    if domain.status != ProfessionalDomain.Status.ACTIVE:
        return Member.objects.none()
    covenanters = Member.objects.filter(
        member_role_filter(ROLE_COVENANTER, checked_at=checked_at)
    ).values("pk")
    return (
        Member.objects.filter(
            pk__in=covenanters,
            professional_qualifications__domain=domain,
            professional_qualifications__status=MemberProfessionalQualification.Status.ACTIVE,
            professional_qualifications__valid_from__lte=checked_at,
        )
        .filter(
            Q(professional_qualifications__valid_until__isnull=True)
            | Q(professional_qualifications__valid_until__gt=checked_at)
        )
        .distinct()
        .order_by("member_no")
    )


@atomic_for_model(MemberProfessionalQualification)
def revoke_professional_qualification(
    *,
    qualification: MemberProfessionalQualification,
    revoked_by: Member,
    at_time=None,
) -> MemberProfessionalQualification:
    """撤销一项专业资格；记录保留并立即不再参与授权判断。"""

    _require_qualification_administrator(revoked_by, action="撤销")
    qualification.status = MemberProfessionalQualification.Status.REVOKED
    qualification.revoked_by = revoked_by
    qualification.revoked_at = at_time or timezone.now()
    qualification.save(update_fields=["status", "revoked_by", "revoked_at", "updated_at"])
    return qualification
