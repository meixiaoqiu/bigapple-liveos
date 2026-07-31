"""直接角色判断静态盘点的回归测试。"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from django.test import SimpleTestCase


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from check_role_usage import check_role_usage_catalog, discover_role_usages  # noqa: E402


class RoleUsageCheckTests(SimpleTestCase):
    def test_current_production_role_usages_are_all_classified(self) -> None:
        self.assertEqual(check_role_usage_catalog(PROJECT_ROOT), [])

    def test_unclassified_direct_role_check_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sample = root / "module.py"
            sample.write_text(
                "def may_access(member):\n"
                "    return member_has_role(member, '正式成员')\n",
                encoding="utf-8",
            )

            usages = discover_role_usages(root)
            self.assertEqual([usage.location for usage in usages], ["module.py:2"])
            self.assertEqual(
                check_role_usage_catalog(root, catalog={}),
                ["未分类的直接角色判断：module.py:2（调用 member_has_role）"],
            )

    def test_product_source_does_not_keep_old_role_labels(self) -> None:
        forbidden_labels = ("观察者", "预备成员", "大苹果成员", "治理成员", "治理管理员")
        ignored_parts = {".git", ".venv", "node_modules", "openspec", "migrations", "tests", "__pycache__"}
        product_files = [
            path
            for pattern in ("*.py", "*.html")
            for path in PROJECT_ROOT.rglob(pattern)
            if not ignored_parts.intersection(path.relative_to(PROJECT_ROOT).parts)
        ]

        unexpected = [
            f"{path.relative_to(PROJECT_ROOT)}：{label}"
            for path in product_files
            for label in forbidden_labels
            if label in path.read_text(encoding="utf-8")
        ]

        self.assertEqual(unexpected, [])
