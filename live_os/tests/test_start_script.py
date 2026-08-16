from pathlib import Path
from unittest import TestCase


class StartScriptMigrationTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.root = Path(__file__).resolve().parents[2]
        cls.script = (cls.root / "start.bat").read_text(encoding="utf-8")
        cls.helper_path = cls.root / "scripts" / "Invoke-WorldMigration.ps1"
        cls.helper = cls.helper_path.read_text(encoding="utf-8-sig")

    def test_start_script_passes_each_fixed_world_configuration(self):
        self.assertIn(
            "Invoke-WorldMigration.ps1 -DatabaseAlias default "
            "-Service big-apple-admin -SettingsModule live_os.settings_admin",
            self.script,
        )
        self.assertIn(
            "Invoke-WorldMigration.ps1 -DatabaseAlias realworld "
            "-Service big-apple-real -SettingsModule live_os.settings_real",
            self.script,
        )
        self.assertIn(
            "Invoke-WorldMigration.ps1 -DatabaseAlias simulation0001 "
            "-Service big-apple-sim -SettingsModule live_os.settings_sim",
            self.script,
        )

    def test_helper_runs_migrate_for_the_selected_fixed_world(self):
        self.assertIn(
            "$Service python manage.py migrate --noinput \"--settings=$SettingsModule\"",
            self.helper,
        )
        self.assertNotIn("--database realworld", self.helper)
        self.assertNotIn("--database simulation0001", self.helper)

    def test_migration_commands_disable_compose_stdin(self):
        self.assertEqual(self.script.count("run --interactive=false --rm --no-deps"), 0)
        self.assertEqual(self.helper.count("run --interactive=false --rm --no-deps"), 3)
        self.assertNotIn("run --rm --no-deps", self.script)
        self.assertNotIn("run --rm --no-deps", self.helper)

    def test_world_migration_uses_utf8_and_ascii_schema_marker(self):
        self.assertIn("[Console]::OutputEncoding = $utf8NoBom", self.helper)
        self.assertIn('$legacyProposalSchemaMarker = "LEGACY_PROPOSAL_SCHEMA_DETECTED"', self.helper)
        self.assertIn("$combinedSchemaOutput.Contains($legacyProposalSchemaMarker)", self.helper)
        self.assertIn("chcp 65001 >nul", self.script)

    def test_helper_rejects_mismatched_world_configuration_before_docker(self):
        self.assertIn('"default" = @{', self.helper)
        self.assertIn('Service = "big-apple-admin"', self.helper)
        self.assertIn('SettingsModule = "live_os.settings_admin"', self.helper)
        self.assertIn('"realworld" = @{', self.helper)
        self.assertIn('Service = "big-apple-real"', self.helper)
        self.assertIn('SettingsModule = "live_os.settings_real"', self.helper)
        self.assertIn('"simulation0001" = @{', self.helper)
        self.assertIn('Service = "big-apple-sim"', self.helper)
        self.assertIn('SettingsModule = "live_os.settings_sim"', self.helper)
        self.assertIn("参数组合无效", self.helper)
        self.assertLess(
            self.helper.index("参数组合无效"),
            self.helper.index("& docker compose"),
        )

    def test_helper_has_utf8_bom_for_windows_powershell_compatibility(self):
        self.assertTrue(self.helper_path.read_bytes().startswith(b"\xef\xbb\xbf"))


class OpenFgaStartupGuidanceTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.script_path = Path(__file__).resolve().parents[2] / "scripts" / "Invoke-OpenFgaLocalSetup.ps1"
        cls.script = cls.script_path.read_text(encoding="utf-8-sig")

    def test_configuration_failure_explains_manual_recovery_in_chinese(self):
        self.assertIn("OpenFGA 配置校验失败，启动已停止。", self.script)
        self.assertIn("请按以下步骤处理：", self.script)
        self.assertIn("--world-kind real", self.script)
        self.assertIn("--world-kind sim", self.script)
        self.assertIn("OPENFGA_REAL_AUTHORIZATION_MODEL_ID", self.script)
        self.assertIn("OPENFGA_SIM_AUTHORIZATION_MODEL_ID", self.script)
        self.assertIn("OPENFGA_AUTHORIZATION_MODEL_SHA256", self.script)
        self.assertIn("保存 .env 后重新运行 start.bat", self.script)

    def test_script_has_utf8_bom_for_windows_powershell_compatibility(self):
        self.assertTrue(self.script_path.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_one_shot_compose_commands_disable_stdin(self):
        self.assertEqual(self.script.count('"run", "--interactive=false", "--rm"'), 4)
        self.assertEqual(self.script.count("run --interactive=false --rm --no-deps"), 2)
        self.assertNotIn('"run", "--rm"', self.script)
        self.assertNotIn("run --rm --no-deps", self.script)
