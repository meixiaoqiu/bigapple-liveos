"""Management command: evaluate all risk rules and create/update RiskAlerts."""

from django.core.management.base import BaseCommand
from core.risk_services import evaluate_all_risks


class Command(BaseCommand):
    help = "Evaluate all risk rules and create/update RiskAlerts."

    def handle(self, *args, **options):
        result = evaluate_all_risks()
        self.stdout.write(self.style.SUCCESS(f"Risk evaluation complete: {result}"))
