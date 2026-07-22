"""Tests for workspace procurement management views."""

from __future__ import annotations

from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone

from core.credential_services import ensure_builtin_credential_templates
from core.member_roles import ROLE_FORMAL_MEMBER
from core.models import (
    ApprovalProposal,
    CredentialGrant,
    Resource,
    ResourceTransaction,
    SupplierQuote,
)
from core.procurement_services import (
    mark_offer_paid_or_donated,
    record_offer_receipt,
    submit_resource_offer,
)
from core.tests.helpers import (
    create_governance_admin_member,
    create_member,
    login_as_member,
    grant_governance_admin_role,
)


FIXED_WORLD_SETTINGS = {"WORLD_ROUTER_FORCE_ID": "wt-proc-test"}


@override_settings(**FIXED_WORLD_SETTINGS)
class WorkspaceProcurementTests(TestCase):
    """工作台采购管理测试。"""

    def setUp(self):
        now = timezone.now()
        ensure_builtin_credential_templates()
        self.resource = Resource.objects.create(
            resource_id="res-ws-proc",
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
        self.governor = create_governance_admin_member("gov-proc-1")
        login_as_member(self.client, self.governor)

        self.supplier = create_member("sup-proc-1", role_name=ROLE_FORMAL_MEMBER)
        self.regular = create_member("reg-proc-1", role_name=ROLE_FORMAL_MEMBER)

    def _submit_quote(
        self,
        offer_type="quote",
        unit_price=Decimal("10"),
        *,
        execute_acceptance_proposal: bool = True,
    ) -> SupplierQuote:
        quote = submit_resource_offer(
            resource=self.resource,
            submitted_by=self.supplier,
            offer_type=offer_type,
            available_quantity=Decimal("30"),
            unit_price=unit_price,
        )
        prop = ApprovalProposal.objects.filter(
            target_type="supplier_quote", target_id=quote.quote_id,
        ).first()
        if prop and execute_acceptance_proposal:
            from core.proposal_services import approve_proposal, execute_proposal
            approve_proposal(proposal=prop, approved_by=self.governor, role="governance")
            execute_proposal(proposal=prop, actor=self.governor)
            quote.refresh_from_db()
        return quote

    # ── permission ─────────────────────────────────────────────

    def test_governance_can_access_procurement_page(self):
        response = self.client.get("/workspace/procurement/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "采购与供给管理")

    def test_regular_member_cannot_access_procurement_page(self):
        login_as_member(self.client, self.regular)
        response = self.client.get("/workspace/procurement/")
        self.assertEqual(response.status_code, 403)

    # ── accept / reject ────────────────────────────────────────

    def test_governance_can_create_acceptance_proposal(self):
        quote = self._submit_quote(execute_acceptance_proposal=False)
        response = self.client.post(
            f"/workspace/procurement/{quote.quote_id}/create-proposal/",
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "采纳提案")

    def test_governance_can_reject_submitted_quote_via_proposal(self):
        quote = self._submit_quote(execute_acceptance_proposal=False)
        proposal = ApprovalProposal.objects.get(
            target_type="supplier_quote",
            target_id=quote.quote_id,
            proposal_type=ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE,
        )
        response = self.client.post(
            f"/workspace/approval-proposals/{proposal.proposal_id}/reject/",
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        quote.refresh_from_db()
        self.assertEqual(quote.decision_status, SupplierQuote.DecisionStatus.REJECTED)

    # ── receipt ────────────────────────────────────────────────

    def test_receipt_accepted_creates_transaction(self):
        quote = self._submit_quote()
        txn_before = ResourceTransaction.objects.count()
        response = self.client.post(
            f"/workspace/procurement/{quote.quote_id}/receipt/",
            {"receipt_status": "accepted"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "验收通过")
        quote.refresh_from_db()
        self.assertEqual(quote.receipt_status, SupplierQuote.ReceiptStatus.ACCEPTED)
        self.assertEqual(ResourceTransaction.objects.count(), txn_before + 1)

    def test_receipt_rejected_no_transaction(self):
        quote = self._submit_quote()
        txn_before = ResourceTransaction.objects.count()
        response = self.client.post(
            f"/workspace/procurement/{quote.quote_id}/receipt/",
            {"receipt_status": "rejected"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        quote.refresh_from_db()
        self.assertEqual(quote.receipt_status, SupplierQuote.ReceiptStatus.REJECTED)
        self.assertEqual(ResourceTransaction.objects.count(), txn_before)

    # ── complete / credential ──────────────────────────────────

    def test_complete_quote_issues_credential(self):
        quote = self._submit_quote()
        record_offer_receipt(
            quote=quote,
            received_by=self.governor,
            receipt_status=SupplierQuote.ReceiptStatus.ACCEPTED,
        )
        cred_before = CredentialGrant.objects.filter(
            template__code="provider_delivery_completed",
        ).count()
        response = self.client.post(
            f"/workspace/procurement/{quote.quote_id}/complete/",
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "履约凭证已发放")
        quote.refresh_from_db()
        self.assertEqual(quote.decision_status, SupplierQuote.DecisionStatus.FULFILLED)
        self.assertEqual(
            CredentialGrant.objects.filter(
                template__code="provider_delivery_completed",
            ).count(),
            cred_before + 1,
        )

    def test_complete_donation_issues_credential(self):
        quote = self._submit_quote(offer_type=SupplierQuote.OfferType.DONATION, unit_price=Decimal("0"))
        record_offer_receipt(
            quote=quote,
            received_by=self.governor,
            receipt_status=SupplierQuote.ReceiptStatus.ACCEPTED,
        )
        response = self.client.post(
            f"/workspace/procurement/{quote.quote_id}/complete/",
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        quote.refresh_from_db()
        self.assertEqual(quote.decision_status, SupplierQuote.DecisionStatus.FULFILLED)
        self.assertIsNotNone(quote.performance_credential)

    def test_fulfilled_quote_cannot_be_completed_again(self):
        quote = self._submit_quote()
        record_offer_receipt(
            quote=quote,
            received_by=self.governor,
            receipt_status=SupplierQuote.ReceiptStatus.ACCEPTED,
        )
        mark_offer_paid_or_donated(quote=quote, actor=self.governor)
        cred_count = CredentialGrant.objects.filter(
            template__code="provider_delivery_completed",
        ).count()
        response = self.client.post(
            f"/workspace/procurement/{quote.quote_id}/complete/",
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            CredentialGrant.objects.filter(
                template__code="provider_delivery_completed",
            ).count(),
            cred_count,
        )

    # ── no metadata / operator leak ────────────────────────────

    def test_procurement_page_no_metadata_leak(self):
        self._submit_quote()
        response = self.client.get("/workspace/procurement/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn("metadata", content)
        self.assertNotIn("operator", content)
