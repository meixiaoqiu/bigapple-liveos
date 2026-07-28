"""Proposal voter eligibility and approval threshold helpers."""

from __future__ import annotations

import math

from django.utils import timezone

from core.authorization_services import AuthorizationService, authorization_backend, login_capable_member_filter
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
    if authorization_backend() == "openfga":
        return AuthorizationService().eligible_voters_for_role(electorate_role, at_time=at_time)

    checked_at = at_time or timezone.now()
    return (
        Member.objects.filter(
            login_capable_member_filter(),
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
        if authorization_backend() == "openfga":
            role_ids = Role.objects.filter(
                organization=voter_scope_organization,
                status=Role.Status.ACTIVE,
            ).values_list("pk", flat=True)
            return AuthorizationService().eligible_voters_for_organization(role_ids, at_time=checked_at)
        return (
            Member.objects.filter(
                login_capable_member_filter(),
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
        if authorization_backend() == "openfga":
            return AuthorizationService().eligible_formal_members()
        return Member.objects.filter(
            login_capable_member_filter(),
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
