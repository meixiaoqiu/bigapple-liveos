"""Proposal voter eligibility and approval threshold helpers."""

from __future__ import annotations

import math

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from core.models import Member, Organization, Proposal, Role, RoleAssignment
from core.permission_services import MEMBER_PERMISSION_STATUSES


def calculate_required_approvals(voter_count: int, required_percent: int) -> int:
    if voter_count < 1:
        return 1
    normalized_percent = max(1, min(100, required_percent))
    if normalized_percent == 100:
        return voter_count
    return max(1, math.floor(voter_count * normalized_percent / 100) + 1)


def eligible_voters_for_role(electorate_role: Role, *, at_time=None):
    checked_at = at_time or timezone.now()
    return (
        Member.objects.filter(
            _login_capable_member_filter(),
            role_assignments__role=electorate_role,
            role_assignments__status=RoleAssignment.Status.ACTIVE,
            role_assignments__role__status=Role.Status.ACTIVE,
            role_assignments__start_at__lte=checked_at,
            role_assignments__end_at__gte=checked_at,
            status__in=MEMBER_PERMISSION_STATUSES,
        )
        .distinct()
        .order_by("member_no")
    )


def eligible_voters_for_proposal_scope(
    *,
    voter_scope_type: str,
    voter_scope_role: Role | None = None,
    voter_scope_organization: Organization | None = None,
    at_time=None,
):
    checked_at = at_time or timezone.now()
    if voter_scope_type == Proposal.VoterScopeType.ROLE and voter_scope_role is not None:
        return eligible_voters_for_role(voter_scope_role, at_time=checked_at)
    if voter_scope_type == Proposal.VoterScopeType.ORGANIZATION and voter_scope_organization is not None:
        return (
            Member.objects.filter(
                _login_capable_member_filter(),
                role_assignments__role__organization=voter_scope_organization,
                role_assignments__status=RoleAssignment.Status.ACTIVE,
                role_assignments__role__status=Role.Status.ACTIVE,
                role_assignments__start_at__lte=checked_at,
                role_assignments__end_at__gte=checked_at,
                status__in=MEMBER_PERMISSION_STATUSES,
            )
            .distinct()
            .order_by("member_no")
        )
    if voter_scope_type == Proposal.VoterScopeType.ALL_MEMBERS:
        return Member.objects.filter(
            _login_capable_member_filter(),
            status__in=MEMBER_PERMISSION_STATUSES,
        ).order_by("member_no")
    return Member.objects.none()


def eligible_voter_snapshot(
    *,
    voter_scope_type: str,
    voter_scope_role: Role | None = None,
    voter_scope_organization: Organization | None = None,
    at_time=None,
) -> list[int]:
    return list(
        eligible_voters_for_proposal_scope(
            voter_scope_type=voter_scope_type,
            voter_scope_role=voter_scope_role,
            voter_scope_organization=voter_scope_organization,
            at_time=at_time,
        ).values_list("pk", flat=True)
    )


def _login_capable_member_filter() -> Q:
    """Return members that can actually log in to cast a workspace vote."""

    user_model = get_user_model()
    active_usernames = user_model._default_manager.filter(is_active=True).values("username")
    return Q(user__is_active=True) | Q(member_no__in=active_usernames)
