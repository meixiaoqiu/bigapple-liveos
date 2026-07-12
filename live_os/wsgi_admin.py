"""WSGI entry point for the control-plane site."""

import os

from django.core.wsgi import get_wsgi_application


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "live_os.settings_admin")

application = get_wsgi_application()
