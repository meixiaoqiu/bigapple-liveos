"""Bounded ingestion for untrusted uploaded files."""

from __future__ import annotations

from django.core.files.uploadedfile import UploadedFile

from core.exceptions import DomainError


def read_bounded_upload(upload: UploadedFile, *, max_bytes: int, subject: str = "头像文件") -> bytes:
    """Read an upload without allowing its bytes to exceed ``max_bytes``."""

    data = bytearray()
    try:
        for chunk in upload.chunks():
            if not isinstance(chunk, bytes):
                chunk = bytes(chunk)
            data.extend(chunk)
            if len(data) > max_bytes:
                raise DomainError(f"{subject}不能超过 {max_bytes // (1024 * 1024)} MiB。")
    except DomainError:
        raise
    except Exception as exc:
        raise DomainError(f"{subject}读取失败，请重新选择文件。") from exc
    if not data:
        raise DomainError(f"{subject}不能为空。")
    return bytes(data)
