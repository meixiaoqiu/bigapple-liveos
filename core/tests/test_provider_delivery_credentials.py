"""Tests for procurement/delivery workflow and provider_delivery_completed credentials."""

from __future__ import annotations

from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.credential_services import (
    credentials_for_member,
    ensure_builtin_credential_templates,
)
from core.exceptions import DomainError
from core.member_roles import ROLE_FORMAL_MEMBER
from core.models import (
    CredentialGrant,
    CredentialTemplate,
    Member,
    Resource,
    ResourceTransaction,
    SupplierQuote,
)
from core.procurement_services import (
    accept_resource_offer,
    mark_offer_paid_or_donated,
    record_offer_receipt,
    reject_resource_offer,
    submit_resource_offer,
)
from core.tests.helpers import create_member


class ProviderDeliveryCredentialTests(TestCase):
    """凭证模板和 zero_start 断言。"""

    def setUp(self):
        ensure_builtin_credential_templates()

    def test_template_created_idempotently(self):
        first = ensure_builtin_credential_templates()
        second = ensure_builtin_credential_templates()
        self.assertEqual(second, 0)
        t = CredentialTemplate.objects.get(code="provider_delivery_completed")
        self.assertEqual(t.name, "供给履约完成凭证")
        self.assertEqual(t.credential_type, CredentialTemplate.CredentialType.CERTIFICATE)
        self.assertEqual(t.visibility, CredentialTemplate.Visibility.PUBLIC)

    def test_template_public_metadata(self):
        t = CredentialTemplate.objects.get(code="provider_delivery_completed")
        meta = t.metadata or {}
        self.assertEqual(meta.get("category"), "procurement")
        self.assertEqual(meta.get("public_label"), "供给履约完成")
        self.assertTrue(meta.get("nft_ready"))

    def test_zero_start_creates_template_no_grants(self):
        """zero_start creates the credential template but no grants."""
        from live_os.demo_seed.zero_start import seed_zero_start

        seed_zero_start(founder_member_no="M-ZT-CRED", founder_display_name="凭证测试")
        self.assertTrue(
            CredentialTemplate.objects.filter(code="provider_delivery_completed").exists()
        )
        self.assertEqual(
            CredentialGrant.objects.filter(
                template__code="provider_delivery_completed",
            ).count(),
            0,
        )
        self.assertEqual(SupplierQuote.objects.count(), 0)
        self.assertEqual(ResourceTransaction.objects.count(), 0)


