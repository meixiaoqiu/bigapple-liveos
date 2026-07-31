"""提案选民政策、快照与当前资格查询。"""

from __future__ import annotations

import math

from django.core.exceptions import ValidationError
from django.utils import timezone

from core.member_roles import ROLE_DELIBERATOR, ROLE_FORMAL_MEMBER, member_role_filter
from core.models import Member, ProfessionalDomain, Proposal
from core.professional_qualification_services import members_with_current_professional_qualification


def calculate_required_approvals(voter_count: int, required_percent: int) -> int:
    if voter_count < 1:
        return 1
    normalized_percent = max(1, min(100, required_percent))
    if normalized_percent == 100:
        return voter_count
    return max(1, math.floor(voter_count * normalized_percent / 100) + 1)


def validate_electorate_policy(
    *,
    electorate_policy: str,
    professional_domain: ProfessionalDomain | None = None,
) -> None:
    """拒绝未分类、过期或不完整的提案选民政策。"""

    if electorate_policy == Proposal.ElectoratePolicy.GENERAL_DELIBERATION:
        if professional_domain is not None:
            raise ValidationError("普通议事提案不能指定专业领域。")
        return
    if electorate_policy == Proposal.ElectoratePolicy.PROFESSIONAL_DELIBERATION:
        if professional_domain is None:
            raise ValidationError("专业议事提案必须指定一个专业领域。")
        if professional_domain.status != ProfessionalDomain.Status.ACTIVE:
            raise ValidationError("专业议事提案只能使用启用中的专业领域。")
        return
    raise ValidationError("提案必须使用已定义的选民政策。")


def eligible_general_deliberators(*, at_time=None):
    """返回同时具备正式成员资格和有效议事者任期的登录成员。"""

    checked_at = at_time or timezone.now()
    formal_members = Member.objects.filter(
        member_role_filter(ROLE_FORMAL_MEMBER, checked_at=checked_at)
    ).values("pk")
    deliberators = Member.objects.filter(
        member_role_filter(ROLE_DELIBERATOR, checked_at=checked_at)
    ).values("pk")
    return Member.objects.filter(pk__in=formal_members).filter(pk__in=deliberators).order_by("member_no")


def eligible_voters_for_electorate_policy(
    *,
    electorate_policy: str,
    professional_domain: ProfessionalDomain | None = None,
    at_time=None,
):
    """根据唯一允许的政策计算选民，不读取角色或组织范围。"""

    validate_electorate_policy(
        electorate_policy=electorate_policy,
        professional_domain=professional_domain,
    )
    checked_at = at_time or timezone.now()
    general_deliberators = eligible_general_deliberators(at_time=checked_at)
    if electorate_policy == Proposal.ElectoratePolicy.GENERAL_DELIBERATION:
        return general_deliberators
    qualified_members = members_with_current_professional_qualification(
        domain=professional_domain,
        at_time=checked_at,
    )
    return general_deliberators.filter(pk__in=qualified_members.values("pk"))


def member_is_currently_eligible_to_vote(
    *,
    member: Member,
    electorate_policy: str,
    professional_domain: ProfessionalDomain | None = None,
    at_time=None,
) -> bool:
    """按提案政策重新检查单个成员当前资格，快照不能替代该检查。"""

    return eligible_voters_for_electorate_policy(
        electorate_policy=electorate_policy,
        professional_domain=professional_domain,
        at_time=at_time,
    ).filter(pk=member.pk).exists()


def eligible_voter_snapshot(
    *,
    electorate_policy: str,
    professional_domain: ProfessionalDomain | None = None,
    at_time=None,
) -> list[int]:
    """在表决开始时保存选民编号快照，用于票数阈值而非授权绕过。"""

    return list(
        eligible_voters_for_electorate_policy(
            electorate_policy=electorate_policy,
            professional_domain=professional_domain,
            at_time=at_time,
        ).values_list("pk", flat=True)
    )
