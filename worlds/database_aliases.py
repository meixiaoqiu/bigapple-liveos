from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def require_configured_world_database_alias(alias: str) -> str:
    """Return a configured world database alias or fail closed.

    World-scoped business data must never silently fall back to the control
    database. When routing is enabled, every active world must point at a
    configured non-default alias listed in ``WORLD_DATABASE_ALIASES``.
    """

    checked = str(alias or "").strip()
    if not checked:
        raise ImproperlyConfigured("World database alias cannot be empty.")

    if not getattr(settings, "WORLD_DATABASE_ROUTING_ENABLED", True):
        return checked

    if checked == "default":
        raise ImproperlyConfigured("World database alias cannot be the control database alias: default.")
    if checked not in settings.DATABASES:
        raise ImproperlyConfigured(f"World database alias is not configured in settings.DATABASES: {checked}")
    if checked not in set(getattr(settings, "WORLD_DATABASE_ALIASES", ())):
        raise ImproperlyConfigured(f"World database alias is not listed in WORLD_DATABASE_ALIASES: {checked}")
    return checked
