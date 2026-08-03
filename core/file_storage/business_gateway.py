"""Narrow storage gateway for immutable business evidence."""

from django.core.files.base import ContentFile
from django.core.files.storage import storages

from .keys import new_business_attachment_key, require_business_attachment_key


class BusinessAttachmentStorageGateway:
    def __init__(self, *, alias: str = "business_attachments") -> None:
        self.storage = storages[alias]

    def save_immutable(self, *, world_id: str, content: bytes) -> str:
        key = new_business_attachment_key(world_id)
        saved_key = self.storage.save(key, ContentFile(content))
        if saved_key != key:
            self.storage.delete(saved_key)
            raise RuntimeError("Storage backend changed the immutable attachment key.")
        return key

    def open(self, key: str, *, world_id: str):
        return self.storage.open(require_business_attachment_key(key, world_id=world_id), "rb")

    def exists(self, key: str, *, world_id: str) -> bool:
        return self.storage.exists(require_business_attachment_key(key, world_id=world_id))

    def delete_uncommitted(self, key: str, *, world_id: str) -> None:
        self.storage.delete(require_business_attachment_key(key, world_id=world_id))
