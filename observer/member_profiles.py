"""Public member profile context for /u/<member_no>/ pages."""

from __future__ import annotations

from typing import Any

from django.db.models import Q
from core.credential_services import credentials_for_member
from core.event_ledger import PUBLIC_LEDGER_SCHEMA
from core.identity_display import member_identity_display
from core.models import CredentialGrant, Member, MemberPublicProfile, RoleAssignment, SystemEvent

# SystemEvent -> human-readable title

_EVENT_TITLE_MAP: dict[str, str] = {
    SystemEvent.EventType.ROLE_ASSIGNED: "角色任命",
    SystemEvent.EventType.ROLE_REVOKED: "角色撤销",
    SystemEvent.EventType.CREDENTIAL_GRANTED: "凭证发放",
    SystemEvent.EventType.MEMBER_CREATED: "成员创建",
    SystemEvent.EventType.MEMBER_APPLICATION_SUBMITTED: "报名提交",
    SystemEvent.EventType.MEMBER_APPLICATION_REVIEWED: "报名审核",
}

def public_identity_badges_for_member(member: Member) -> list[dict[str, str]]:
    """按统一展示投影返回身份徽章，不以层级遮蔽并存职责。"""

    identity_display = member_identity_display(member)
    badges: list[dict[str, str]] = []
    derived_status = identity_display["derived_status"]
    if derived_status:
        badges.append({"label": derived_status["name"], "style": "badge-ghost"})
    membership = identity_display["membership"]
    if membership:
        badges.append({"label": membership["name"], "style": "badge-primary"})
    for duty in identity_display["duties"]:
        style = "badge-accent" if duty["code"] == "deliberator" else "badge-secondary"
        badges.append({"label": duty["name"], "style": style})
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
    """返回当前成员资格和职责；保留此函数作为公开资料的读取入口。"""

    identity_display = member_identity_display(member)
    roles: list[dict[str, Any]] = []
    membership = identity_display["membership"]
    if membership:
        roles.append({"kind": "成员资格", **membership})
    roles.extend({"kind": "职责", **duty} for duty in identity_display["duties"])
    return roles


def _identity(member: Member) -> dict[str, Any]:
    """Return public identity fields — no bio, no is_visible."""
    profile = getattr(member, "public_profile", None)
    if profile is not None:
        public_name = profile.public_name or member.display_name or member.member_no
        avatar_version = (
            str(int(profile.avatar_updated_at.timestamp() * 1_000_000))
            if profile.avatar_updated_at
            else "default"
        )
        return {
            "member_no": member.member_no,
            "public_name": public_name,
            "display_name": member.display_name or "",
            "avatar_url": (
                f"/u/{member.member_no}/avatar/?v={avatar_version}"
                if profile.avatar_key
                else ""
            ),
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


public_member_identity = _identity
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
        "identity_display": member_identity_display(member),
        "recent_actions": public_governance_activity_for_member(member),
    }
