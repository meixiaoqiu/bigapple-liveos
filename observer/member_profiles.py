"""Public member profile context for Observer member pages."""

from __future__ import annotations

from typing import Any

from django.utils import timezone

from core.credential_services import credentials_for_member
from core.event_ledger import PUBLIC_LEDGER_SCHEMA
from core.models import Member, MemberPublicProfile, SystemEvent


def public_member_identity(member: Member) -> dict[str, Any]:
    """Return public identity fields for a member."""
    profile = getattr(member, "public_profile", None)
    if profile and profile.is_visible:
        public_name = profile.public_name or member.display_name or member.member_no
        return {
            "member_no": member.member_no,
            "public_name": public_name,
            "display_name": member.display_name or "",
            "avatar_url": profile.avatar_url or "",
            "bio": profile.bio or "",
            "is_profile_visible": True,
            "initials": public_name[0] if public_name else (member.member_no or "?")[0],
        }
    public_name = member.display_name or member.member_no
    return {
        "member_no": member.member_no,
        "public_name": public_name,
        "display_name": member.display_name or "",
        "avatar_url": "",
        "bio": "",
        "is_profile_visible": False,
        "initials": public_name[0] if public_name else (member.member_no or "?")[0],
    }


def public_member_governance_roles(member: Member) -> list[dict[str, Any]]:
    """Return active governance role assignments with derived permissions."""
    now = timezone.now()
    roles: list[dict[str, Any]] = []
    for ra in member.role_assignments.filter(
        status="active",
        role__status="active",
        start_at__lte=now,
        end_at__gte=now,
    ).select_related("role", "role__organization"):
        gov_perms = list(
            ra.role.role_permissions.filter(permission__code__startswith="governance.")
            .select_related("permission")
            .values_list("permission__code", "permission__name")
        )
        roles.append({
            "organization_name": ra.role.organization.name if ra.role.organization_id else "",
            "role_name": ra.role.name,
            "source_type": ra.get_source_type_display(),
            "start_at": ra.start_at,
            "end_at": ra.end_at,
            "governance_permissions": [{"code": code, "name": name} for code, name in gov_perms],
        })
    return roles


def public_member_recent_actions(member: Member) -> list[dict[str, Any]]:
    """Return recent public SystemEvents for this member."""
    from observer.event_context import _short_hash, system_event_chain_check

    actions: list[dict[str, Any]] = []
    for se in SystemEvent.objects.filter(
        actor_member=member,
        payload_json__schema=PUBLIC_LEDGER_SCHEMA,
    ).order_by("-seq")[:20]:
        pk = se.payload_json or {}
        chain = system_event_chain_check(se)
        actions.append({
            "seq": se.seq,
            "event_type_display": se.get_event_type_display(),
            "occurred_at": se.occurred_at,
            "summary": str(pk.get("summary", "")) or se.get_event_type_display(),
            "event_hash_short": _short_hash(se.event_hash),
            "chain_valid": chain["chain_valid"],
        })
    return actions


def public_member_profile_context(member_no: str) -> dict[str, Any] | None:
    """Build context for /observer/members/<member_no>/."""
    try:
        member = Member.objects.get(member_no=member_no)
    except Member.DoesNotExist:
        return None
    return {
        "identity": public_member_identity(member),
        "governance_roles": public_member_governance_roles(member),
        "recent_actions": public_member_recent_actions(member),
        "credentials": credentials_for_member(member),
    }
