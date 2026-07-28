"""Control-plane settings for bigadmin.local."""

from .settings import *  # noqa: F401,F403


SITE_ROLE = "control"
SITE_FIXED_WORLD = False
BIG_APPLE_AUTHORIZATION_BACKEND = "legacy"
ROOT_URLCONF = "live_os.urls_admin"
ALLOWED_HOSTS = [*ALLOWED_HOSTS, "bigadmin.local"] if "bigadmin.local" not in ALLOWED_HOSTS else ALLOWED_HOSTS
