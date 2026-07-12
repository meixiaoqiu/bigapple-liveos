"""Theme static asset helpers."""

from __future__ import annotations

from django.contrib.staticfiles import finders
from django.http import HttpRequest
from django.templatetags.static import static

from .active import get_active_theme
from .config import DEFAULT_GAME_THEME_KEY, get_theme_config
from .utils import _clean_path

SUPPORTED_ASSET_ROOTS = {"img", "svg", "css", "js", "lottie", "audio"}


def get_theme_static_base(request: HttpRequest) -> str:
    """Return the active theme static URL base."""

    return static(str(get_active_theme(request)["static_dir"]).strip("/") + "/")


def get_theme_asset_url(request: HttpRequest, asset_path: str) -> str:
    """Return an active/default theme asset URL or an empty safe fallback."""

    normalized_path = _clean_path(asset_path)
    if not normalized_path or normalized_path.split("/", 1)[0] not in SUPPORTED_ASSET_ROOTS:
        return ""

    active_config = get_active_theme(request)
    default_config = get_theme_config(DEFAULT_GAME_THEME_KEY)
    candidates = [
        f"{active_config['static_dir']}/{normalized_path}",
        f"{default_config['static_dir']}/{normalized_path}",
    ]
    for candidate in dict.fromkeys(candidates):
        if finders.find(candidate):
            return static(candidate)
    return ""
