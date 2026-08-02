"""Narrow Django Storage gateway for replaceable avatar assets."""

from __future__ import annotations

from io import BytesIO

from django.core.files.base import ContentFile
from django.core.files.storage import storages

from .keys import new_avatar_key, require_deletable_avatar_key


class AvatarStorageGateway:
    def __init__(self, *, alias: str = "avatars") -> None:
        self.storage = storages[alias]

    def save_processed(self, *, world_id: str, content: bytes) -> str:
        key = new_avatar_key(world_id)
        saved_key = self.storage.save(key, ContentFile(content))
        if saved_key != key:
            self.storage.delete(saved_key)
            raise RuntimeError("Storage backend changed the non-colliding avatar key.")
        return key

    def open_current(self, key: str):
        return self.storage.open(key, "rb")

    def exists(self, key: str) -> bool:
        return self.storage.exists(key)

    def size(self, key: str) -> int:
        return self.storage.size(key)

    def delete_current(self, key: str, *, world_id: str) -> None:
        self.storage.delete(require_deletable_avatar_key(key, world_id=world_id))

    def list_prefix(self, prefix: str) -> list[str]:
        directories, files = self.storage.listdir(prefix.rstrip("/"))
        result = [f"{prefix.rstrip('/')}/{name}" for name in files]
        for directory in directories:
            result.extend(self.list_prefix(f"{prefix.rstrip('/')}/{directory}/"))
        return result
