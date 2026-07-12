"""Single real-world runtime settings for bigreal.local."""

from .settings import *  # noqa: F401,F403


SITE_ROLE = "real"
SITE_FIXED_WORLD = True
SITE_WORLD_ID = config_value("BIG_APPLE_REAL_SITE_WORLD_ID", "realworld")
SITE_WORLD_TYPE = "real"
SITE_WORLD_DATABASE_ALIAS = "default"

REALWORLD_DATABASE_URL = world_database_url_for_alias(SITE_WORLD_ID, BASE_DATABASE_URL)
require_mysql_database_url(REALWORLD_DATABASE_URL)
DATABASES = {
    "default": database_from_url(REALWORLD_DATABASE_URL),
}
SITE_WORLD_DATABASE_NAME = str(DATABASES["default"].get("NAME", ""))
WORLD_DATABASE_ROUTING_ENABLED = False
WORLD_DATABASE_ALIASES = ("default",)
DEFAULT_WORLD_DATABASE_ALIAS = "default"
DATABASE_ROUTERS = []
ROOT_URLCONF = "live_os.urls_real"
WORLD_INSTANCE_TYPE = "real"
ALLOWED_HOSTS = [*ALLOWED_HOSTS, "bigreal.local"] if "bigreal.local" not in ALLOWED_HOSTS else ALLOWED_HOSTS
