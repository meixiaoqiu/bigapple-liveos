"""Theme configuration registry."""

from __future__ import annotations

from django.conf import settings

from .utils import _bool, _clean_path

THEME_SESSION_KEY = "active_theme"
DEFAULT_GAME_THEME_KEY = "default_game"


def get_theme_configs() -> dict[str, dict[str, object]]:
    """Return normalized theme configs keyed by theme key."""

    raw_configs = getattr(settings, "THEME_CONFIGS", {})
    if isinstance(raw_configs, dict):
        config_items = raw_configs.items()
    else:
        config_items = ((config.get("key") or config.get("name") or "", config) for config in raw_configs)

    configs: dict[str, dict[str, object]] = {}
    for config_key, raw_config in config_items:
        if not isinstance(raw_config, dict):
            continue
        key = str(raw_config.get("key") or config_key).strip()
        if not key:
            continue
        configs[key] = {
            "key": key,
            "name": str(raw_config.get("name") or key),
            "description": str(raw_config.get("description") or ""),
            "template_dir": _clean_path(raw_config.get("template_dir"), f"themes/{key}"),
            "static_dir": _clean_path(raw_config.get("static_dir"), f"themes/{key}"),
            "daisy_theme": str(raw_config.get("daisy_theme") or "light"),
            "preview_image": str(raw_config.get("preview_image") or ""),
            "is_active": _bool(raw_config.get("is_active"), True),
            "supports_mobile": _bool(raw_config.get("supports_mobile"), True),
            "supports_animations": _bool(raw_config.get("supports_animations"), False),
            "alias_of": str(raw_config.get("alias_of") or ""),
        }

    if DEFAULT_GAME_THEME_KEY not in configs:
        configs[DEFAULT_GAME_THEME_KEY] = {
            "key": DEFAULT_GAME_THEME_KEY,
            "name": "默认游戏骨架",
            "description": "面向公众观察台的最小可运行主题骨架。",
            "template_dir": f"themes/{DEFAULT_GAME_THEME_KEY}",
            "static_dir": f"themes/{DEFAULT_GAME_THEME_KEY}",
            "daisy_theme": "light",
            "preview_image": "",
            "is_active": True,
            "supports_mobile": True,
            "supports_animations": True,
            "alias_of": "",
        }
    return configs


def get_theme_config(theme_key: str | None) -> dict[str, object]:
    """Return a valid theme config, resolving aliases and unknown keys."""

    configs = get_theme_configs()
    requested_key = str(theme_key or "").strip() or DEFAULT_GAME_THEME_KEY
    config = configs.get(requested_key)
    if config is None:
        return configs[DEFAULT_GAME_THEME_KEY]

    alias_of = str(config.get("alias_of") or "")
    if alias_of and alias_of in configs:
        return configs[alias_of]
    return config


def get_default_theme_name() -> str:
    """Return the configured default theme key, falling back to default_game."""

    configured = str(getattr(settings, "ACTIVE_THEME", DEFAULT_GAME_THEME_KEY))
    return str(get_theme_config(configured)["key"])


def get_available_themes() -> list[dict[str, object]]:
    """Return switchable themes in display order."""

    return [config for config in get_theme_configs().values() if config.get("is_active")]
