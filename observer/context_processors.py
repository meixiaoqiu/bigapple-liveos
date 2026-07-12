"""Template context processors for shared presentation state."""

from __future__ import annotations

from django.http import HttpRequest

from .theme import get_active_theme, get_active_theme_name, get_available_themes, get_theme_static_base


def theme_context(request: HttpRequest) -> dict[str, object]:
    """Expose active theme metadata to every Django template."""

    active_config = get_active_theme(request)
    return {
        "active_theme": get_active_theme_name(request),
        "active_theme_config": active_config,
        "daisy_theme": active_config["daisy_theme"],
        "available_themes": get_available_themes(),
        "theme_static_base": get_theme_static_base(request),
    }
