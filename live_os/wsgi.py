"""WSGI entry point for Big Apple Live OS."""

import os

from django.core.wsgi import get_wsgi_application


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "live_os.settings")

application = get_wsgi_application()

