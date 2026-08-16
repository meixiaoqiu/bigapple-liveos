from pathlib import Path
from unittest import TestCase


class ProjectContractCheckTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        root = Path(__file__).resolve().parents[2]
        cls.check_script = (root / "scripts" / "check_project.py").read_text(encoding="utf-8")

    def test_event_feedback_contract_replaces_retired_dispute_contract(self) -> None:
        self.assertIn('"schemas/event-feedback.schema.json"', self.check_script)
        self.assertNotIn('"schemas/dispute.schema.json"', self.check_script)
