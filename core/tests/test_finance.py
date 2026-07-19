"""Finance service and model tests."""

from __future__ import annotations

from django.test import TestCase
from django.utils import timezone

from core.exceptions import DomainError
from core.finance_setup import ensure_finance_roles
from core.finance_services import (
    mark_expense_claim_paid, review_expense_claim, submit_expense_claim, withdraw_expense_claim,
    FINANCE_REVIEW_PERMISSION, FINANCE_PAY_PERMISSION,
)
from core.member_roles import ROLE_FORMAL_MEMBER
from core.models import (
    ExpenseClaim, FinanceReview, FinanceTransaction,
    Organization, Permission, Role, RoleAssignment, RolePermission, SystemEvent, Event,
)
from core.role_assignment_services import create_role_assignment
from core.tests.helpers import create_member, login_as_member
from observer.event_context import public_event_semantic_summary


def _make_finance_member(member_no: str, perm_code: str):
    """Create a member with the given finance permission."""
    member = create_member(member_no, display_name=member_no, role_name=ROLE_FORMAL_MEMBER)
    setup = ensure_finance_roles()
    role = setup["review_role"] if perm_code == FINANCE_REVIEW_PERMISSION else setup["pay_role"]
    create_role_assignment(member=member, role=role)
    return member


class FinanceServiceTests(TestCase):

    def setUp(self):
        self.author = create_member("fin-author", display_name="报销作者")

    def _submit(self, **kw):
        defaults = {"claimant_member": self.author, "title": "test", "description": "", "amount": 1, "expense_date": "2026-01-01"}
        defaults.update(kw)
        return submit_expense_claim(**defaults)

    def test_submit_claim_success(self):
        c = self._submit(title="服务器月费", description="7月", amount=500, category="server")
        self.assertEqual(c.status, ExpenseClaim.Status.SUBMITTED)
        event = Event.objects.get(event_id=f"expense-claim-submitted-{c.claim_id}")
        self.assertEqual(event.payload["source"], "finance")
        self.assertEqual(event.payload["claim_id"], c.claim_id)
        system_event = SystemEvent.objects.get(aggregate_id=c.claim_id)
        self.assertEqual(system_event.event_type, SystemEvent.EventType.EXPENSE_CLAIM_SUBMITTED)
        self.assertEqual(system_event.payload_json["public_facts"]["claim_id"], c.claim_id)

    def test_suspended_cannot_submit(self):
        self.author.status = "suspended"
        self.author.save(update_fields=["status"])
        with self.assertRaises(DomainError):
            self._submit()

    def test_non_reviewer_cannot_review(self):
        c = self._submit()
        with self.assertRaises(DomainError):
            review_expense_claim(claim=c, reviewer_member=self.author, decision="approved")

    def test_cannot_review_own_claim(self):
        reviewer = _make_finance_member("fin-reviewer-self", FINANCE_REVIEW_PERMISSION)
        c = submit_expense_claim(claimant_member=reviewer, title="own", description="", amount=1, expense_date="2026-01-01")
        with self.assertRaises(DomainError):
            review_expense_claim(claim=c, reviewer_member=reviewer, decision="approved")

    def test_reject_without_reason_fails(self):
        reviewer = _make_finance_member("fin-reviewer-no", FINANCE_REVIEW_PERMISSION)
        c = self._submit()
        with self.assertRaises(DomainError):
            review_expense_claim(claim=c, reviewer_member=reviewer, decision="rejected", reason="")

    def test_invalid_review_decision_fails(self):
        reviewer = _make_finance_member("fin-reviewer-bad-decision", FINANCE_REVIEW_PERMISSION)
        c = self._submit()
        with self.assertRaises(DomainError):
            review_expense_claim(claim=c, reviewer_member=reviewer, decision="bad")

    def test_approve_creates_review_and_event(self):
        reviewer = _make_finance_member("fin-reviewer-ok", FINANCE_REVIEW_PERMISSION)
        c = self._submit(title="approve me", amount=100)
        review_expense_claim(claim=c, reviewer_member=reviewer, decision="approved")
        c.refresh_from_db()
        self.assertEqual(c.status, ExpenseClaim.Status.APPROVED)
        self.assertTrue(FinanceReview.objects.filter(claim=c).exists())
        self.assertTrue(Event.objects.filter(event_id__startswith=f"expense-claim-reviewed-{c.claim_id}-").exists())

    def test_cannot_review_after_final_decision(self):
        reviewer = _make_finance_member("fin-reviewer-final", FINANCE_REVIEW_PERMISSION)
        c = self._submit(title="final", amount=100)
        review_expense_claim(claim=c, reviewer_member=reviewer, decision="approved")
        with self.assertRaises(DomainError):
            review_expense_claim(claim=c, reviewer_member=reviewer, decision="approved")

    def test_non_payer_cannot_pay(self):
        c = self._submit()
        reviewer = _make_finance_member("fin-rev-pay", FINANCE_REVIEW_PERMISSION)
        review_expense_claim(claim=c, reviewer_member=reviewer, decision="approved")
        with self.assertRaises(DomainError):
            mark_expense_claim_paid(claim=c, payer_member=self.author)

    def test_claimant_cannot_pay_own(self):
        reviewer = _make_finance_member("fin-rev2", FINANCE_REVIEW_PERMISSION)
        payer = _make_finance_member("fin-pay-self", FINANCE_PAY_PERMISSION)
        c = submit_expense_claim(claimant_member=payer, title="self-pay", description="", amount=1, expense_date="2026-01-01")
        review_expense_claim(claim=c, reviewer_member=reviewer, decision="approved")
        with self.assertRaises(DomainError):
            mark_expense_claim_paid(claim=c, payer_member=payer)

    def test_only_approved_can_be_paid(self):
        reviewer = _make_finance_member("fin-rev3", FINANCE_REVIEW_PERMISSION)
        payer = _make_finance_member("fin-pay2", FINANCE_PAY_PERMISSION)
        c = self._submit(claimant_member=self.author)
        with self.assertRaises(DomainError):
            mark_expense_claim_paid(claim=c, payer_member=payer)

    def test_pay_creates_transaction_and_events(self):
        reviewer = _make_finance_member("fin-rev4", FINANCE_REVIEW_PERMISSION)
        payer = _make_finance_member("fin-pay3", FINANCE_PAY_PERMISSION)
        c = self._submit(title="pay-me", amount=999)
        review_expense_claim(claim=c, reviewer_member=reviewer, decision="approved")
        mark_expense_claim_paid(claim=c, payer_member=payer)
        c.refresh_from_db()
        self.assertEqual(c.status, ExpenseClaim.Status.PAID)
        txn = FinanceTransaction.objects.get(claim=c)
        self.assertTrue(Event.objects.filter(event_id__startswith=f"expense-claim-paid-{c.claim_id}-").exists())
        system_event = SystemEvent.objects.get(aggregate_id=txn.transaction_id)
        self.assertEqual(system_event.event_type, SystemEvent.EventType.EXPENSE_CLAIM_PAID)

    def test_finance_transaction_is_append_only(self):
        reviewer = _make_finance_member("fin-rev-append", FINANCE_REVIEW_PERMISSION)
        payer = _make_finance_member("fin-pay-append", FINANCE_PAY_PERMISSION)
        c = self._submit(title="append", amount=10)
        review_expense_claim(claim=c, reviewer_member=reviewer, decision="approved")
        txn = mark_expense_claim_paid(claim=c, payer_member=payer)
        txn.summary = "edited"
        with self.assertRaises(ValueError):
            txn.save()

    def test_withdraw_only_owner(self):
        c = self._submit()
        other = create_member("other-wd", display_name="其他")
        with self.assertRaises(DomainError):
            withdraw_expense_claim(claim=c, member=other)

    def test_withdraw_only_submitted(self):
        reviewer = _make_finance_member("fin-rev-wd", FINANCE_REVIEW_PERMISSION)
        c = self._submit(title="approved-wd")
        review_expense_claim(claim=c, reviewer_member=reviewer, decision="approved")
        with self.assertRaises(DomainError):
            withdraw_expense_claim(claim=c, member=self.author)

    def test_finance_role_requires_formal_member(self):
        basic = create_member("fin-basic-only")
        setup = ensure_finance_roles()
        with self.assertRaises(DomainError):
            create_role_assignment(member=basic, role=setup["review_role"])

    def test_ensure_finance_roles_creates_baseline_permissions_and_roles(self):
        setup = ensure_finance_roles()
        self.assertTrue(Permission.objects.filter(code=FINANCE_REVIEW_PERMISSION).exists())
        self.assertTrue(Permission.objects.filter(code=FINANCE_PAY_PERMISSION).exists())
        self.assertEqual(setup["review_role"].role_permissions.count(), 2)
        self.assertEqual(setup["pay_role"].role_permissions.count(), 2)

    def test_finance_event_semantic_summary(self):
        c = self._submit(title="语义财务", amount=42, category="ai_usage")
        event = Event.objects.get(event_id=f"expense-claim-submitted-{c.claim_id}")
        summary = public_event_semantic_summary(event)
        self.assertIn({"label": "事项", "value": "收到报销申请"}, summary)
        self.assertIn({"label": "标题", "value": "语义财务"}, summary)
        self.assertIn({"label": "金额", "value": "42.00 CNY"}, summary)


