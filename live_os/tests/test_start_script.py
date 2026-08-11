from pathlib import Path
from unittest import TestCase


class StartScriptMigrationTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.script = (Path(__file__).resolve().parents[2] / "start.bat").read_text(encoding="utf-8")

    def test_fixed_world_settings_migrate_their_default_database(self):
        real_command = (
            "big-apple-real python manage.py migrate --noinput "
            "--settings=live_os.settings_real"
        )
        simulation_command = (
            "big-apple-sim python manage.py migrate --noinput "
            "--settings=live_os.settings_sim"
        )

        self.assertIn(real_command, self.script)
        self.assertIn(simulation_command, self.script)
        self.assertNotIn("--database realworld", self.script)
        self.assertNotIn("--database simulation0001", self.script)

    def test_migration_commands_disable_compose_stdin(self):
        self.assertEqual(self.script.count("run --interactive=false --rm --no-deps"), 3)
        self.assertNotIn("run --rm --no-deps", self.script)


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
