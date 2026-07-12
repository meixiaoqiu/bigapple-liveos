"""Single simulation-world runtime settings for bigsim.local."""

from .settings import *  # noqa: F401,F403


SITE_ROLE = "simulation"
SITE_FIXED_WORLD = True
SITE_WORLD_ID = config_value("BIG_APPLE_SIM_SITE_WORLD_ID", "simulation0001")
SITE_WORLD_TYPE = "simulation"
SITE_WORLD_DATABASE_ALIAS = "default"

SIMULATION_DATABASE_URL = world_database_url_for_alias(SITE_WORLD_ID, BASE_DATABASE_URL)
require_mysql_database_url(SIMULATION_DATABASE_URL)
DATABASES = {
    "default": database_from_url(SIMULATION_DATABASE_URL),
}
SITE_WORLD_DATABASE_NAME = str(DATABASES["default"].get("NAME", ""))
WORLD_DATABASE_ROUTING_ENABLED = False
WORLD_DATABASE_ALIASES = ("default",)
DEFAULT_WORLD_DATABASE_ALIAS = "default"
DATABASE_ROUTERS = []
ROOT_URLCONF = "live_os.urls_sim"
WORLD_INSTANCE_TYPE = "simulation"
ALLOWED_HOSTS = [*ALLOWED_HOSTS, "bigsim.local"] if "bigsim.local" not in ALLOWED_HOSTS else ALLOWED_HOSTS
