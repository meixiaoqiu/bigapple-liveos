"""Tests for workspace work-item dashboard."""

from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone

from core.credential_services import ensure_builtin_credential_templates
from core.member_roles import ROLE_FORMAL_MEMBER
from core.models import (
    ApprovalProposal,
    Resource,
    SupplierQuote,
)
from core.procurement_services import submit_resource_offer
from core.proposal_services import (
    approve_proposal,
    create_approval_proposal,
    execute_proposal,
)
from core.tests.helpers import (
    create_governance_admin_member,
    create_member,
    login_as_member,
)

from workspace.work_item_context import build_member_work_items

FIXED_WORLD_SETTINGS = {"WORLD_ROUTER_FORCE_ID": "wt-wi-test"}


@override_settings(**FIXED_WORLD_SETTINGS)
class WorkItemContextTests(TestCase):
    """Unit tests for build_member_work_items."""

    def setUp(self):
        ensure_builtin_credential_templates()
        now = timezone.now()
        self.resource = Resource.objects.create(
            resource_id="res-wi-grain",
            resource_type=Resource.ResourceType.GRAIN,
            unit=Resource.Unit.KG,
            current_stock=Decimal("100"),
            daily_consumption_estimate=Decimal("0"),
            warning_threshold=Decimal("10"),
            loss_rate=Decimal("0"),
            replenishment_method=Resource.ReplenishmentMethod.PURCHASE,
            updated_at=now,
            rule_version="v1",
        )
        self.governor = create_governance_admin_member("gov-wi-1")
        self.supplier = create_member("sup-wi-1", role_name=ROLE_FORMAL_MEMBER)
        self.regular = create_member("reg-wi-1", role_name=ROLE_FORMAL_MEMBER)

    def test_governance_sees_pending_approval_proposal(self):
        create_approval_proposal(
            proposal_type=ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE,
            dedupe_key="test:wi:1",
            title="Test approval",
            submitted_by=self.governor,
            approval_tier=ApprovalProposal.Tier.SINGLE,
        )
        items = build_member_work_items(self.governor)
        self.assertGreater(len(items["approval_pending"]), 0)

    def test_governance_sees_approved_execute_item(self):
        p = create_approval_proposal(
            proposal_type=ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE,
            dedupe_key="test:wi:2",
            title="Test execute",
            submitted_by=self.governor,
            approval_tier=ApprovalProposal.Tier.SINGLE,
        )
        approve_proposal(proposal=p, approved_by=self.governor, role="governance")
        items = build_member_work_items(self.governor)
        self.assertGreater(len(items["execute_pending"]), 0)

    def test_accepted_quote_ready_shows_receipt_item(self):
        quote = submit_resource_offer(
            resource=self.resource,
            submitted_by=self.supplier,
            offer_type=SupplierQuote.OfferType.QUOTE,
            available_quantity=Decimal("10"),
            unit_price=Decimal("3"),
        )
        p = ApprovalProposal.objects.get(
            proposal_type=ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE,
            target_type="supplier_quote",
            target_id=quote.quote_id,
        )
        approve_proposal(proposal=p, approved_by=self.governor, role="governance")
        execute_proposal(proposal=p, actor=self.governor)
        items = build_member_work_items(self.governor)
        self.assertGreater(len(items["receipt_pending"]), 0)

    def test_regular_member_sees_no_governance_items(self):
        create_approval_proposal(
            proposal_type=ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE,
            dedupe_key="test:wi:3",
            title="Hidden",
            submitted_by=self.governor,
            approval_tier=ApprovalProposal.Tier.SINGLE,
        )
        items = build_member_work_items(self.regular)
        self.assertEqual(items["total_pending"], 0)

    def test_work_items_no_metadata_leak(self):
        create_approval_proposal(
            proposal_type=ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE,
            dedupe_key="test:wi:4",
            title="Test",
            submitted_by=self.governor,
        )
        items = build_member_work_items(self.governor)
        for item in items["approval_pending"]:
            self.assertNotIn("metadata", str(item))
            self.assertNotIn("operator", str(item))


@override_settings(**FIXED_WORLD_SETTINGS)
class WorkspaceDashboardTests(TestCase):
    """Integration tests for /workspace/ dashboard."""

    def setUp(self):
        ensure_builtin_credential_templates()
        now = timezone.now()
        self.resource = Resource.objects.create(
            resource_id="res-ws-home",
            resource_type=Resource.ResourceType.GRAIN,
            unit=Resource.Unit.KG,
            current_stock=Decimal("100"),
            daily_consumption_estimate=Decimal("0"),
            warning_threshold=Decimal("10"),
            loss_rate=Decimal("0"),
            replenishment_method=Resource.ReplenishmentMethod.PURCHASE,
            updated_at=now,
            rule_version="v1",
        )
        self.governor = create_governance_admin_member("gov-home-1")

    def test_dashboard_shows_pending_items_when_exist(self):
        login_as_member(self.client, self.governor)
        create_approval_proposal(
            proposal_type=ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE,
            dedupe_key="test:home:1",
            title="Pending approval",
            submitted_by=self.governor,
            approval_tier=ApprovalProposal.Tier.SINGLE,
        )
        response = self.client.get("/workspace/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "待处理事项")

    def test_dashboard_ok_without_pending_items(self):
        login_as_member(self.client, self.governor)
        response = self.client.get("/workspace/")
        self.assertEqual(response.status_code, 200)

    def test_dashboard_links_point_to_pages(self):
        login_as_member(self.client, self.governor)
        create_approval_proposal(
            proposal_type=ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE,
            dedupe_key="test:home:2",
            title="Link test",
            submitted_by=self.governor,
        )
        response = self.client.get("/workspace/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "待处理事项")

    def test_no_metadata_on_homepage(self):
        login_as_member(self.client, self.governor)
        response = self.client.get("/workspace/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn("metadata", content)
