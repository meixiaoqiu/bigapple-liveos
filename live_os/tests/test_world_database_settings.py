from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase

from live_os import settings as live_settings


class WorldDatabaseSettingsTests(SimpleTestCase):
    def test_default_settings_use_control_admin_urlconf(self) -> None:
        self.assertEqual(live_settings.ROOT_URLCONF, "live_os.urls_admin")

    def test_parse_world_database_aliases_deduplicates_ordered_aliases(self) -> None:
        aliases = live_settings.parse_world_database_aliases("realworld, simulation0001, realworld,simulation0002")

        self.assertEqual(aliases, ("realworld", "simulation0001", "simulation0002"))

    def test_setting_key_for_database_alias_uses_uppercase_safe_name(self) -> None:
        self.assertEqual(
            live_settings.setting_key_for_database_alias("simulation-0002", "DATABASE_URL"),
            "BIG_APPLE_SIMULATION_0002_DATABASE_URL",
        )

    def test_default_world_database_name_keeps_short_simulation_prefix(self) -> None:
        self.assertEqual(live_settings.default_world_database_name("realworld"), "dev_big_real")
        self.assertEqual(live_settings.default_world_database_name("simulation0002"), "dev_big_sim0002")
        self.assertEqual(live_settings.default_world_database_name("custom-world"), "dev_big_custom_world")

    def test_world_database_url_for_alias_uses_default_derived_database_name(self) -> None:
        base_url = "mysql://user:pass@mysql97:3306/dev_big_control?charset=utf8mb4"

        with patch.object(live_settings, "config_value", side_effect=lambda _key, default="": default):
            database_url = live_settings.world_database_url_for_alias("simulation0002", base_url)

        self.assertEqual(database_url, "mysql://user:pass@mysql97:3306/dev_big_sim0002?charset=utf8mb4")

    def test_world_database_url_for_alias_allows_explicit_database_url(self) -> None:
        base_url = "mysql://user:pass@mysql97:3306/dev_big_control?charset=utf8mb4"

        def fake_config(key: str, default: str = "") -> str:
            if key == "BIG_APPLE_SIMULATION0002_DATABASE_URL":
                return "mysql://user:pass@mysql97:3306/custom_sim?charset=utf8mb4"
            return default

        with patch.object(live_settings, "config_value", side_effect=fake_config):
            database_url = live_settings.world_database_url_for_alias("simulation0002", base_url)

        self.assertEqual(database_url, "mysql://user:pass@mysql97:3306/custom_sim?charset=utf8mb4")
