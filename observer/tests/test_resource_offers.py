"""Tests for public resource offer pages."""

from __future__ import annotations

from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone

from core.credential_services import ensure_builtin_credential_templates
from core.member_roles import ROLE_FORMAL_MEMBER
from core.models import Resource, SupplierQuote
from core.tests.helpers import create_member, login_as_member


FIXED_WORLD_SETTINGS = {"WORLD_ROUTER_FORCE_ID": "wt-offer-test"}


@override_settings(**FIXED_WORLD_SETTINGS)
class PublicResourceOffersTests(TestCase):
    """公开报价页测试。"""

    def setUp(self):
        ensure_builtin_credential_templates()
        now = timezone.now()
        self.resource = Resource.objects.create(
            resource_id="res-offer-1",
            resource_type=Resource.ResourceType.GRAIN,
            unit=Resource.Unit.KG,
            current_stock=Decimal("100"),
            warning_threshold=Decimal("50"),
            daily_consumption_estimate=Decimal("0"),
            loss_rate=Decimal("0"),
            replenishment_method=Resource.ReplenishmentMethod.PURCHASE,
            updated_at=now,
            rule_version="v1",
        )
        self.member = create_member("mem-offer-1", role_name=ROLE_FORMAL_MEMBER)

    def test_anonymous_can_view_offers_page(self):
        response = self.client.get("/resources/res-offer-1/offers/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "res-offer-1")

    def test_anonymous_cannot_submit_offer_redirects_to_login(self):
        response = self.client.get("/resources/res-offer-1/offers/new/")
        self.assertIn(response.status_code, {302, 403})

    def test_member_can_access_offer_new_page(self):
        login_as_member(self.client, self.member)
        response = self.client.get("/resources/res-offer-1/offers/new/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "提交报价")

    def test_member_can_submit_quote(self):
        login_as_member(self.client, self.member)
        response = self.client.post(
            "/resources/res-offer-1/offers/new/",
            {
                "offer_type": "quote",
                "available_quantity": "50",
                "unit_price": "10.5",
                "currency": "CNY",
                "lead_time_days": "3",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "报价已提交")
        quote = SupplierQuote.objects.filter(submitted_by=self.member).first()
        self.assertIsNotNone(quote)
        self.assertEqual(quote.submitted_by, self.member)
        self.assertIsNone(quote.partner_application)

    def test_member_can_submit_donation(self):
        login_as_member(self.client, self.member)
        response = self.client.post(
            "/resources/res-offer-1/offers/new/",
            {
                "offer_type": "donation",
                "available_quantity": "20",
                "unit_price": "0",
                "lead_time_days": "1",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "报价已提交")
        quote = SupplierQuote.objects.filter(
            submitted_by=self.member, offer_type=SupplierQuote.OfferType.DONATION,
        ).first()
        self.assertIsNotNone(quote)
        self.assertEqual(quote.unit_price, Decimal("0"))

    def test_donation_nonzero_price_rejected(self):
        login_as_member(self.client, self.member)
        response = self.client.post(
            "/resources/res-offer-1/offers/new/",
            {
                "offer_type": "donation",
                "available_quantity": "20",
                "unit_price": "10",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("捐赠单价必须为 0", response.content.decode())

    def test_offers_page_no_metadata_exposure(self):
        response = self.client.get("/resources/res-offer-1/offers/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn("metadata", content)
        self.assertNotIn("operator", content)

    def test_offers_page_shows_public_summary(self):
        login_as_member(self.client, self.member)
        self.client.post(
            "/resources/res-offer-1/offers/new/",
            {"offer_type": "quote", "available_quantity": "30", "unit_price": "8", "lead_time_days": "2"},
        )
        response = self.client.get("/resources/res-offer-1/offers/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "已提交")

    def test_resource_page_has_offer_button(self):
        response = self.client.get("/resources/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "报价")

    def test_submit_quote_auto_creates_proposal(self):
        """提交报价后自动创建 ApprovalProposal。"""
        from core.models import ApprovalProposal

        login_as_member(self.client, self.member)
        self.client.post(
            "/resources/res-offer-1/offers/new/",
            {"offer_type": "quote", "available_quantity": "30", "unit_price": "8", "lead_time_days": "2"},
        )
        quote = SupplierQuote.objects.filter(submitted_by=self.member).first()
        self.assertIsNotNone(quote)
        prop = ApprovalProposal.objects.filter(
            target_type="supplier_quote",
            target_id=quote.quote_id,
            proposal_type=ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE,
        ).first()
        self.assertIsNotNone(prop)

    def test_submit_donation_auto_creates_proposal(self):
        from core.models import ApprovalProposal

        login_as_member(self.client, self.member)
        self.client.post(
            "/resources/res-offer-1/offers/new/",
            {"offer_type": "donation", "available_quantity": "10", "unit_price": "0", "lead_time_days": "1"},
        )
        quote = SupplierQuote.objects.filter(
            submitted_by=self.member, offer_type=SupplierQuote.OfferType.DONATION,
        ).first()
        self.assertIsNotNone(quote)
        prop = ApprovalProposal.objects.filter(
            target_type="supplier_quote",
            target_id=quote.quote_id,
        ).first()
        self.assertIsNotNone(prop)

    def test_submit_with_accepts_offers_false_rejected(self):
        """accepts_offers=False 时提交被拒绝。"""
        self.resource.accepts_offers = False
        self.resource.save()
        login_as_member(self.client, self.member)
        response = self.client.post(
            "/resources/res-offer-1/offers/new/",
            {"offer_type": "quote", "available_quantity": "10", "unit_price": "5"},
        )
        self.assertEqual(response.status_code, 403)

    def test_closed_resource_page_no_offer_button(self):
        """accepts_offers=False 时资源页不显示报价入口。"""
        self.resource.accepts_offers = False
        self.resource.save()
        # Create another resource so there's something to show
        response = self.client.get("/resources/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("offers/", response.content.decode())

    def test_resource_page_shows_offer_summary(self):
        login_as_member(self.client, self.member)
        self.client.post(
            "/resources/res-offer-1/offers/new/",
            {"offer_type": "quote", "available_quantity": "30", "unit_price": "8", "lead_time_days": "2"},
        )
        response = self.client.get("/resources/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1 条报价")


@override_settings(**FIXED_WORLD_SETTINGS)
class PublicResourcesPageTests(TestCase):
    """公开资源页增强测试。"""

    def setUp(self):
        now = timezone.now()
        for i in range(3):
            Resource.objects.create(
                resource_id=f"res-pub-{i}",
                resource_type=Resource.ResourceType.MATERIAL,
                unit=Resource.Unit.COUNT,
                current_stock=Decimal("50"),
                warning_threshold=Decimal("20"),
                daily_consumption_estimate=Decimal("0"),
                loss_rate=Decimal("0"),
                replenishment_method=Resource.ReplenishmentMethod.PURCHASE,
                updated_at=now,
                rule_version="v1",
            )

    def test_anonymous_can_view_resources(self):
        response = self.client.get("/resources/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "全部资源库存")
