"""Validation for untrusted finance evidence while preserving original bytes."""

from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath
import csv

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile

from core.exceptions import DomainError

from .detection import _detector
from .hashing import sha256_hex
from .limits import read_bounded_upload


ALLOWED_LABELS = {
    "pdf": "application/pdf",
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "csv": "text/csv",
}


@dataclass(frozen=True)
class ProcessedBusinessAttachment:
    content: bytes
    media_type: str
    display_filename: str
    sha256: str
    size: int


def _safe_filename(name: str) -> str:
    value = PurePath(str(name or "attachment").replace("\\", "/")).name.strip()
    return (value or "attachment")[:255]


def _validate_image(data: bytes) -> None:
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
            if width > settings.ATTACHMENT_MAX_EDGE_PIXELS or height > settings.ATTACHMENT_MAX_EDGE_PIXELS:
                raise DomainError("凭证图片边长超过限制。")
            if width * height > settings.ATTACHMENT_MAX_TOTAL_PIXELS:
                raise DomainError("凭证图片像素总量超过限制。")
            image.load()
    except DomainError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise DomainError("凭证图片已损坏或无法安全解码。") from exc


def process_business_attachment(upload: UploadedFile) -> ProcessedBusinessAttachment:
    """Validate one supported evidence file and preserve its original bytes."""
    data = read_bounded_upload(upload, max_bytes=settings.ATTACHMENT_MAX_UPLOAD_BYTES, subject="凭证文件")
    try:
        label = str(_detector().identify_bytes(data).output.label).lower()
    except Exception as exc:
        raise DomainError("无法可靠识别凭证文件类型。") from exc
    if label not in ALLOWED_LABELS:
        raise DomainError("凭证只支持 PDF、JPEG、PNG、WebP 或 CSV。")
    media_type = ALLOWED_LABELS[label]
    if media_type.startswith("image/"):
        _validate_image(data)
    elif media_type == "application/pdf":
        if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-2048:]:
            raise DomainError("PDF 凭证已损坏或结构不完整。")
    else:
        try:
            text = data.decode("utf-8-sig")
            if "\x00" in text:
                raise ValueError
            list(csv.reader(text.splitlines()[:100]))
        except (UnicodeDecodeError, csv.Error, ValueError) as exc:
            raise DomainError("CSV 凭证必须是有效的 UTF-8 文本。") from exc
    return ProcessedBusinessAttachment(data, media_type, _safe_filename(upload.name), sha256_hex(data), len(data))
