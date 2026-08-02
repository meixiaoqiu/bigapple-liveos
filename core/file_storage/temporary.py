"""Temporary avatar object operations, isolated from permanent attachments."""

from __future__ import annotations

from django.core.files.base import ContentFile
from django.core.files.storage import storages

from .keys import new_temporary_key, require_deletable_avatar_key


class AvatarTemporaryStorage:
    def __init__(self) -> None:
        self.storage = storages["avatar_temporary"]

    def save(self, *, world_id: str, content: bytes) -> str:
        key = new_temporary_key(world_id)
        return self.storage.save(key, ContentFile(content))

    def delete(self, key: str, *, world_id: str) -> None:
        self.storage.delete(require_deletable_avatar_key(key, world_id=world_id, temporary=True))
