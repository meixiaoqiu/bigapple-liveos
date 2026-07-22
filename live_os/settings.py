"""Django settings for the Big Apple Live OS prototype.

The settings intentionally avoid third-party configuration helpers so that the
repository can be inspected before dependencies are installed. `DATABASE_URL`
is parsed with the Python standard library.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlparse

from django.core.exceptions import ImproperlyConfigured


BASE_DIR = Path(__file__).resolve().parents[1]
DATABASE_ENV_FILE = BASE_DIR / ".env"

DEFAULT_LOCAL_SECRET_KEY = "insecure-local-development-key"
LOCAL_ENVIRONMENTS = {"local", "development", "dev", "test"}
APP_ENV = os.environ.get("BIG_APPLE_ENV", os.environ.get("DJANGO_ENV", "local")).strip().lower() or "local"
IS_LOCAL_ENV = APP_ENV in LOCAL_ENVIRONMENTS


def parse_bool_setting(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_int_setting(value: str | None, *, default: int = 0) -> int:
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ImproperlyConfigured(f"Invalid integer setting value: {value}") from exc


def parse_csv_setting(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or (DEFAULT_LOCAL_SECRET_KEY if IS_LOCAL_ENV else "")
DEBUG = parse_bool_setting(os.environ.get("DJANGO_DEBUG"), default=IS_LOCAL_ENV)
ALLOWED_HOSTS = parse_csv_setting(
    os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,bigadmin.local,bigreal.local,bigsim.local")
)
CSRF_TRUSTED_ORIGINS = parse_csv_setting(os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", ""))
SECURE_SSL_REDIRECT = parse_bool_setting(os.environ.get("DJANGO_SECURE_SSL_REDIRECT"), default=not IS_LOCAL_ENV)
SESSION_COOKIE_SECURE = parse_bool_setting(os.environ.get("DJANGO_SESSION_COOKIE_SECURE"), default=not IS_LOCAL_ENV)
CSRF_COOKIE_SECURE = parse_bool_setting(os.environ.get("DJANGO_CSRF_COOKIE_SECURE"), default=not IS_LOCAL_ENV)
SECURE_HSTS_SECONDS = parse_int_setting(
    os.environ.get("DJANGO_SECURE_HSTS_SECONDS"),
    default=0 if IS_LOCAL_ENV else 31536000,
)
SECURE_HSTS_INCLUDE_SUBDOMAINS = parse_bool_setting(
    os.environ.get("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS"),
    default=not IS_LOCAL_ENV,
)
SECURE_HSTS_PRELOAD = parse_bool_setting(os.environ.get("DJANGO_SECURE_HSTS_PRELOAD"), default=False)


def validate_runtime_security(
    *,
    app_env: str,
    secret_key: str,
    debug: bool,
    allowed_hosts: list[str],
    secure_ssl_redirect: bool,
    session_cookie_secure: bool,
    csrf_cookie_secure: bool,
    secure_hsts_seconds: int,
) -> None:
    if app_env in LOCAL_ENVIRONMENTS:
        return
    if not secret_key or secret_key == DEFAULT_LOCAL_SECRET_KEY:
        raise ImproperlyConfigured("非本地环境必须显式设置 DJANGO_SECRET_KEY。")
    if debug:
        raise ImproperlyConfigured("非本地环境必须设置 DJANGO_DEBUG=false。")
    if not os.environ.get("DJANGO_ALLOWED_HOSTS") or not allowed_hosts or "*" in allowed_hosts:
        raise ImproperlyConfigured("非本地环境必须显式设置 DJANGO_ALLOWED_HOSTS，且不能使用 *。")
    if not secure_ssl_redirect:
        raise ImproperlyConfigured("非本地环境必须启用 DJANGO_SECURE_SSL_REDIRECT=true。")
    if not session_cookie_secure:
        raise ImproperlyConfigured("非本地环境必须启用 DJANGO_SESSION_COOKIE_SECURE=true。")
    if not csrf_cookie_secure:
        raise ImproperlyConfigured("非本地环境必须启用 DJANGO_CSRF_COOKIE_SECURE=true。")
    if secure_hsts_seconds <= 0:
        raise ImproperlyConfigured("非本地环境必须设置 DJANGO_SECURE_HSTS_SECONDS 为正整数。")


validate_runtime_security(
    app_env=APP_ENV,
    secret_key=SECRET_KEY,
    debug=DEBUG,
    allowed_hosts=ALLOWED_HOSTS,
    secure_ssl_redirect=SECURE_SSL_REDIRECT,
    session_cookie_secure=SESSION_COOKIE_SECURE,
    csrf_cookie_secure=CSRF_COOKIE_SECURE,
    secure_hsts_seconds=SECURE_HSTS_SECONDS,
)

INSTALLED_APPS = [
    "tailwind",
    "django_htmx",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "worlds.apps.WorldsConfig",
    "core.apps.CoreConfig",
    "applications.apps.ApplicationsConfig",
    "workspace.apps.WorkspaceConfig",
    "observer.apps.ObserverConfig",
    "simulation.apps.SimulationConfig",
    "simulation_lab.apps.SimulationLabConfig",
    "feedback.apps.FeedbackConfig",
    "finance.apps.FinanceConfig",
    "theme",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "worlds.middleware.WorldContextMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "live_os.middleware.FriendlyErrorPageMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "worlds.middleware.WorldSessionBoundaryMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "live_os.urls_admin"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "observer.context_processors.theme_context",
                "live_os.context_processors.runtime_nav",
            ],
        },
    },
]

WSGI_APPLICATION = "live_os.wsgi.application"
ASGI_APPLICATION = "live_os.asgi.application"


def _decoded_url_value(value: str | None) -> str:
    """Decode URL-escaped credentials and database names."""

    return unquote(value or "")


def _clean_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def config_value_from_env_file(path: Path, target_key: str) -> str:
    """Read DATABASE_URL from a simple local env file.

    Supported syntax is intentionally small:
    `DATABASE_URL=mysql://...` or `export DATABASE_URL=mysql://...`.
    """

    if not path.exists():
        return ""

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key.removeprefix("export ").strip()
        if key == target_key:
            return _clean_env_value(value)
    return ""


def config_value(key: str, default: str = "") -> str:
    value = os.environ.get(key, "").strip()
    if value:
        return value
    return config_value_from_env_file(DATABASE_ENV_FILE, key) or default


def database_url_from_env_file(path: Path) -> str:
    return config_value_from_env_file(path, "DATABASE_URL")


def get_database_url(key: str = "DATABASE_URL", *, default: str = "") -> str:
    database_url = config_value(key)
    if database_url:
        return database_url

    if default:
        return default

    raise ImproperlyConfigured(
        "未找到数据库连接信息。请在项目根目录 .env 中填写 "
        "DATABASE_URL=mysql://用户名:URL编码后的密码@主机:3306/数据库名?charset=utf8mb4。"
    )


def require_mysql_database_url(url: str) -> None:
    if os.environ.get("BIG_APPLE_ALLOW_NON_MYSQL_DATABASE", "").lower() in {
        "1",
        "true",
        "yes",
    }:
        return
    if not url.startswith("mysql://"):
        raise ImproperlyConfigured(
            "当前项目已切换为 MySQL 运行模式，DATABASE_URL 必须使用 mysql://。"
        )
    if "CHANGE_ME" in url:
        raise ImproperlyConfigured(
            "请先替换项目根目录 .env 中 DATABASE_URL 里的 CHANGE_ME。"
        )


def database_from_url(url: str) -> dict[str, object]:
    """Convert DATABASE_URL into Django's DATABASES setting.

    MySQL 8 with InnoDB is the current runtime target. SQLite remains the test
    fallback.
    """

    parsed = urlparse(url)
    if parsed.scheme in {"postgres", "postgresql"}:
        raise ValueError("PostgreSQL is no longer supported; use mysql://.")
    if parsed.scheme == "mysql":
        options = {
            "charset": "utf8mb4",
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
            "isolation_level": "read committed",
        }
        options.update(dict(parse_qsl(parsed.query)))
        return {
            "ENGINE": "django.db.backends.mysql",
            "NAME": _decoded_url_value(parsed.path.lstrip("/")),
            "USER": _decoded_url_value(parsed.username),
            "PASSWORD": _decoded_url_value(parsed.password),
            "HOST": parsed.hostname or "",
            "PORT": str(parsed.port or 3306),
            "OPTIONS": options,
        }
    if parsed.scheme == "sqlite":
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": parsed.path or str(BASE_DIR / "db.sqlite3"),
        }
    raise ValueError(f"Unsupported DATABASE_URL scheme: {parsed.scheme}")


def database_url_with_name(url: str, database_name: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme == "sqlite" or not database_name:
        return url
    return parsed._replace(path=f"/{database_name}").geturl()


def setting_key_for_database_alias(alias: str, suffix: str) -> str:
    normalized = "".join(char if char.isalnum() else "_" for char in alias.upper())
    return f"BIG_APPLE_{normalized}_{suffix}"


def default_world_database_name(alias: str) -> str:
    if alias == "realworld":
        return "dev_big_real"
    if alias.startswith("simulation"):
        return f"dev_big_sim{alias.removeprefix('simulation')}"
    normalized = alias.replace("-", "_")
    return f"dev_big_{normalized}"


def parse_world_database_aliases(value: str) -> tuple[str, ...]:
    aliases: list[str] = []
    seen: set[str] = set()
    for raw_alias in value.split(","):
        alias = raw_alias.strip()
        if not alias or alias in seen:
            continue
        aliases.append(alias)
        seen.add(alias)
    return tuple(aliases)


def world_database_url_for_alias(alias: str, base_url: str) -> str:
    database_name_key = setting_key_for_database_alias(alias, "DB_NAME")
    database_url_key = setting_key_for_database_alias(alias, "DATABASE_URL")
    database_name = config_value(database_name_key, default_world_database_name(alias))
    return get_database_url(database_url_key, default=database_url_with_name(base_url, database_name))


BASE_DATABASE_URL = get_database_url()
CONTROL_DATABASE_NAME = config_value("BIG_APPLE_CONTROL_DB_NAME", "dev_big_control")
WORLD_DATABASE_ALIASES = parse_world_database_aliases(
    config_value("BIG_APPLE_WORLD_DATABASE_ALIASES", "realworld,simulation0001")
)

DATABASE_URL = get_database_url(
    "BIG_APPLE_CONTROL_DATABASE_URL",
    default=database_url_with_name(BASE_DATABASE_URL, CONTROL_DATABASE_NAME),
)
require_mysql_database_url(DATABASE_URL)
DATABASES = {
    "default": database_from_url(DATABASE_URL),
}
CONTROL_DATABASE_ALIAS = "default"
for database_alias in WORLD_DATABASE_ALIASES:
    if database_alias == "default":
        continue
    world_database_url = world_database_url_for_alias(database_alias, BASE_DATABASE_URL)
    require_mysql_database_url(world_database_url)
    DATABASES[database_alias] = database_from_url(world_database_url)
WORLD_DATABASE_ROUTING_ENABLED = parse_bool_setting(
    config_value("BIG_APPLE_WORLD_DATABASE_ROUTING_ENABLED") or None,
    default=True,
)
DEFAULT_WORLD_DATABASE_ALIAS = config_value("BIG_APPLE_DEFAULT_WORLD_DATABASE_ALIAS", "realworld")
DATABASE_ROUTERS = ["worlds.db.WorldDatabaseRouter"]

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True
WORLD_INSTANCE_TYPE = os.environ.get("WORLD_INSTANCE_TYPE", "simulation").strip().lower() or "simulation"

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
SIMULATION_ARCHIVE_ROOT = Path(config_value("BIG_APPLE_SIMULATION_ARCHIVE_ROOT", str(BASE_DIR / "var" / "simulation_archives")))
TAILWIND_APP_NAME = "theme"
NPM_BIN_PATH = os.environ.get("NPM_BIN_PATH", "npm.cmd" if os.name == "nt" else "npm")
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

ACTIVE_THEME = os.environ.get("ACTIVE_THEME", "default_game")
THEME_CONFIGS = {
    "default_game": {
        "key": "default_game",
        "name": "默认游戏骨架",
        "description": "面向公众观察台的最小可运行主题骨架。",
        "template_dir": "themes/default_game",
        "static_dir": "themes/default_game",
        "daisy_theme": "light",
        "preview_image": "",
        "is_active": True,
        "supports_mobile": True,
        "supports_animations": True,
    },
    "dark": {
        "key": "dark",
        "name": "深色实验主题",
        "description": "仅切换 daisyUI dark；缺失模板和资源回退到 default_game。",
        "template_dir": "themes/dark",
        "static_dir": "themes/dark",
        "daisy_theme": "dark",
        "preview_image": "",
        "is_active": True,
        "supports_mobile": True,
        "supports_animations": True,
    },
}

BIG_APPLE_CONTRACTS_ROOT = Path(
    os.environ.get("BIG_APPLE_CONTRACTS_ROOT", "../bigapple-docs/static/technical-contracts")
)
if not BIG_APPLE_CONTRACTS_ROOT.is_absolute():
    BIG_APPLE_CONTRACTS_ROOT = (BASE_DIR / BIG_APPLE_CONTRACTS_ROOT).resolve()
