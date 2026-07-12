"""WSGI entry point for the real-world site."""

import os

from django.core.wsgi import get_wsgi_application


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "live_os.settings_real")

application = get_wsgi_application()
