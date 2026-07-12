"""ASGI entry point for the control-plane site."""

import os

from django.core.asgi import get_asgi_application


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "live_os.settings_admin")

application = get_asgi_application()
