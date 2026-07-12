"""测试专用设置。

测试默认使用 SQLite 内存数据库，避免本地 MySQL 连接成为单元测试前置条件。
生产和本地开发运行仍使用 `live_os.settings`。
"""

import os


os.environ.setdefault("BIG_APPLE_ALLOW_NON_MYSQL_DATABASE", "true")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from .settings import *  # noqa: F403


ROOT_URLCONF = "live_os.urls_test"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    },
    "realworld": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    },
    "simulation0001": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
WORLD_DATABASE_ROUTING_ENABLED = False
DEFAULT_WORLD_DATABASE_ALIAS = "default"
WORLD_DATABASE_ALIASES = ("realworld", "simulation0001")

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]
