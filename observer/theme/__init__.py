"""Theme selection, fallback, and static asset helpers."""

from .active import (
    get_active_theme,
    get_active_theme_config,
    get_active_theme_name,
    set_active_theme,
    set_request_theme_override,
)
from .assets import SUPPORTED_ASSET_ROOTS, get_theme_asset_url, get_theme_static_base
from .config import (
    DEFAULT_GAME_THEME_KEY,
    THEME_SESSION_KEY,
    get_available_themes,
    get_default_theme_name,
    get_theme_config,
    get_theme_configs,
)
from .templates import (
    get_theme_component_path,
    get_theme_partial_path,
    get_theme_template_path,
)

__all__ = [
    "THEME_SESSION_KEY",
    "DEFAULT_GAME_THEME_KEY",
    "SUPPORTED_ASSET_ROOTS",
    "get_theme_configs",
    "get_theme_config",
    "get_default_theme_name",
    "get_available_themes",
    "get_active_theme",
    "get_active_theme_name",
    "get_active_theme_config",
    "set_active_theme",
    "set_request_theme_override",
    "get_theme_template_path",
    "get_theme_partial_path",
    "get_theme_component_path",
    "get_theme_static_base",
    "get_theme_asset_url",
]
