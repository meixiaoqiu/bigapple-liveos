"""Active theme session helpers."""

from __future__ import annotations

from django.http import HttpRequest

from .config import DEFAULT_GAME_THEME_KEY, THEME_SESSION_KEY, get_default_theme_name, get_theme_config, get_theme_configs

REQUEST_THEME_OVERRIDE_ATTR = "_active_theme_override"


def get_active_theme(request: HttpRequest) -> dict[str, object]:
    """Read active theme from session, then ACTIVE_THEME, with fallback."""

    request_theme = getattr(request, REQUEST_THEME_OVERRIDE_ATTR, None)
    if request_theme:
        return _active_or_default(str(request_theme))

    session_theme = None
    if hasattr(request, "session"):
        session_theme = request.session.get(THEME_SESSION_KEY)
    if session_theme:
        return _active_or_default(str(session_theme))
    return _active_or_default(get_default_theme_name())


def get_active_theme_name(request: HttpRequest) -> str:
    """Compatibility helper returning the active theme key."""

    return str(get_active_theme(request)["key"])


def get_active_theme_config(request: HttpRequest) -> dict[str, object]:
    """Compatibility helper returning the active theme config."""

    return get_active_theme(request)


def set_active_theme(request: HttpRequest, theme_name: str) -> bool:
    """Persist a valid theme key into session."""

    requested_key = str(theme_name or "").strip()
    configs = get_theme_configs()
    if requested_key not in configs:
        return False

    config = get_theme_config(requested_key)
    if not config.get("is_active"):
        return False
    request.session[THEME_SESSION_KEY] = config["key"]
    return True


def set_request_theme_override(request: HttpRequest, theme_name: str) -> bool:
    """Use a valid theme for the current request without mutating session state."""

    requested_key = str(theme_name or "").strip()
    configs = get_theme_configs()
    if requested_key not in configs:
        return False

    config = get_theme_config(requested_key)
    if not config.get("is_active"):
        return False
    setattr(request, REQUEST_THEME_OVERRIDE_ATTR, config["key"])
    return True


def _active_or_default(theme_name: str) -> dict[str, object]:
    config = get_theme_config(theme_name)
    if config.get("is_active"):
        return config
    return get_theme_config(DEFAULT_GAME_THEME_KEY)
