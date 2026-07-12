"""ASGI entry point for Big Apple Live OS."""

import os

from django.core.asgi import get_asgi_application


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "live_os.settings")

application = get_asgi_application()

