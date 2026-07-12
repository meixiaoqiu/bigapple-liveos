"""ASGI entry point for the simulation-world site."""

import os

from django.core.asgi import get_asgi_application


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "live_os.settings_sim")

application = get_asgi_application()
