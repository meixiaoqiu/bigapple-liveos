"""Public member profile context for /u/<member_no>/ pages."""

from __future__ import annotations

from typing import Any

from django.db.models import Q
from django.utils import timezone

from core.credential_services import credentials_for_member
from core.event_ledger import PUBLIC_LEDGER_SCHEMA
from core.models import CredentialGrant, Member, MemberPublicProfile, RoleAssignment, SystemEvent


# Chinese label mapping for governance permission codes

_GOVERNANCE_PERMISSION_LABELS: dict[str, str] = {
    "governance.vote": "参与治理投票",
    "governance.propose": "发起治理提案",
    "governance.execute": "执行通过的治理决议",
    "governance.view_admin": "查看治理管理后台",
}

_DEFAULT_GOVERNANCE_LABEL = "其他治理权限"

# SystemEvent -> human-readable title

_EVENT_TITLE_MAP: dict[str, str] = {
    SystemEvent.EventType.PROPOSAL_CREATED: "创建提案",
    SystemEvent.EventType.PROPOSAL_VOTE_CAST: "投票",
    SystemEvent.EventType.PROPOSAL_VOTE_CHANGED: "改票",
    SystemEvent.EventType.PROPOSAL_PASSED: "提案通过",
    SystemEvent.EventType.PROPOSAL_FAILED: "提案未通过",
    SystemEvent.EventType.PROPOSAL_CANCELLED: "取消提案",
    SystemEvent.EventType.PROPOSAL_EXECUTED: "执行提案",
    SystemEvent.EventType.ROLE_ASSIGNED: "角色任命",
    SystemEvent.EventType.ROLE_REVOKED: "角色撤销",
    SystemEvent.EventType.CREDENTIAL_GRANTED: "凭证发放",
    SystemEvent.EventType.MEMBER_CREATED: "成员创建",
    SystemEvent.EventType.MEMBER_APPLICATION_SUBMITTED: "报名提交",
    SystemEvent.EventType.MEMBER_APPLICATION_REVIEWED: "报名审核",
}

# member role -> identity badge

from core.member_roles import (
    ROLE_BIG_APPLE_MEMBER,
    ROLE_FORMAL_MEMBER,
    ROLE_GOVERNANCE_MEMBER,
    member_has_role,
)


def public_identity_badges_for_member(member: Member) -> list[dict[str, str]]:
    """Return visible identity badges for *member* based on active roles."""
    badges: list[dict[str, str]] = []
    if member_has_role(member, ROLE_BIG_APPLE_MEMBER):
        badges.append({"label": "注册参与者", "style": "badge-outline"})
    if member_has_role(member, ROLE_FORMAL_MEMBER):
        badges.append({"label": "正式成员", "style": "badge-primary"})
    if member_has_role(member, ROLE_GOVERNANCE_MEMBER):
        badges.append({"label": "治理成员", "style": "badge-accent"})
    return badges


def public_credentials_for_member(member: Member) -> list[dict[str, Any]]:
    """Return public credentials, stripping internal IDs like grant_id."""
    raw = credentials_for_member(member)
    safe: list[dict[str, Any]] = []
    for item in raw:
        safe.append({
            "template_code": item.get("template_code", ""),
            "template_name": item.get("template_name", ""),
            "credential_type": item.get("credential_type", ""),
            "display_no": item.get("display_no", ""),
            "serial_no": item.get("serial_no"),
            "title": item.get("title", ""),
            "status": item.get("status", ""),
            "issued_at": item.get("issued_at"),
            "source_type": item.get("source_type", ""),
        })
    return safe


def public_roles_for_member(member: Member) -> list[dict[str, Any]]:
    """Return active governance role assignments with Chinese permission labels."""
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
        perm_labels: list[str] = []
        for code, name in gov_perms:
            label = _GOVERNANCE_PERMISSION_LABELS.get(code)
            if label:
                perm_labels.append(label)
            else:
                perm_labels.append(_DEFAULT_GOVERNANCE_LABEL)
        roles.append({
            "organization_name": ra.role.organization.name if ra.role.organization_id else "",
            "role_name": ra.role.name,
            "source_type": ra.get_source_type_display(),
            "start_at": ra.start_at,
            "end_at": ra.end_at,
            "permission_labels": perm_labels,
        })
    return roles


