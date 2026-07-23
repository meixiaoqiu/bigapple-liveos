"""Tests for workspace approval proposal views."""

from __future__ import annotations

from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone

from core.member_roles import ROLE_FORMAL_MEMBER
from core.models import (
    ApprovalDecision,
    ApprovalProposal,
    Resource,
    SupplierQuote,
    SystemEvent,
)
from core.procurement_services import submit_resource_offer
from core.proposal_services import (
    create_approval_proposal,
    proposal_is_approved,
)
from core.tests.helpers import (
    create_governance_admin_member,
    create_member,
    login_as_member,
)


FIXED_WORLD_SETTINGS = {"WORLD_ROUTER_FORCE_ID": "wt-apv-test"}


@override_settings(**FIXED_WORLD_SETTINGS)
class ApprovalProposalViewsTests(TestCase):

    def setUp(self):
        self.governor = create_governance_admin_member("gov-apv-1")
        login_as_member(self.client, self.governor)
        self.finance = create_member("fin-apv-1", role_name=ROLE_FORMAL_MEMBER)
        self.regular = create_member("reg-apv-1", role_name=ROLE_FORMAL_MEMBER)

        now = timezone.now()
        self.resource = Resource.objects.create(
            resource_id="res-apv-test",
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
        self.supplier = create_member("sup-apv-1", role_name=ROLE_FORMAL_MEMBER)

    _proposal_counter = 0

    def _create_test_proposal(self, tier="single", ptype=None) -> ApprovalProposal:
        self._proposal_counter += 1
        ptype = ptype or ApprovalProposal.ProposalType.INVENTORY_ADJUSTMENT
        return create_approval_proposal(
            proposal_type=ptype,
            dedupe_key=f"test:approval:{self._proposal_counter}",
            title=f"Test proposal {tier}",
            submitted_by=self.governor,
            target_type="",
            target_id="",
            approval_tier=tier,
        )

    # ── permissions ──────────────────────────────────────────

    def test_regular_member_403(self):
        login_as_member(self.client, self.regular)
        response = self.client.get("/workspace/proposals/")
        self.assertEqual(response.status_code, 403)

    def test_governance_can_access(self):
        response = self.client.get("/workspace/proposals/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "待处理提案")

    def test_regular_cannot_approve(self):
        login_as_member(self.client, self.regular)
        p = self._create_test_proposal()
        response = self.client.post(
            f"/workspace/approval-proposals/{p.proposal_id}/approve/",
        )
        self.assertEqual(response.status_code, 403)

    def test_regular_cannot_reject(self):
        login_as_member(self.client, self.regular)
        p = self._create_test_proposal()
        response = self.client.post(
            f"/workspace/approval-proposals/{p.proposal_id}/reject/",
        )
        self.assertEqual(response.status_code, 403)

    def test_regular_cannot_execute(self):
        login_as_member(self.client, self.regular)
        p = self._create_test_proposal()
        response = self.client.post(
            f"/workspace/approval-proposals/{p.proposal_id}/execute/",
        )
        self.assertEqual(response.status_code, 403)

    # ── approve ──────────────────────────────────────────────

    def test_governance_can_approve_single(self):
        p = self._create_test_proposal("single")
        response = self.client.post(
            f"/workspace/approval-proposals/{p.proposal_id}/approve/",
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.status, ApprovalProposal.Status.APPROVED)
        self.assertTrue(
            ApprovalDecision.objects.filter(
                proposal=p, approver=self.governor, role="governance",
                decision=ApprovalDecision.Decision.APPROVED,
            ).exists()
        )

    def test_approve_creates_event(self):
        p = self._create_test_proposal("single")
        evt_before = SystemEvent.objects.filter(
            event_type=SystemEvent.EventType.APPROVAL_PROPOSAL_APPROVED,
        ).count()
        self.client.post(
            f"/workspace/approval-proposals/{p.proposal_id}/approve/",
        )
        self.assertEqual(
            SystemEvent.objects.filter(
                event_type=SystemEvent.EventType.APPROVAL_PROPOSAL_APPROVED,
            ).count(),
            evt_before + 1,
        )

    def test_cannot_approve_same_proposal_twice(self):
        p = self._create_test_proposal("single")
        self.client.post(
            f"/workspace/approval-proposals/{p.proposal_id}/approve/",
        )
        response = self.client.post(
            f"/workspace/approval-proposals/{p.proposal_id}/approve/",
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            ApprovalDecision.objects.filter(
                proposal=p, approver=self.governor,
                decision=ApprovalDecision.Decision.APPROVED,
            ).count(),
            1,
        )

    # ── standard tier ────────────────────────────────────────

    def test_standard_governance_approve_still_missing_finance(self):
        p = self._create_test_proposal(
            "standard", ptype=ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE,
        )
        # Attach a dummy quote so the proposal is valid
        SupplierQuote.objects.create(
            quote_id=p.target_id or "quote-std-001",
            resource=self.resource,
            offer_type=SupplierQuote.OfferType.QUOTE,
            unit_price=Decimal("10"),
            available_quantity=Decimal("10"),
            status=SupplierQuote.Status.ACTIVE,
            decision_status=SupplierQuote.DecisionStatus.SUBMITTED,
            created_at=timezone.now(),
            updated_at=timezone.now(),
        )
        self.client.post(
            f"/workspace/approval-proposals/{p.proposal_id}/approve/",
        )
        p.refresh_from_db()
        self.assertEqual(p.status, ApprovalProposal.Status.SUBMITTED)

    # ── reject ───────────────────────────────────────────────

    def test_reject_proposal(self):
        p = self._create_test_proposal("single")
        response = self.client.post(
            f"/workspace/approval-proposals/{p.proposal_id}/reject/",
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.status, ApprovalProposal.Status.REJECTED)

    def test_rejected_cannot_execute(self):
        p = self._create_test_proposal("single")
        self.client.post(
            f"/workspace/approval-proposals/{p.proposal_id}/reject/",
        )
        response = self.client.post(
            f"/workspace/approval-proposals/{p.proposal_id}/execute/",
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.status, ApprovalProposal.Status.REJECTED)

    # ── execute ──────────────────────────────────────────────

    def test_execute_approved_single(self):
        p = self._create_test_proposal("single")
        self.client.post(
            f"/workspace/approval-proposals/{p.proposal_id}/approve/",
        )
        response = self.client.post(
            f"/workspace/approval-proposals/{p.proposal_id}/execute/",
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.status, ApprovalProposal.Status.EXECUTED)

    def test_cannot_execute_unapproved(self):
        p = self._create_test_proposal("single")
        response = self.client.post(
            f"/workspace/approval-proposals/{p.proposal_id}/execute/",
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.status, ApprovalProposal.Status.SUBMITTED)

    # ── procurement integration ──────────────────────────────

    def test_execute_procurement_acceptance_accepts_quote(self):
        quote = submit_resource_offer(
            resource=self.resource,
            submitted_by=self.supplier,
            offer_type=SupplierQuote.OfferType.QUOTE,
            available_quantity=Decimal("10"),
            unit_price=Decimal("5"),
        )
        # Auto-created proposal from submit_resource_offer
        p = ApprovalProposal.objects.get(
            proposal_type=ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE,
            target_type="supplier_quote", target_id=quote.quote_id,
        )
        self.client.post(
            f"/workspace/approval-proposals/{p.proposal_id}/approve/",
        )
        self.client.post(
            f"/workspace/approval-proposals/{p.proposal_id}/execute/",
        )
        quote.refresh_from_db()
        self.assertEqual(quote.decision_status, SupplierQuote.DecisionStatus.ACCEPTED)

    # ── page rendering ───────────────────────────────────────

    def test_page_shows_pending_proposal(self):
        self._create_test_proposal("single")
        response = self.client.get("/workspace/proposals/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "待我处理")

    def test_page_no_metadata_leak(self):
        self._create_test_proposal("single")
        response = self.client.get("/workspace/proposals/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn("metadata", content)

    def test_workspace_index_shows_proposals_link(self):
        response = self.client.get("/workspace/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "待处理提案")

    # ── procurement page proposal integration ────────────────

    def test_procurement_page_shows_auto_proposal_link_not_direct_decision(self):
        submit_resource_offer(
            resource=self.resource,
            submitted_by=self.supplier,
            offer_type=SupplierQuote.OfferType.QUOTE,
            available_quantity=Decimal("10"),
            unit_price=Decimal("5"),
        )
        response = self.client.get("/workspace/procurement/?status=submitted")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("查看提案", content)
        self.assertNotIn("workspace-procurement-accept", content)
        self.assertNotIn("workspace-procurement-reject", content)

    def test_procurement_page_shows_proposal_status_when_exists(self):
        quote = submit_resource_offer(
            resource=self.resource,
            submitted_by=self.supplier,
            offer_type=SupplierQuote.OfferType.QUOTE,
            available_quantity=Decimal("10"),
            unit_price=Decimal("5"),
        )
        # Auto-proposal already exists from submit_resource_offer
        response = self.client.get("/workspace/procurement/?status=submitted")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "已提交")

    # ── old proposal routes still work ───────────────────────

    def test_old_proposal_routes_not_broken(self):
        """Old voting proposal routes should still be accessible patterns."""
        response = self.client.get("/workspace/procurement/")
        self.assertEqual(response.status_code, 200)