class FinanceViewTests(TestCase):

    def setUp(self):
        self.author = create_member("fin-view-author", display_name="视图作者")
        login_as_member(self.client, self.author)

    def test_claims_page_redirects_unauthenticated(self):
        self.client.logout()
        resp = self.client.get("/workspace/finance/claims/")
        self.assertEqual(resp.status_code, 302)

    def test_claims_page_shows_own_claim(self):
        submit_expense_claim(claimant_member=self.author, title="我的报销", description="", amount=100, expense_date="2026-01-01")
        resp = self.client.get("/workspace/finance/claims/")
        self.assertContains(resp, "我的报销")

    def test_other_member_cannot_view_claim_detail(self):
        claim = submit_expense_claim(
            claimant_member=create_member("fin-other-owner"),
            title="别人报销",
            description="",
            amount=100,
            expense_date="2026-01-01",
        )
        resp = self.client.get(f"/workspace/finance/claims/{claim.claim_id}/")
        self.assertEqual(resp.status_code, 403)

    def test_invalid_claim_form_does_not_create(self):
        before = ExpenseClaim.objects.count()
        resp = self.client.post("/workspace/finance/claims/new/", {
            "title": "坏金额",
            "amount": "-1",
            "currency": "CNY",
            "expense_date": "2026-01-01",
            "category": "server",
            "description": "",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ExpenseClaim.objects.count(), before)

    def test_public_finance_accessible(self):
        resp = self.client.get("/finance/")
        self.assertEqual(resp.status_code, 200)

    def test_public_finance_no_leak(self):
        resp = self.client.get("/finance/")
        content = resp.content.decode().lower()
        self.assertNotIn("email", content)
        self.assertNotIn("user_id", content)
        self.assertNotIn("member_id", content)
        self.assertNotIn("contact", content)
