from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from scripts.check_legacy_proposal import check_legacy_proposal_residuals


class LegacyProposalResidualCheckTests(SimpleTestCase):
    def test_rejects_product_code_using_legacy_identifier(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            legacy_import = "from core." + "proposals import " + "Proposal" + "Vote\n"
            (root / "feature.py").write_text(legacy_import, encoding="utf-8")

            errors = check_legacy_proposal_residuals(liveos_root=root)

        self.assertTrue(any("旧领域模块" in error for error in errors))
        old_model_label = "旧模型 Proposal" + "Vote"
        self.assertTrue(any(old_model_label in error for error in errors))

    def test_allows_this_change_to_record_process_history(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            process_dir = root / "openspec" / "changes" / "remove-legacy-proposal-system"
            process_dir.mkdir(parents=True)
            process_history = "删除 Proposal" + "Execution。\n"
            (process_dir / "design.md").write_text(process_history, encoding="utf-8")

            errors = check_legacy_proposal_residuals(liveos_root=root)

        self.assertEqual(errors, [])
