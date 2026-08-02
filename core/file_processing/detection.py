"""Content-based type detection for untrusted files."""

from __future__ import annotations

from functools import lru_cache

from core.exceptions import DomainError


ALLOWED_MAGIKA_LABELS = {
    "jpeg", "jpg", "png", "webp", "gif", "bmp", "tiff",
}


@lru_cache(maxsize=1)
def _detector():
    try:
        from magika import Magika, PredictionMode
    except ImportError as exc:
        raise DomainError("服务器尚未安装头像内容识别组件。") from exc
    try:
        return Magika(prediction_mode=PredictionMode.HIGH_CONFIDENCE)
    except TypeError:
        return Magika()


def identify_allowed_image(data: bytes) -> str:
    """Return a trusted Magika label or reject the upload."""

    try:
        result = _detector().identify_bytes(data)
        label = str(result.output.label).lower()
    except DomainError:
        raise
    except Exception as exc:
        raise DomainError("无法可靠识别头像文件类型。") from exc
    if label not in ALLOWED_MAGIKA_LABELS:
        raise DomainError("请选择 JPEG、PNG、WebP、GIF、BMP 或 TIFF 图片。")
    return label
