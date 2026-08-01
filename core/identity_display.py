"""成员身份的只读展示投影，不参与任何业务授权。"""

from __future__ import annotations

from django.db.models import Q
from django.utils import timezone

from .member_roles import (
    ROLE_DELIBERATOR,
    ROLE_COVENANTER,
    ROLE_MAINTAINER,
    member_allows_role_facts,
    member_has_role,
    participation_status,
)
from .models import Member, MemberProfessionalQualification, RoleAssignment
from .role_catalog import ROLE_CATALOG_ORGANIZATION_KEY, role_definition_for_name


def _current_role_display(member: Member, role_name: str, *, at_time) -> dict[str, object] | None:
    """返回一项当前有效直接角色的展示资料，并统一处理前置资格。"""

    definition = role_definition_for_name(role_name)
    if definition is None or not member_has_role(member, role_name, checked_at=at_time):
        return None
    assignment = (
        RoleAssignment.objects.filter(
            member=member,
            role__organization__role_catalog_key=ROLE_CATALOG_ORGANIZATION_KEY,
            role__name=role_name,
            status=RoleAssignment.Status.ACTIVE,
            start_at__lte=at_time,
            end_at__gt=at_time,
        )
        .order_by("-start_at", "-pk")
        .first()
    )
    if assignment is None:
        return None
    return {
        "code": definition.code,
        "name": definition.display_name,
        "dimension": definition.dimension.value,
        "source_type": assignment.get_source_type_display(),
        "start_at": assignment.start_at,
        "end_at": assignment.end_at,
    }


def member_identity_display(member: Member, *, at_time=None) -> dict[str, object]:
    """构造成员资格、职责、专业资格与限制原因的展示投影。

    本函数只描述当前可见事实。调用方不得使用返回值进行授权，授权必须继续
    经过 ``AuthorizationService``。
    """

    checked_at = at_time or timezone.now()
    if not member_allows_role_facts(member):
        return {
            "derived_status": None,
            "membership": None,
            "duties": [],
            "professional_qualifications": [],
            "restriction_reason": "成员状态或登录账号当前不可用。",
        }

    membership = _current_role_display(member, ROLE_COVENANTER, at_time=checked_at)
    duties = [
        item
        for item in (
            _current_role_display(member, ROLE_DELIBERATOR, at_time=checked_at),
            _current_role_display(member, ROLE_MAINTAINER, at_time=checked_at),
        )
        if item is not None
    ]
    qualifications: list[dict[str, object]] = []
    if membership is not None:
        queryset = (
            MemberProfessionalQualification.objects.select_related("domain")
            .filter(
                member=member,
                status=MemberProfessionalQualification.Status.ACTIVE,
                domain__status="active",
                valid_from__lte=checked_at,
            )
            .filter(Q(valid_until__isnull=True) | Q(valid_until__gt=checked_at))
            .order_by("domain__code")
        )
        qualifications = [
            {
                "code": qualification.domain.code,
                "name": qualification.domain.name,
                "valid_from": qualification.valid_from,
                "valid_until": qualification.valid_until,
            }
            for qualification in queryset
        ]

    derived_status = participation_status(member, checked_at=checked_at)
    restriction_reason = ""
    if membership is None:
        restriction_reason = "尚未取得当前有效的守约者资格。"
    elif not duties:
        restriction_reason = "当前未承担议事或维护职责。"
    return {
        "derived_status": (
            {"code": "contributor", "name": "贡献者"} if derived_status == "contributor" else None
        ),
        "membership": membership,
        "duties": duties,
        "professional_qualifications": qualifications,
        "restriction_reason": restriction_reason,
    }
