import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from core.management.commands.check_mysql_readiness import is_case_sensitive_collation
from live_os.settings import (
    DEFAULT_LOCAL_SECRET_KEY,
    database_from_url,
    database_url_from_env_file,
    parse_csv_setting,
    validate_runtime_security,
)


class DatabaseSettingsTests(SimpleTestCase):
    """数据库 URL 解析必须保持后端切换配置可预测。"""

    def test_mysql_url_uses_safe_runtime_defaults(self) -> None:
        config = database_from_url(
            "mysql://live_user:p%40ss@127.0.0.1:3307/big_apple_live?charset=utf8mb4"
        )

        self.assertEqual(config["ENGINE"], "django.db.backends.mysql")
        self.assertEqual(config["NAME"], "big_apple_live")
        self.assertEqual(config["USER"], "live_user")
        self.assertEqual(config["PASSWORD"], "p@ss")
        self.assertEqual(config["HOST"], "127.0.0.1")
        self.assertEqual(config["PORT"], "3307")
        self.assertEqual(config["OPTIONS"]["charset"], "utf8mb4")
        self.assertEqual(config["OPTIONS"]["isolation_level"], "read committed")
        self.assertIn("STRICT_TRANS_TABLES", config["OPTIONS"]["init_command"])

    def test_mysql_url_defaults_to_port_3306(self) -> None:
        config = database_from_url("mysql://live_user:secret@localhost/big_apple_live")

        self.assertEqual(config["PORT"], "3306")

    def test_database_url_can_be_read_from_local_env_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text(
                "\n".join(
                    [
                        "# 本地数据库连接，不提交真实凭据",
                        "export DATABASE_URL='mysql://live_user:p%40ss@127.0.0.1:3306/big_apple_live?charset=utf8mb4'",
                    ]
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                database_url_from_env_file(env_file),
                "mysql://live_user:p%40ss@127.0.0.1:3306/big_apple_live?charset=utf8mb4",
            )

    def test_csv_setting_ignores_empty_items_and_whitespace(self) -> None:
        self.assertEqual(
            parse_csv_setting("localhost, 127.0.0.1, ,https://bigapple.example"),
            ["localhost", "127.0.0.1", "https://bigapple.example"],
        )

    def test_postgresql_url_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "PostgreSQL is no longer supported"):
            database_from_url("postgresql://w:p%40ss@localhost:5432/live")

    def test_mysql_collation_check_requires_case_sensitive_semantics(self) -> None:
        self.assertTrue(is_case_sensitive_collation("utf8mb4_0900_as_cs"))
        self.assertTrue(is_case_sensitive_collation("utf8mb4_bin"))
        self.assertFalse(is_case_sensitive_collation("utf8mb4_0900_ai_ci"))

    def test_local_environment_allows_development_defaults(self) -> None:
        validate_runtime_security(
            app_env="local",
            secret_key=DEFAULT_LOCAL_SECRET_KEY,
            debug=True,
            allowed_hosts=["localhost", "127.0.0.1"],
            secure_ssl_redirect=False,
            session_cookie_secure=False,
            csrf_cookie_secure=False,
            secure_hsts_seconds=0,
        )

    def test_non_local_environment_rejects_insecure_defaults(self) -> None:
        with self.assertRaises(ImproperlyConfigured):
            validate_runtime_security(
                app_env="production",
                secret_key=DEFAULT_LOCAL_SECRET_KEY,
                debug=True,
                allowed_hosts=["example.com"],
                secure_ssl_redirect=True,
                session_cookie_secure=True,
                csrf_cookie_secure=True,
                secure_hsts_seconds=31536000,
            )

    def test_non_local_environment_accepts_explicit_secure_settings(self) -> None:
        with patch.dict(os.environ, {"DJANGO_ALLOWED_HOSTS": "bigapple.example"}, clear=False):
            validate_runtime_security(
                app_env="production",
                secret_key="not-the-local-development-secret",
                debug=False,
                allowed_hosts=["bigapple.example"],
                secure_ssl_redirect=True,
                session_cookie_secure=True,
                csrf_cookie_secure=True,
                secure_hsts_seconds=31536000,
            )
