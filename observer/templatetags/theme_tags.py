"""Template tags for theme-aware template inclusion."""

from __future__ import annotations

from django import template

from observer.theme import (
    get_theme_asset_url,
    get_theme_component_path,
    get_theme_partial_path,
)


register = template.Library()


@register.simple_tag(takes_context=True)
def themed_partial(context: template.Context, partial_name: str) -> str:
    """Resolve a partial through active theme and default_game fallback."""

    request = context.get("request")
    if request is None:
        return partial_name
    return get_theme_partial_path(request, partial_name)


@register.simple_tag(takes_context=True)
def themed_component(context: template.Context, component_name: str) -> str:
    """Resolve a component through active theme and default_game fallback."""

    request = context.get("request")
    if request is None:
        return component_name
    return get_theme_component_path(request, component_name)


@register.simple_tag(takes_context=True)
def theme_asset(context: template.Context, asset_path: str) -> str:
    """Return a safe static URL for a theme asset or an empty string."""

    request = context.get("request")
    if request is None:
        return ""
    return get_theme_asset_url(request, asset_path)
