"""Safe avatar decoding and canonical WebP encoding."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import warnings

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile

from core.exceptions import DomainError

from .detection import identify_allowed_image
from .hashing import sha256_hex
from .limits import read_bounded_upload


@dataclass(frozen=True)
class ProcessedAvatar:
    content: bytes
    content_type: str
    sha256: str
    size: int


def _center_crop(image, edge: int):
    from PIL import Image

    width, height = image.size
    crop_edge = min(width, height)
    left = (width - crop_edge) // 2
    top = (height - crop_edge) // 2
    return image.crop((left, top, left + crop_edge, top + crop_edge)).resize(
        (edge, edge),
        resample=Image.Resampling.LANCZOS,
    )


def process_avatar(upload: UploadedFile) -> ProcessedAvatar:
    """Validate an uploaded image and return canonical, metadata-free WebP bytes."""

    from PIL import Image, ImageOps, UnidentifiedImageError

    data = read_bounded_upload(upload, max_bytes=settings.AVATAR_MAX_UPLOAD_BYTES)
    identify_allowed_image(data)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                width, height = source.size
                if width > settings.AVATAR_MAX_EDGE_PIXELS or height > settings.AVATAR_MAX_EDGE_PIXELS:
                    raise DomainError("头像图片边长超过限制。")
                if width * height > settings.AVATAR_MAX_TOTAL_PIXELS:
                    raise DomainError("头像图片像素总量超过限制。")
                # Pillow reads image dimensions while opening the header. Enforce
                # project limits before load(), EXIF transpose, or conversion can
                # allocate a full decompressed pixel buffer.
                source.load()
                normalized = ImageOps.exif_transpose(source)
                if getattr(normalized, "is_animated", False):
                    normalized.seek(0)
                mode = "RGBA" if "A" in normalized.getbands() else "RGB"
                normalized = normalized.convert(mode)
                output_image = _center_crop(normalized, settings.AVATAR_OUTPUT_PIXELS)
                buffer = BytesIO()
                output_image.save(
                    buffer,
                    format="WEBP",
                    quality=settings.AVATAR_WEBP_QUALITY,
                    method=6,
                    exif=b"",
                    icc_profile=None,
                )
    except DomainError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise DomainError("头像图片已损坏或无法安全解码。") from exc
    content = buffer.getvalue()
    return ProcessedAvatar(
        content=content,
        content_type="image/webp",
        sha256=sha256_hex(content),
        size=len(content),
    )
