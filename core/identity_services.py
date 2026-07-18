"""Member and role creation services for world-scoped operations."""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.utils import timezone

from core.db import atomic_for_model
from core.event_ledger import PUBLIC_LEDGER_SCHEMA, append_event
from core.event_payloads import _member_label, _public_member_label, _private, _public_ref
from core.exceptions import DomainError
from core.member_roles import ROLE_BIG_APPLE_MEMBER, ensure_member_role, ensure_role_assignment
from core.models import Member, Organization, Role, RoleAssignment, SystemEvent
from core.role_assignment_services import create_role_assignment


def member_creation_payload(member: Member, *, actor_ref: dict[str, Any] | None = None) -> dict[str, Any]:
    public_label = _public_member_label(member.display_name, member.member_no)
    return {
        "schema": PUBLIC_LEDGER_SCHEMA,
        "subject": {
            "type": "member",
            "ref": _public_ref("member", public_label),
            "label": public_label,
        },
        "action": "created",
        "stage": member.status,
        "summary": f"新成员 {public_label} 已创建。",
        "public_facts": {
            "status": member.status,
            "batch_id": member.batch_id,
            "joined_simulation_day": member.joined_simulation_day,
        },
        "private_commitments": [
            _private("member_id", reason="成员内部ID"),
            _private("member_no", reason="成员编号属于隐私"),
            _private("display_name_raw", reason="真实姓名属于隐私"),
            _private("credit_floor", reason="信用额度属于隐私"),
            _private("actor", present=bool(actor_ref), reason="操作人属于隐私"),
        ],
    }


def role_creation_payload(role: Role, *, actor_ref: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema": PUBLIC_LEDGER_SCHEMA,
        "subject": {
            "type": "role",
            "ref": _public_ref("role", role.organization.name, role.name),
            "label": role.name,
        },
        "action": "created",
        "stage": role.status,
        "summary": f"角色「{role.name}」（{role.organization.name}）已创建。",
        "public_facts": {
            "role_name": role.name,
            "organization_name": role.organization.name,
            "status": role.status,
        },
        "private_commitments": [
            _private("role_id", reason="角色内部ID"),
            _private("organization_id", reason="组织内部ID"),
            _private("description", reason="角色描述"),
            _private("appointment_electorate_role_id", reason="任命选民角色内部ID"),
            _private("appointment_required_percent", reason="任命阈值比例"),
            _private("appointment_deadline_days", reason="任命截止天数"),
            _private("actor", present=bool(actor_ref), reason="操作人属于隐私"),
        ],
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

    from core.event_payloads import actor_member_from_ref

    actor_member = actor_member_from_ref(created_by)
    append_event(
        event_type=SystemEvent.EventType.MEMBER_CREATED,
        aggregate_type="Member",
        aggregate_id=member.member_no,
        actor_member=actor_member,
        payload_json=member_creation_payload(member, actor_ref=created_by),
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

    from core.event_payloads import actor_member_from_ref

    append_event(
        event_type=SystemEvent.EventType.ROLE_CREATED,
        aggregate_type="Role",
        aggregate_id=str(role.pk),
        actor_member=actor_member_from_ref(created_by),
        payload_json=role_creation_payload(role, actor_ref=created_by),
        occurred_at=now,
    )
    return role


@atomic_for_model(Member)
def ensure_basic_member_for_user(user) -> Member:
    """Ensure an authenticated User has the baseline Member identity.

    This creates only User-bound Member + ROLE_BIG_APPLE_MEMBER. It does
    **not** create MemberApplication, Proposal, or public observer Event.

    Returns the existing Member if *user* is already bound to one.
    """
    username = str(user.get_username() or "").strip()
    if not username:
        raise DomainError("登录账号不能为空。")
    member = Member.objects.filter(user=user).first()
    if member is not None:
        return member
    existing = Member.objects.filter(member_no=username).first()
    if existing is not None:
        if existing.user_id and existing.user_id != user.pk:
            raise DomainError("该账号已被其他成员绑定。")
        existing.user = user
        if not existing.display_name:
            existing.display_name = username
        existing.save(update_fields=["user", "display_name"])
        ensure_role_assignment(existing, ensure_member_role(ROLE_BIG_APPLE_MEMBER))
        return existing
    member = Member.objects.create(
        member_no=username,
        display_name=username,
        status=Member.Status.PENDING_REVIEW,
        credit_floor=-100,
        created_at=timezone.now(),
    )
    member.user = user
    member.save(update_fields=["user"])
    ensure_role_assignment(member, ensure_member_role(ROLE_BIG_APPLE_MEMBER))
    return member


@atomic_for_model(Member)
def register_participant_account(
    *,
    username: str,
    password: str,
    display_name: str,
    contact: str,
):
    """Register a participant account and baseline Member identity.

    This is **account registration only**. It must not create
    MemberApplication, Proposal, or public observer Event.

    Returns ``(user, member)``.
    """
    cleaned_username = str(username or "").strip()
    cleaned_display_name = str(display_name or "").strip()
    cleaned_contact = str(contact or "").strip()
    if not cleaned_username:
        raise DomainError("登录账号不能为空。")
    if not password:
        raise DomainError("登录密码不能为空。")
    if not cleaned_display_name:
        raise DomainError("姓名或称呼不能为空。")
    if not cleaned_contact:
        raise DomainError("联系方式不能为空。")
    user_model = get_user_model()
    if user_model.objects.filter(username=cleaned_username).exists():
        raise DomainError("登录账号已存在。")
    if Member.objects.filter(member_no=cleaned_username).exists():
        raise DomainError("该账号已被成员编号使用。")

    user = user_model.objects.create_user(username=cleaned_username, password=password)
    member = Member.objects.create(
        member_no=cleaned_username,
        display_name=cleaned_display_name,
        status=Member.Status.PENDING_REVIEW,
        credit_floor=-100,
        created_at=timezone.now(),
        metadata={
            "registration_contact": cleaned_contact,
            "registration_source": "public_register_form",
        },
    )
    member.user = user
    member.save(update_fields=["user"])
    ensure_role_assignment(member, ensure_member_role(ROLE_BIG_APPLE_MEMBER))
    return user, member
