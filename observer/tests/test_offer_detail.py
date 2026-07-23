"""Tests for public offer detail / timeline page."""

from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone

from core.credential_services import ensure_builtin_credential_templates
from core.member_roles import ROLE_FORMAL_MEMBER
from core.models import Resource, SupplierQuote
from core.procurement_services import submit_resource_offer
from core.tests.helpers import create_member, login_as_member

FIXED_WORLD_SETTINGS = {"WORLD_ROUTER_FORCE_ID": "wt-od-test"}


@override_settings(**FIXED_WORLD_SETTINGS)
class OfferDetailPageTests(TestCase):

    def setUp(self):
        ensure_builtin_credential_templates()
        now = timezone.now()
        self.resource = Resource.objects.create(
            resource_id="res-od-grain",
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
        self.member = create_member("mem-od-1", role_name=ROLE_FORMAL_MEMBER)

    def test_anonymous_can_view_offer_detail(self):
        login_as_member(self.client, self.member)
        self.client.post(
            "/resources/res-od-grain/offers/new/",
            {"offer_type": "quote", "available_quantity": "5", "unit_price": "7", "lead_time_days": "1"},
        )
        quote = SupplierQuote.objects.first()
        response = self.client.get(f"/resources/res-od-grain/offers/{quote.quote_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "报价详情")

    def test_nonexistent_quote_returns_404(self):
        response = self.client.get("/resources/res-od-grain/offers/nonexistent-999/")
        self.assertEqual(response.status_code, 404)

    def test_quote_wrong_resource_returns_404(self):
        login_as_member(self.client, self.member)
        self.client.post(
            "/resources/res-od-grain/offers/new/",
            {"offer_type": "quote", "available_quantity": "5", "unit_price": "7"},
        )
        quote = SupplierQuote.objects.first()
        # Create a different resource
        Resource.objects.create(
            resource_id="res-od-other",
            resource_type=Resource.ResourceType.WATER,
            unit=Resource.Unit.LITER,
            current_stock=Decimal("50"),
            daily_consumption_estimate=Decimal("0"),
            warning_threshold=Decimal("5"),
            loss_rate=Decimal("0"),
            replenishment_method=Resource.ReplenishmentMethod.PURCHASE,
            updated_at=timezone.now(),
            rule_version="v1",
        )
        response = self.client.get(f"/resources/res-od-other/offers/{quote.quote_id}/")
        self.assertEqual(response.status_code, 404)

    def test_offer_detail_shows_core_fields(self):
        login_as_member(self.client, self.member)
        self.client.post(
            "/resources/res-od-grain/offers/new/",
            {"offer_type": "quote", "available_quantity": "8", "unit_price": "12", "lead_time_days": "3"},
        )
        quote = SupplierQuote.objects.first()
        response = self.client.get(f"/resources/res-od-grain/offers/{quote.quote_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "报价详情")
        self.assertContains(response, str(quote.quote_id))

    def test_offer_detail_shows_timeline(self):
        login_as_member(self.client, self.member)
        self.client.post(
            "/resources/res-od-grain/offers/new/",
            {"offer_type": "quote", "available_quantity": "5", "unit_price": "3", "lead_time_days": "1"},
        )
        quote = SupplierQuote.objects.first()
        response = self.client.get(f"/resources/res-od-grain/offers/{quote.quote_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "时间线")

    def test_offer_detail_no_metadata_leak(self):
        login_as_member(self.client, self.member)
        self.client.post(
            "/resources/res-od-grain/offers/new/",
            {"offer_type": "quote", "available_quantity": "5", "unit_price": "3"},
        )
        quote = SupplierQuote.objects.first()
        response = self.client.get(f"/resources/res-od-grain/offers/{quote.quote_id}/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn("metadata", content)
        self.assertNotIn("operator", content)
        self.assertNotIn("payload_json", content)


@override_settings(**FIXED_WORLD_SETTINGS)
class AntiSpamTests(TestCase):
    """Tests for daily offer rate limit."""

    def setUp(self):
        ensure_builtin_credential_templates()
        now = timezone.now()
        self.resource = Resource.objects.create(
            resource_id="res-as-1",
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
        self.resource2 = Resource.objects.create(
            resource_id="res-as-2",
            resource_type=Resource.ResourceType.WATER,
            unit=Resource.Unit.LITER,
            current_stock=Decimal("50"),
            daily_consumption_estimate=Decimal("0"),
            warning_threshold=Decimal("5"),
            loss_rate=Decimal("0"),
            replenishment_method=Resource.ReplenishmentMethod.PURCHASE,
            updated_at=now,
            rule_version="v1",
        )
        self.member = create_member("mem-as-1", role_name=ROLE_FORMAL_MEMBER)
        login_as_member(self.client, self.member)

    def _submit(self, resource_id="res-as-1"):
        return self.client.post(
            f"/resources/{resource_id}/offers/new/",
            {"offer_type": "quote", "available_quantity": "10", "unit_price": "5", "lead_time_days": "1"},
            follow=True,
        )

    def test_five_offers_allowed(self):
        for i in range(5):
            resp = self._submit()
            self.assertEqual(resp.status_code, 200)
        self.assertEqual(SupplierQuote.objects.filter(resource=self.resource).count(), 5)

    def test_sixth_offer_rejected(self):
        for _ in range(5):
            self._submit()
        quote_before = SupplierQuote.objects.count()
        resp = self.client.post(
            "/resources/res-as-1/offers/new/",
            {"offer_type": "quote", "available_quantity": "10", "unit_price": "5"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(SupplierQuote.objects.count(), quote_before)

    def test_different_resource_no_limit(self):
        for _ in range(5):
            self._submit("res-as-1")
        # Submit to different resource — should work
        resp = self._submit("res-as-2")
        self.assertEqual(resp.status_code, 200)

    def test_different_member_no_limit(self):
        for _ in range(5):
            self._submit()
        member2 = create_member("mem-as-2", role_name=ROLE_FORMAL_MEMBER)
        login_as_member(self.client, member2)
        resp = self._submit()
        self.assertEqual(resp.status_code, 200)

    def test_closed_resource_rejected(self):
        self.resource.accepts_offers = False
        self.resource.save()
        quote_before = SupplierQuote.objects.count()
        resp = self.client.post(
            "/resources/res-as-1/offers/new/",
            {"offer_type": "quote", "available_quantity": "10", "unit_price": "5"},
        )
        self.assertIn(resp.status_code, [400, 403])
        self.assertEqual(SupplierQuote.objects.count(), quote_before)
