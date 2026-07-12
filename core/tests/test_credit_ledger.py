from __future__ import annotations

from django.test import TestCase

from core.models import LedgerEntry, SystemEvent
from core.ledger_services import create_ledger_entry, ledger_balance_for_member, reverse_ledger_entry
from core.service_utils import actor_ref
from core.event_ledger import verify_event_chain
from core.tests.helpers import create_member


class CreditLedgerTests(TestCase):
    def test_credit_entry_appends_system_event(self) -> None:
        member = create_member("member-credit-earned")
        entry = create_ledger_entry(
            ledger_entry_id="ledger-credit-earned",
            member=member,
            amount=30,
            entry_type=LedgerEntry.EntryType.CONTRIBUTION,
            reason="完成公共维护任务",
            rule_version="ruleset-v0.1.0",
            created_by=actor_ref(member),
            reviewer=actor_ref(member),
        )

        entry.refresh_from_db()

        self.assertIsNotNone(entry.system_event)
        self.assertEqual(entry.system_event.event_type, SystemEvent.EventType.CREDIT_EARNED)
        self.assertEqual(entry.system_event.aggregate_type, "LedgerEntry")
        self.assertEqual(entry.system_event.aggregate_id, entry.pk)
        self.assertEqual(entry.system_event.actor_member, member)
        self.assertTrue(verify_event_chain())

    def test_credit_reversal_appends_system_event_and_balance_is_derived(self) -> None:
        member = create_member("member-credit-reversal")
        original = create_ledger_entry(
            ledger_entry_id="ledger-credit-original",
            member=member,
            amount=40,
            entry_type=LedgerEntry.EntryType.CONTRIBUTION,
            reason="原始积分",
            rule_version="ruleset-v0.1.0",
            created_by=actor_ref(member),
            reviewer=actor_ref(member),
        )

        reversal = reverse_ledger_entry(
            entry=original,
            ledger_entry_id="ledger-credit-reversal",
            reason="冲正原始积分",
            created_by=actor_ref(member),
        )

        self.assertEqual(reversal.amount, -40)
        self.assertEqual(reversal.entry_type, LedgerEntry.EntryType.REVERSAL)
        self.assertEqual(reversal.reverses_entry, original)
        self.assertEqual(reversal.system_event.event_type, SystemEvent.EventType.CREDIT_REVERSED)
        self.assertEqual(ledger_balance_for_member(member), 0)
        self.assertTrue(verify_event_chain())
