"""Theme template fallback helpers."""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from django.template import TemplateDoesNotExist
from django.template.loader import select_template

from .active import get_active_theme
from .config import DEFAULT_GAME_THEME_KEY, get_theme_config
from .utils import _clean_path


def _candidate_paths(request: HttpRequest, relative_path: str) -> list[str]:
    normalized_path = _clean_path(relative_path)
    active_config = get_active_theme(request)
    default_config = get_theme_config(DEFAULT_GAME_THEME_KEY)

    candidates = [
        f"{active_config['template_dir']}/{normalized_path}",
        f"{default_config['template_dir']}/{normalized_path}",
    ]
    return list(dict.fromkeys(candidates))


def _select_existing_template(candidates: list[str], safe_fallback: str = "") -> str:
    try:
        template = select_template(candidates)
    except TemplateDoesNotExist:
        return safe_fallback

    origin = getattr(template, "origin", None)
    if origin is not None:
        return str(origin.template_name)

    backend_template: Any = getattr(template, "template", None)
    backend_name = getattr(backend_template, "name", None)
    return str(backend_name or candidates[0])


def get_theme_template_path(request: HttpRequest, template_name: str) -> str:
    """Resolve a full page template through active/default fallback."""

    normalized_name = _clean_path(template_name)
    return _select_existing_template(
        _candidate_paths(request, normalized_name),
        safe_fallback=normalized_name,
    )


def get_theme_partial_path(request: HttpRequest, partial_name: str) -> str:
    """Resolve a theme partial path with default_game fallback."""

    normalized_name = _clean_path(partial_name)
    if not normalized_name.startswith("partials/"):
        normalized_name = f"partials/{normalized_name}"
    return _select_existing_template(
        _candidate_paths(request, normalized_name),
        safe_fallback=f"themes/{DEFAULT_GAME_THEME_KEY}/components/empty_state.html",
    )

def get_theme_component_path(request: HttpRequest, component_name: str) -> str:
    """Resolve a theme component path with default_game fallback."""

    normalized_name = _clean_path(component_name)
    if not normalized_name.startswith("components/"):
        normalized_name = f"components/{normalized_name}"
    return _select_existing_template(
        _candidate_paths(request, normalized_name),
        safe_fallback=f"themes/{DEFAULT_GAME_THEME_KEY}/components/empty_state.html",
    )
