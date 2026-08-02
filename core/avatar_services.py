"""Authoritative state transitions for replaceable member avatars."""

from __future__ import annotations

import logging
from uuid import uuid4

from django.core.files.uploadedfile import UploadedFile
from django.db import router, transaction
from django.utils import timezone

from core.exceptions import DomainError
from core.file_processing import process_avatar
from core.file_storage import AvatarStorageGateway
from core.models import Event, Member, MemberPublicProfile
from core.permission_services import member_has_permission


logger = logging.getLogger(__name__)


def _database_alias(member: Member) -> str:
    return member._state.db or router.db_for_write(MemberPublicProfile, instance=member) or "default"


def replace_own_avatar(
    *,
    member: Member,
    world_id: str,
    upload: UploadedFile,
    gateway: AvatarStorageGateway | None = None,
) -> MemberPublicProfile:
    """Replace a member's own current avatar without accepting a target member id."""

    storage = gateway or AvatarStorageGateway()
    processed = process_avatar(upload)
    try:
        new_key = storage.save_processed(world_id=world_id, content=processed.content)
    except Exception as exc:
        raise DomainError("头像存储失败，请稍后重试。") from exc

    database_alias = _database_alias(member)
    old_key = ""
    try:
        with transaction.atomic(using=database_alias):
            profile, _created = MemberPublicProfile.objects.using(database_alias).select_for_update().get_or_create(
                member_id=member.pk,
                defaults={"is_visible": True},
            )
            old_key = profile.avatar_key
            profile.avatar_key = new_key
            profile.avatar_sha256 = processed.sha256
            profile.avatar_size = processed.size
            profile.avatar_updated_at = timezone.now()
            profile.full_clean()
            profile.save(
                using=database_alias,
                update_fields=["avatar_key", "avatar_sha256", "avatar_size", "avatar_updated_at", "updated_at"],
            )
            if old_key and old_key != new_key:
                transaction.on_commit(
                    lambda: _delete_after_commit(storage, old_key, world_id),
                    using=database_alias,
                )
    except Exception:
        try:
            storage.delete_current(new_key, world_id=world_id)
        except Exception:
            logger.exception("avatar_compensation_delete_failed world=%s key=%s", world_id, new_key)
        raise
    return profile


def _delete_after_commit(storage: AvatarStorageGateway, key: str, world_id: str) -> None:
    try:
        storage.delete_current(key, world_id=world_id)
    except Exception:
        logger.exception("avatar_old_object_delete_failed world=%s key=%s", world_id, key)


def remove_own_avatar(
    *, member: Member, world_id: str, gateway: AvatarStorageGateway | None = None
) -> MemberPublicProfile:
    """Restore the member's default avatar and clean the old current object after commit."""

    return _remove_avatar(member=member, world_id=world_id, gateway=gateway)


def remove_avatar_as_maintainer(
    *, actor: Member, target: Member, world_id: str, gateway: AvatarStorageGateway | None = None
) -> MemberPublicProfile:
    """Remove a policy-violating avatar when the actor has people-maintenance permission."""

    if not member_has_permission(actor, "governance.manage_people"):
        raise DomainError("你没有移除其他成员头像的权限。")
    database_alias = _database_alias(target)
    with transaction.atomic(using=database_alias):
        profile = _remove_avatar(member=target, world_id=world_id, gateway=gateway)
        Event.objects.using(database_alias).create(
            event_id=f"evt-avatar-{uuid4().hex}",
            event_type=Event.EventType.GOVERNANCE,
            simulation_day=0,
            severity=Event.Severity.INFO,
            title="违规头像已移除",
            summary=f"维护人员 {actor.member_no} 已移除成员 {target.member_no} 的当前头像。",
            involved_member_ids=[actor.member_no, target.member_no],
            occurred_at=timezone.now(),
            generated_by=Event.GeneratedBy.HUMAN_OPERATOR,
            visibility=Event.Visibility.INTERNAL,
            payload={
                "action": "member_avatar_removed",
                "actor_member_no": actor.member_no,
                "target_member_no": target.member_no,
            },
        )
    logger.warning(
        "avatar_removed_by_maintainer actor=%s target=%s occurred_at=%s",
        actor.member_no,
        target.member_no,
        timezone.now().isoformat(),
    )
    return profile


def _remove_avatar(
    *, member: Member, world_id: str, gateway: AvatarStorageGateway | None
) -> MemberPublicProfile:
    storage = gateway or AvatarStorageGateway()
    database_alias = _database_alias(member)
    with transaction.atomic(using=database_alias):
        profile, _created = MemberPublicProfile.objects.using(database_alias).select_for_update().get_or_create(
            member_id=member.pk,
            defaults={"is_visible": True},
        )
        old_key = profile.avatar_key
        if not old_key:
            return profile
        profile.avatar_key = ""
        profile.avatar_sha256 = ""
        profile.avatar_size = None
        profile.avatar_updated_at = timezone.now()
        profile.full_clean()
        profile.save(
            using=database_alias,
            update_fields=["avatar_key", "avatar_sha256", "avatar_size", "avatar_updated_at", "updated_at"],
        )
        transaction.on_commit(
            lambda: _delete_after_commit(storage, old_key, world_id),
            using=database_alias,
        )
    return profile
