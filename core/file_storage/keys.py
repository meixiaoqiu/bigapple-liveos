"""Opaque, lifecycle-separated object key generation and validation."""

from __future__ import annotations

import re
from uuid import uuid4

from core.exceptions import DomainError


WORLD_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")


def require_safe_world_id(world_id: str) -> str:
    value = str(world_id or "")
    if not WORLD_ID_PATTERN.fullmatch(value):
        raise DomainError("无效的 world 标识。")
    return value


def avatar_prefix(world_id: str) -> str:
    return f"worlds/{require_safe_world_id(world_id)}/current-assets/avatars/"


def avatar_temporary_prefix(world_id: str) -> str:
    return f"worlds/{require_safe_world_id(world_id)}/temporary/avatar-uploads/"


def new_avatar_key(world_id: str) -> str:
    return f"{avatar_prefix(world_id)}{uuid4().hex}.webp"


def new_temporary_key(world_id: str) -> str:
    return f"{avatar_temporary_prefix(world_id)}{uuid4().hex}"


def require_deletable_avatar_key(key: str, *, world_id: str, temporary: bool = False) -> str:
    expected = avatar_temporary_prefix(world_id) if temporary else avatar_prefix(world_id)
    value = str(key or "")
    if not value.startswith(expected) or ".." in value or "\\" in value:
        raise DomainError("拒绝删除不属于当前 world 头像生命周期的对象。")
    suffix = value.removeprefix(expected)
    if not suffix or "/" in suffix:
        raise DomainError("无效的头像对象 key。")
    return value
