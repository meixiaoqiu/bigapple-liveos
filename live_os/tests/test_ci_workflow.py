from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class MySQLConcurrencyWorkflowTests(SimpleTestCase):
    def test_mysql_job_runs_all_database_locking_test_cases(self):
        workflow = (Path(settings.BASE_DIR) / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("mysql-concurrency:", workflow)
        self.assertIn(
            "core.tests.test_finance_role_appointments.FinanceReviewerAppointmentConcurrencyTests",
            workflow,
        )
        self.assertIn(
            "core.tests.test_event_feedback.EventFeedbackConcurrencyTests",
            workflow,
        )
        self.assertIn("--settings=live_os.settings_real", workflow)