def _identity(member: Member) -> dict[str, Any]:
    """Return public identity fields — no bio, no is_visible."""
    profile = getattr(member, "public_profile", None)
    if profile is not None:
        public_name = profile.public_name or member.display_name or member.member_no
        return {
            "member_no": member.member_no,
            "public_name": public_name,
            "display_name": member.display_name or "",
            "avatar_url": profile.avatar_url or "",
            "initials": public_name[0] if public_name else (member.member_no or "?")[0],
        }
    public_name = member.display_name or member.member_no
    return {
        "member_no": member.member_no,
        "public_name": public_name,
        "display_name": member.display_name or "",
        "avatar_url": "",
        "initials": public_name[0] if public_name else (member.member_no or "?")[0],
    }


def public_governance_activity_for_member(member: Member, *, limit: int = 20) -> list[dict[str, Any]]:
    """Return recent public governance events for *member*.

    Matches both active events (actor_member=member) and passive events
    (CredentialGrant / RoleAssignment granted *to* the member), in a
    single deduplicated timeline.
    """
    from observer.event_context import _short_hash, system_event_chain_check

    # Collect IDs that belong to this member
    credential_grant_ids = list(
        CredentialGrant.objects.filter(member=member).values_list("grant_id", flat=True)
    )
    role_assignment_ids = list(
        RoleAssignment.objects.filter(member=member).values_list("pk", flat=True)
    )

    # Build query: actor actions OR member-tagged passive events
    query = Q(actor_member=member, payload_json__schema=PUBLIC_LEDGER_SCHEMA)

    if credential_grant_ids:
        query |= Q(
            aggregate_type="CredentialGrant",
            aggregate_id__in=credential_grant_ids,
            payload_json__schema=PUBLIC_LEDGER_SCHEMA,
        )
    if role_assignment_ids:
        query |= Q(
            aggregate_type="RoleAssignment",
            aggregate_id__in=[str(ra_id) for ra_id in role_assignment_ids],
            payload_json__schema=PUBLIC_LEDGER_SCHEMA,
        )

    seen: set[int] = set()
    actions: list[dict[str, Any]] = []
    for se in SystemEvent.objects.filter(query).order_by("-seq"):
        if se.seq in seen:
            continue
        seen.add(se.seq)
        if len(actions) >= limit:
            break

        pk = se.payload_json or {}
        chain = system_event_chain_check(se)
        title = _EVENT_TITLE_MAP.get(se.event_type, se.get_event_type_display())
        summary = str(pk.get("summary", "")) or se.get_event_type_display()

        facts = pk.get("public_facts", {}) if isinstance(pk.get("public_facts"), dict) else {}
        vote_choice = str(facts.get("vote_choice_label", ""))
        vote_reason = str(facts.get("reason", ""))

        row: dict[str, Any] = {
            "seq": se.seq,
            "title": title,
            "event_type_display": se.get_event_type_display(),
            "occurred_at": se.occurred_at,
            "summary": summary,
            "event_hash_short": _short_hash(se.event_hash),
            "chain_valid": chain["chain_valid"],
        }
        if vote_choice:
            row["vote_choice"] = vote_choice
        if vote_reason:
            row["vote_reason"] = vote_reason

        # Extra context for credential / role events
        if se.event_type == SystemEvent.EventType.CREDENTIAL_GRANTED:
            template_name = str(facts.get("template_name", ""))
            display_no = str(facts.get("display_no", ""))
            if template_name or display_no:
                row["credential_label"] = f"{template_name} {display_no}".strip()

        if se.event_type in (SystemEvent.EventType.ROLE_ASSIGNED, SystemEvent.EventType.ROLE_REVOKED):
            role_name = str(facts.get("role_name", ""))
            if role_name:
                row["role_name"] = role_name

        actions.append(row)
    return actions


# retained aliases for backward compatibility

public_member_identity = _identity
public_member_governance_roles = public_roles_for_member
public_member_recent_actions = public_governance_activity_for_member


def public_member_profile_context(member_no: str) -> dict[str, Any] | None:
    """Build context for /u/<member_no>/."""
    try:
        member = Member.objects.get(member_no=member_no)
    except Member.DoesNotExist:
        return None
    return {
        "identity": _identity(member),
        "badges": public_identity_badges_for_member(member),
        "credentials": public_credentials_for_member(member),
        "governance_roles": public_roles_for_member(member),
        "recent_actions": public_governance_activity_for_member(member),
    }
