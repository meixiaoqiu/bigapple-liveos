"""Member and role creation services for world-scoped operations."""

from __future__ import annotations

from typing import Any

from django.db import IntegrityError
from django.utils import timezone

from core.db import atomic_for_model
from core.event_ledger import append_event
from core.event_payloads import actor_member_from_ref, member_display_name
from core.exceptions import DomainError
from core.member_roles import ROLE_BIG_APPLE_MEMBER, ensure_member_role
from core.models import Member, Organization, Role, RoleAssignment, SystemEvent
from core.role_assignment_services import create_role_assignment


def member_creation_payload(member: Member, *, actor: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "member_id": member.pk,
        "member_no": member.member_no,
        "display_name": member_display_name(member),
        "status": member.status,
        "batch_id": member.batch_id,
        "joined_simulation_day": member.joined_simulation_day,
        "credit_floor": member.credit_floor,
        "created_at": member.created_at.isoformat() if member.created_at else None,
        "actor": actor or {},
    }


def role_creation_payload(role: Role, *, actor: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "role_id": role.pk,
        "role_name": role.name,
        "organization_id": role.organization_id,
        "organization_name": role.organization.name,
        "description": role.description,
        "status": role.status,
        "appointment_electorate_role_id": role.appointment_electorate_role_id,
        "appointment_electorate_role_name": role.appointment_electorate_role.name
        if role.appointment_electorate_role_id
        else "",
        "appointment_required_percent": role.appointment_required_percent,
        "appointment_deadline_days": role.appointment_deadline_days,
        "created_at": role.created_at.isoformat() if role.created_at else None,
        "actor": actor or {},
    }


@atomic_for_model(Member)
def register_member(
    *,
    member_no: str,
    display_name: str = "",
    status: str = Member.Status.ACTIVE,
    batch_id: str = "",
    joined_simulation_day: int | None = None,
    credit_floor: int = -100,
    profile: dict[str, Any] | None = None,
    created_by: dict[str, Any] | None = None,
) -> Member:
    """Create one member and assign the shared baseline role."""

    cleaned_member_no = member_no.strip()
    cleaned_display_name = display_name.strip()
    valid_statuses = {value for value, _label in Member.Status.choices}
    if not cleaned_member_no:
        raise DomainError("成员 ID 不能为空。")
    if status not in valid_statuses:
        raise DomainError("成员状态无效。")
    if Member.objects.filter(member_no=cleaned_member_no).exists():
        raise DomainError("成员 ID 已存在。")

    now = timezone.now()
    profile_payload = dict(profile or {})
    if cleaned_display_name and not profile_payload.get("display_name"):
        profile_payload["display_name"] = cleaned_display_name
    try:
        member = Member.objects.create(
            member_no=cleaned_member_no,
            display_name=cleaned_display_name,
            status=status,
            batch_id=batch_id.strip(),
            joined_simulation_day=joined_simulation_day,
            credit_floor=credit_floor,
            profile=profile_payload,
            created_at=now,
        )
    except IntegrityError as exc:
        raise DomainError("成员创建失败，请检查成员 ID 是否重复。") from exc

    actor_member = actor_member_from_ref(created_by)
    append_event(
        event_type=SystemEvent.EventType.MEMBER_CREATED,
        aggregate_type="Member",
        aggregate_id=str(member.pk),
        actor_member=actor_member,
        payload_json=member_creation_payload(member, actor=created_by),
        occurred_at=now,
    )
    create_role_assignment(
        member=member,
        role=ensure_member_role(ROLE_BIG_APPLE_MEMBER),
        granted_by=actor_member,
        source_type=RoleAssignment.SourceType.SYSTEM,
    )
    return member


@atomic_for_model(Role)
def create_role_template(
    *,
    organization: Organization,
    name: str,
    description: str = "",
    status: str = Role.Status.ACTIVE,
    appointment_electorate_role: Role | None = None,
    appointment_required_percent: int = 50,
    appointment_deadline_days: int = 7,
    created_by: dict[str, Any] | None = None,
) -> Role:
    """Create a reusable role template inside one organization."""

    cleaned_name = name.strip()
    valid_statuses = {value for value, _label in Role.Status.choices}
    if not cleaned_name:
        raise DomainError("角色名称不能为空。")
    if status not in valid_statuses:
        raise DomainError("角色状态无效。")
    if not 1 <= appointment_required_percent <= 100:
        raise DomainError("任命通过比例必须在 1 到 100 之间。")
    if appointment_deadline_days < 1:
        raise DomainError("任命截止天数必须大于 0。")
    if Role.objects.filter(organization=organization, name=cleaned_name).exists():
        raise DomainError("同一组织下已存在同名角色。")

    now = timezone.now()
    try:
        role = Role.objects.create(
            organization=organization,
            name=cleaned_name,
            description=description.strip(),
            status=status,
            appointment_electorate_role=appointment_electorate_role,
            appointment_required_percent=appointment_required_percent,
            appointment_deadline_days=appointment_deadline_days,
        )
    except IntegrityError as exc:
        raise DomainError("角色创建失败，请检查同一组织下是否已有同名角色。") from exc

    append_event(
        event_type=SystemEvent.EventType.ROLE_CREATED,
        aggregate_type="Role",
        aggregate_id=str(role.pk),
        actor_member=actor_member_from_ref(created_by),
        payload_json=role_creation_payload(role, actor=created_by),
        occurred_at=now,
    )
    return role