class ProcurementWorkflowTests(TestCase):
    """完整报价 → 采纳 → 验收 → 付款/捐赠 → 发凭证流程。"""

    def setUp(self):
        now = timezone.now()
        ensure_builtin_credential_templates()
        self.resource = Resource.objects.create(
            resource_id="res-proc-grain",
            resource_type=Resource.ResourceType.GRAIN,
            unit=Resource.Unit.KG,
            current_stock=Decimal("100"),
            daily_consumption_estimate=Decimal("0"),
            warning_threshold=Decimal("20"),
            loss_rate=Decimal("0"),
            replenishment_method=Resource.ReplenishmentMethod.PURCHASE,
            updated_at=now,
            rule_version="v1",
        )
        self.supplier = create_member("mem-supplier-1", role_name=ROLE_FORMAL_MEMBER)
        from core.tests.helpers import create_governance_admin_member
        self.governor = create_governance_admin_member("gov-proc-1")

    def _exec_proposal(self, quote):
        """Approve + execute auto-created PROCUREMENT_ACCEPTANCE proposal."""
        from core.models import ApprovalProposal
        from core.proposal_services import approve_proposal, execute_proposal

        prop = ApprovalProposal.objects.filter(
            target_type="supplier_quote", target_id=quote.quote_id,
        ).first()
        if prop and prop.status == ApprovalProposal.Status.SUBMITTED:
            approve_proposal(proposal=prop, approved_by=self.governor, role="governance")
            execute_proposal(proposal=prop, actor=self.governor)
            quote.refresh_from_db()

    # ── Quote submission ─────────────────────────────────────

    def test_submit_quote_creates_record(self):
        quote = submit_resource_offer(
            resource=self.resource,
            submitted_by=self.supplier,
            offer_type=SupplierQuote.OfferType.QUOTE,
            available_quantity=Decimal("50"),
            unit_price=Decimal("12.50"),
        )
        self.assertEqual(quote.offer_type, SupplierQuote.OfferType.QUOTE)
        self.assertEqual(quote.decision_status, SupplierQuote.DecisionStatus.SUBMITTED)
        self.assertEqual(quote.payment_status, SupplierQuote.PaymentStatus.PENDING)

    def test_submit_donation_has_not_required_payment(self):
        quote = submit_resource_offer(
            resource=self.resource,
            submitted_by=self.supplier,
            offer_type=SupplierQuote.OfferType.DONATION,
            available_quantity=Decimal("30"),
            unit_price=Decimal("0"),
        )
        self.assertEqual(quote.payment_status, SupplierQuote.PaymentStatus.NOT_REQUIRED)

    def test_submit_quote_zero_quantity_rejected(self):
        with self.assertRaises(DomainError):
            submit_resource_offer(
                resource=self.resource,
                submitted_by=self.supplier,
                offer_type=SupplierQuote.OfferType.QUOTE,
                available_quantity=Decimal("0"),
                unit_price=Decimal("10"),
            )

    def test_submit_quote_negative_quantity_rejected(self):
        with self.assertRaises(DomainError):
            submit_resource_offer(
                resource=self.resource,
                submitted_by=self.supplier,
                offer_type=SupplierQuote.OfferType.QUOTE,
                available_quantity=Decimal("-5"),
                unit_price=Decimal("10"),
            )

    def test_submit_quote_negative_price_rejected(self):
        with self.assertRaises(DomainError):
            submit_resource_offer(
                resource=self.resource,
                submitted_by=self.supplier,
                offer_type=SupplierQuote.OfferType.QUOTE,
                available_quantity=Decimal("10"),
                unit_price=Decimal("-1"),
            )

    # ── Fix 5: donation price validation ─────────────────────

    def test_submit_donation_negative_price_rejected(self):
        with self.assertRaises(DomainError):
            submit_resource_offer(
                resource=self.resource,
                submitted_by=self.supplier,
                offer_type=SupplierQuote.OfferType.DONATION,
                available_quantity=Decimal("10"),
                unit_price=Decimal("-1"),
            )

    def test_submit_donation_nonzero_price_rejected(self):
        with self.assertRaises(DomainError):
            submit_resource_offer(
                resource=self.resource,
                submitted_by=self.supplier,
                offer_type=SupplierQuote.OfferType.DONATION,
                available_quantity=Decimal("10"),
                unit_price=Decimal("5"),
            )

    def test_submit_donation_zero_price_ok(self):
        quote = submit_resource_offer(
            resource=self.resource,
            submitted_by=self.supplier,
            offer_type=SupplierQuote.OfferType.DONATION,
            available_quantity=Decimal("10"),
            unit_price=Decimal("0"),
        )
        self.assertEqual(quote.unit_price, Decimal("0"))

    # ── Accept / reject ───────────────────────────────────────

    def test_accept_quote(self):
        quote = submit_resource_offer(
            resource=self.resource,
            submitted_by=self.supplier,
            offer_type=SupplierQuote.OfferType.QUOTE,
            available_quantity=Decimal("20"),
            unit_price=Decimal("5"),
        )
        quote = accept_resource_offer(
            quote=quote,
            accepted_by=self.governor,
            decision_reason="价格合理。",
        )
        self.assertEqual(quote.decision_status, SupplierQuote.DecisionStatus.ACCEPTED)
        self.assertEqual(quote.accepted_by, self.governor)
        self.assertIsNotNone(quote.accepted_at)

    def test_reject_quote(self):
        quote = submit_resource_offer(
            resource=self.resource,
            submitted_by=self.supplier,
            offer_type=SupplierQuote.OfferType.QUOTE,
            available_quantity=Decimal("10"),
            unit_price=Decimal("999"),
        )
        quote = reject_resource_offer(
            quote=quote,
            rejected_by=self.governor,
            decision_reason="单价过高。",
        )
        self.assertEqual(quote.decision_status, SupplierQuote.DecisionStatus.REJECTED)
        self.assertEqual(quote.rejected_by, self.governor)

    def test_cannot_accept_twice(self):
        quote = submit_resource_offer(
            resource=self.resource,
            submitted_by=self.supplier,
            offer_type=SupplierQuote.OfferType.QUOTE,
            available_quantity=Decimal("10"),
            unit_price=Decimal("10"),
        )
        accept_resource_offer(quote=quote, accepted_by=self.governor)
        with self.assertRaises(DomainError):
            accept_resource_offer(quote=quote, accepted_by=self.governor)

    def test_cannot_accept_rejected_quote(self):
        quote = submit_resource_offer(
            resource=self.resource,
            submitted_by=self.supplier,
            offer_type=SupplierQuote.OfferType.QUOTE,
            available_quantity=Decimal("10"),
            unit_price=Decimal("10"),
        )
        reject_resource_offer(quote=quote, rejected_by=self.governor)
        with self.assertRaises(DomainError):
            accept_resource_offer(quote=quote, accepted_by=self.governor)

    # ── Receipt ───────────────────────────────────────────────

    def test_receipt_creates_resource_transaction(self):
        quote = submit_resource_offer(
            resource=self.resource,
            submitted_by=self.supplier,
            offer_type=SupplierQuote.OfferType.QUOTE,
            available_quantity=Decimal("30"),
            unit_price=Decimal("8"),
        )
        self._exec_proposal(quote)
        txn_before = ResourceTransaction.objects.count()

        quote, txn = record_offer_receipt(
            quote=quote,
            received_by=self.governor,
            receipt_status=SupplierQuote.ReceiptStatus.ACCEPTED,
            receipt_notes="验收合格。",
        )
        self.assertEqual(quote.receipt_status, SupplierQuote.ReceiptStatus.ACCEPTED)
        self.assertEqual(quote.received_by, self.governor)
        self.assertIsNotNone(quote.delivered_at)
        self.assertEqual(ResourceTransaction.objects.count(), txn_before + 1)
        self.assertIsNotNone(txn)
        self.assertEqual(txn.related_supplier_quote, quote)
        self.resource.refresh_from_db()
        self.assertEqual(self.resource.current_stock, Decimal("130"))

    def test_cannot_receipt_unaccepted_quote(self):
        quote = submit_resource_offer(
            resource=self.resource,
            submitted_by=self.supplier,
            offer_type=SupplierQuote.OfferType.QUOTE,
            available_quantity=Decimal("10"),
            unit_price=Decimal("10"),
        )
        with self.assertRaises(DomainError):
            record_offer_receipt(
                quote=quote,
                received_by=self.governor,
                receipt_status=SupplierQuote.ReceiptStatus.ACCEPTED,
            )

    def test_cannot_receipt_rejected_quote(self):
        quote = submit_resource_offer(
            resource=self.resource,
            submitted_by=self.supplier,
            offer_type=SupplierQuote.OfferType.QUOTE,
            available_quantity=Decimal("10"),
            unit_price=Decimal("10"),
        )
        reject_resource_offer(quote=quote, rejected_by=self.governor)
        with self.assertRaises(DomainError):
            record_offer_receipt(
                quote=quote,
                received_by=self.governor,
                receipt_status=SupplierQuote.ReceiptStatus.ACCEPTED,
            )

    # ── Fix 1: receipt_status=rejected does NOT create transaction ──

    def test_receipt_rejected_no_transaction_no_stock_change(self):
        quote = submit_resource_offer(
            resource=self.resource,
            submitted_by=self.supplier,
            offer_type=SupplierQuote.OfferType.QUOTE,
            available_quantity=Decimal("30"),
            unit_price=Decimal("8"),
        )
        self._exec_proposal(quote)
        txn_before = ResourceTransaction.objects.count()
        original_stock = self.resource.current_stock

        quote, txn = record_offer_receipt(
            quote=quote,
            received_by=self.governor,
            receipt_status=SupplierQuote.ReceiptStatus.REJECTED,
            receipt_notes="质量不合格。",
        )
        self.assertEqual(quote.receipt_status, SupplierQuote.ReceiptStatus.REJECTED)
        self.assertIsNone(txn)
        self.assertEqual(ResourceTransaction.objects.count(), txn_before)
        self.resource.refresh_from_db()
        self.assertEqual(self.resource.current_stock, original_stock)

    def test_rejected_receipt_cannot_be_marked_paid(self):
        quote = submit_resource_offer(
            resource=self.resource,
            submitted_by=self.supplier,
            offer_type=SupplierQuote.OfferType.QUOTE,
            available_quantity=Decimal("10"),
            unit_price=Decimal("5"),
        )
        self._exec_proposal(quote)
        record_offer_receipt(
            quote=quote,
            received_by=self.governor,
            receipt_status=SupplierQuote.ReceiptStatus.REJECTED,
        )
        with self.assertRaises(DomainError):
            mark_offer_paid_or_donated(quote=quote, actor=self.governor)

    # ── Fix 1: partial / pending receipt rejected ──

    def test_receipt_partial_raises_domain_error(self):
        quote = submit_resource_offer(
            resource=self.resource,
            submitted_by=self.supplier,
            offer_type=SupplierQuote.OfferType.QUOTE,
            available_quantity=Decimal("10"),
            unit_price=Decimal("5"),
        )
        self._exec_proposal(quote)
        with self.assertRaises(DomainError) as ctx:
            record_offer_receipt(
                quote=quote,
                received_by=self.governor,
                receipt_status=SupplierQuote.ReceiptStatus.PARTIAL,
            )
        self.assertIn("暂不支持", str(ctx.exception))

    def test_receipt_pending_raises_domain_error(self):
        quote = submit_resource_offer(
            resource=self.resource,
            submitted_by=self.supplier,
            offer_type=SupplierQuote.OfferType.QUOTE,
            available_quantity=Decimal("10"),
            unit_price=Decimal("5"),
        )
        self._exec_proposal(quote)
        with self.assertRaises(DomainError):
            record_offer_receipt(
                quote=quote,
                received_by=self.governor,
                receipt_status=SupplierQuote.ReceiptStatus.PENDING,
            )

    # ── Fix 2: repeat receipt rejected ────────────────────────

    def test_cannot_receipt_accepted_quote_twice(self):
        quote = submit_resource_offer(
            resource=self.resource,
            submitted_by=self.supplier,
            offer_type=SupplierQuote.OfferType.QUOTE,
            available_quantity=Decimal("10"),
            unit_price=Decimal("5"),
        )
        self._exec_proposal(quote)
        record_offer_receipt(
            quote=quote,
            received_by=self.governor,
            receipt_status=SupplierQuote.ReceiptStatus.ACCEPTED,
        )
        txn_count = ResourceTransaction.objects.count()
        self.resource.refresh_from_db()
        stock_after_first = self.resource.current_stock
        self.assertEqual(stock_after_first, Decimal("110"))
        with self.assertRaises(DomainError):
            record_offer_receipt(
                quote=quote,
                received_by=self.governor,
                receipt_status=SupplierQuote.ReceiptStatus.ACCEPTED,
            )
        self.assertEqual(ResourceTransaction.objects.count(), txn_count)
        self.resource.refresh_from_db()
        self.assertEqual(self.resource.current_stock, stock_after_first)

    def test_cannot_receipt_rejected_quote_twice(self):
        quote = submit_resource_offer(
            resource=self.resource,
            submitted_by=self.supplier,
            offer_type=SupplierQuote.OfferType.QUOTE,
            available_quantity=Decimal("10"),
            unit_price=Decimal("5"),
        )
        self._exec_proposal(quote)
        record_offer_receipt(
            quote=quote,
            received_by=self.governor,
            receipt_status=SupplierQuote.ReceiptStatus.REJECTED,
        )
        with self.assertRaises(DomainError):
            record_offer_receipt(
                quote=quote,
                received_by=self.governor,
                receipt_status=SupplierQuote.ReceiptStatus.REJECTED,
            )

    # ── Payment / donation + credential ───────────────────────

    def _full_quote_workflow(self, offer_type="quote", unit_price=Decimal("10")) -> SupplierQuote:
        """Helper: submit → proposal → accept → receipt → mark paid/donated."""
        quote = submit_resource_offer(
            resource=self.resource,
            submitted_by=self.supplier,
            offer_type=offer_type,
            available_quantity=Decimal("20"),
            unit_price=unit_price,
        )
        self._exec_proposal(quote)
        quote, _txn = record_offer_receipt(
            quote=quote,
            received_by=self.governor,
            receipt_status=SupplierQuote.ReceiptStatus.ACCEPTED,
        )
        quote = mark_offer_paid_or_donated(quote=quote, actor=self.governor)
        return quote

    def test_full_quote_workflow_issues_credential(self):
        quote = self._full_quote_workflow()
        self.assertEqual(quote.payment_status, SupplierQuote.PaymentStatus.PAID)
        self.assertIsNotNone(quote.paid_at)
        self.assertIsNotNone(quote.performance_credential)
        credential = quote.performance_credential
        self.assertEqual(credential.template.code, "provider_delivery_completed")
        self.assertEqual(credential.member, self.supplier)
        self.assertIn("quote_id", credential.metadata)
        self.assertEqual(credential.metadata["quote_id"], quote.quote_id)

    def test_full_donation_workflow_issues_credential(self):
        quote = self._full_quote_workflow(
            offer_type=SupplierQuote.OfferType.DONATION,
            unit_price=Decimal("0"),
        )
        self.assertEqual(quote.payment_status, SupplierQuote.PaymentStatus.NOT_REQUIRED)
        self.assertIsNotNone(quote.performance_credential)

    def test_quote_requires_payment_before_credential(self):
        """非捐赠必须付款后才能发凭证。"""
        quote = submit_resource_offer(
            resource=self.resource,
            submitted_by=self.supplier,
            offer_type=SupplierQuote.OfferType.QUOTE,
            available_quantity=Decimal("10"),
            unit_price=Decimal("5"),
        )
        self._exec_proposal(quote)
        quote, _txn = record_offer_receipt(
            quote=quote,
            received_by=self.governor,
            receipt_status=SupplierQuote.ReceiptStatus.ACCEPTED,
        )
        # Before payment — no credential
        self.assertIsNone(quote.performance_credential_id)
        # After payment — credential issued
        quote = mark_offer_paid_or_donated(quote=quote, actor=self.governor)
        self.assertIsNotNone(quote.performance_credential)

    def test_donation_does_not_require_payment(self):
        """捐赠完成不要求付款。"""
        quote = submit_resource_offer(
            resource=self.resource,
            submitted_by=self.supplier,
            offer_type=SupplierQuote.OfferType.DONATION,
            available_quantity=Decimal("10"),
            unit_price=Decimal("0"),
        )
        self._exec_proposal(quote)
        quote, _txn = record_offer_receipt(
            quote=quote,
            received_by=self.governor,
            receipt_status=SupplierQuote.ReceiptStatus.ACCEPTED,
        )
        quote = mark_offer_paid_or_donated(quote=quote, actor=self.governor)
        self.assertEqual(quote.payment_status, SupplierQuote.PaymentStatus.NOT_REQUIRED)
        self.assertIsNotNone(quote.performance_credential)

    def test_cannot_mark_paid_before_receipt(self):
        """未验收入库不能付款完成后发凭证。"""
        quote = submit_resource_offer(
            resource=self.resource,
            submitted_by=self.supplier,
            offer_type=SupplierQuote.OfferType.QUOTE,
            available_quantity=Decimal("10"),
            unit_price=Decimal("5"),
        )
        self._exec_proposal(quote)
        with self.assertRaises(DomainError):
            mark_offer_paid_or_donated(quote=quote, actor=self.governor)

    def test_repeat_completion_does_not_duplicate_credential(self):
        """重复完成不重复发凭证。"""
        quote = self._full_quote_workflow()
        cred_count_before = CredentialGrant.objects.filter(
            template__code="provider_delivery_completed",
            member=self.supplier,
        ).count()
        # fulfilled quote cannot be marked again
        with self.assertRaises(DomainError):
            mark_offer_paid_or_donated(quote=quote, actor=self.governor)
        self.assertEqual(
            CredentialGrant.objects.filter(
                template__code="provider_delivery_completed",
                member=self.supplier,
            ).count(),
            cred_count_before,
        )

    def test_credential_is_public(self):
        """provider_delivery_completed 凭证公开可查。"""
        self._full_quote_workflow()
        creds = credentials_for_member(self.supplier)
        codes = {c["template_code"] for c in creds}
        self.assertIn("provider_delivery_completed", codes)

    def test_credential_does_not_grant_workspace_access(self):
        """凭证不会授予 workspace 权限。"""
        self._full_quote_workflow()
        from core.access import is_governance_principal
        self.assertFalse(is_governance_principal(self.supplier))

    def test_receipt_triggers_resource_transaction_with_quote_link(self):
        """验收入库产生的 ResourceTransaction.related_supplier_quote 指向报价。"""
        quote = submit_resource_offer(
            resource=self.resource,
            submitted_by=self.supplier,
            offer_type=SupplierQuote.OfferType.QUOTE,
            available_quantity=Decimal("25"),
            unit_price=Decimal("9"),
        )
        self._exec_proposal(quote)
        _quote, txn = record_offer_receipt(
            quote=quote,
            received_by=self.governor,
            receipt_status=SupplierQuote.ReceiptStatus.ACCEPTED,
        )
        self.assertIsNotNone(txn)
        self.assertEqual(txn.related_supplier_quote, quote)
        self.assertEqual(txn.quantity_delta, Decimal("25"))

    # ── Fix 3: returned txn is from record_resource_adjustment ──

    def test_receipt_txn_is_from_return_value_not_latest_query(self):
        """返回的 transaction 来自 record_resource_adjustment 返回值。"""
        quote = submit_resource_offer(
            resource=self.resource,
            submitted_by=self.supplier,
            offer_type=SupplierQuote.OfferType.QUOTE,
            available_quantity=Decimal("10"),
            unit_price=Decimal("5"),
        )
        self._exec_proposal(quote)
        _quote, txn = record_offer_receipt(
            quote=quote,
            received_by=self.governor,
            receipt_status=SupplierQuote.ReceiptStatus.ACCEPTED,
        )
        self.assertIsNotNone(txn)
        self.assertEqual(txn.resource, self.resource)
        self.assertEqual(txn.transaction_type, ResourceTransaction.TransactionType.INBOUND)

    # ── Fix 6: legacy quote submitted_by=None ──────────────────

    def test_legacy_quote_null_submitter_cannot_be_fulfilled(self):
        """legacy 报价 (submitted_by=None) mark 时抛 DomainError，不创建凭证。"""
        legacy = SupplierQuote.objects.create(
            quote_id="quote-legacy-001",
            resource=self.resource,
            submitted_by=None,
            offer_type=SupplierQuote.OfferType.QUOTE,
            unit_price=Decimal("10"),
            available_quantity=Decimal("5"),
            status=SupplierQuote.Status.ACTIVE,
            decision_status=SupplierQuote.DecisionStatus.ACCEPTED,
            receipt_status=SupplierQuote.ReceiptStatus.ACCEPTED,
            payment_status=SupplierQuote.PaymentStatus.PENDING,
            created_at=timezone.now(),
            updated_at=timezone.now(),
        )
        cred_before = CredentialGrant.objects.count()
        with self.assertRaises(DomainError) as ctx:
            mark_offer_paid_or_donated(quote=legacy, actor=self.governor)
        self.assertIn("缺失提交人", str(ctx.exception))
        self.assertEqual(CredentialGrant.objects.count(), cred_before)

    # ── Fix 7: decision_status=fulfilled ─────────────────────

    def test_quote_fulfilled_sets_decision_status(self):
        """报价付款完成后 decision_status=fulfilled。"""
        quote = self._full_quote_workflow()
        self.assertEqual(quote.decision_status, SupplierQuote.DecisionStatus.FULFILLED)

    def test_donation_fulfilled_sets_decision_status(self):
        """捐赠完成后 decision_status=fulfilled。"""
        quote = self._full_quote_workflow(
            offer_type=SupplierQuote.OfferType.DONATION,
            unit_price=Decimal("0"),
        )
        self.assertEqual(quote.decision_status, SupplierQuote.DecisionStatus.FULFILLED)

    def test_fulfilled_quote_cannot_be_marked_again(self):
        """已 fulfilled 的报价再次 mark 应拒绝。"""
        quote = self._full_quote_workflow()
        with self.assertRaises(DomainError):
            mark_offer_paid_or_donated(quote=quote, actor=self.governor)
