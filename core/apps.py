from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Core Live OS domain app.

    This app owns the first v0.1 authority records that the Simulation Engine
    must access through the public API instead of direct database writes.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Live OS 核心"

    def ready(self) -> None:
        from . import governance_signals  # noqa: F401
