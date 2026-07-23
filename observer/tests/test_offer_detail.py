"""Tests for public offer detail / timeline page."""

from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone

from core.credential_services import ensure_builtin_credential_templates
from core.member_roles import ROLE_FORMAL_MEMBER
from core.models import Resource, SupplierQuote
from core.procurement_services import submit_resource_offer
from core.tests.helpers import create_member, create_governance_admin_member, login_as_member

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


@override_settings(**FIXED_WORLD_SETTINGS)
class DonationVisibilityTests(TestCase):

    def setUp(self):
        from core.credential_services import ensure_builtin_credential_templates
        ensure_builtin_credential_templates()
        now = timezone.now()
        self.resource = Resource.objects.create(
            resource_id="res-dv-1", resource_type=Resource.ResourceType.GRAIN,
            unit=Resource.Unit.KG, current_stock=Decimal("100"),
            daily_consumption_estimate=Decimal("0"), warning_threshold=Decimal("10"),
            loss_rate=Decimal("0"), replenishment_method=Resource.ReplenishmentMethod.PURCHASE,
            updated_at=now, rule_version="v1",
        )
        self.member = create_member("mem-dv-1", role_name=ROLE_FORMAL_MEMBER)

    def test_quote_anonymous_rejected(self):
        login_as_member(self.client, self.member)
        qb = SupplierQuote.objects.count()
        resp = self.client.post("/resources/res-dv-1/offers/new/", {
            "offer_type": "quote", "available_quantity": "10", "unit_price": "5",
            "public_visibility": "anonymous",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(SupplierQuote.objects.count(), qb)

    def test_donation_anonymous_succeeds(self):
        login_as_member(self.client, self.member)
        resp = self.client.post("/resources/res-dv-1/offers/new/", {
            "offer_type": "donation", "available_quantity": "10", "unit_price": "0",
            "public_visibility": "anonymous",
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        q = SupplierQuote.objects.filter(submitted_by=self.member).first()
        self.assertIsNotNone(q)
        self.assertEqual(q.public_visibility, SupplierQuote.PublicVisibility.ANONYMOUS)

    def test_anonymous_donation_no_member_info_in_list(self):
        login_as_member(self.client, self.member)
        self.client.post("/resources/res-dv-1/offers/new/", {
            "offer_type": "donation", "available_quantity": "5", "unit_price": "0",
            "public_visibility": "anonymous",
        })
        # View as a different member to avoid nav-bar self-identification
        viewer = create_member("mem-dv-2", role_name=ROLE_FORMAL_MEMBER)
        login_as_member(self.client, viewer)
        resp = self.client.get("/resources/res-dv-1/offers/")
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertNotIn("mem-dv-1", content)

    def test_public_display_name_shown(self):
        login_as_member(self.client, self.member)
        self.client.post("/resources/res-dv-1/offers/new/", {
            "offer_type": "donation", "available_quantity": "5", "unit_price": "0",
            "public_visibility": "anonymous", "public_display_name": "热心市民",
        })
        viewer = create_member("mem-dv-3", role_name=ROLE_FORMAL_MEMBER)
        login_as_member(self.client, viewer)
        resp = self.client.get("/resources/res-dv-1/offers/")
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn("热心市民", content)
        self.assertNotIn("mem-dv-1", content)


@override_settings(**FIXED_WORLD_SETTINGS)
class ChallengeUITests(TestCase):

    def setUp(self):
        from core.credential_services import ensure_builtin_credential_templates
        ensure_builtin_credential_templates()
        now = timezone.now()
        self.resource = Resource.objects.create(
            resource_id="res-ch-ui-1", resource_type=Resource.ResourceType.GRAIN,
            unit=Resource.Unit.KG, current_stock=Decimal("100"),
            daily_consumption_estimate=Decimal("0"), warning_threshold=Decimal("10"),
            loss_rate=Decimal("0"), replenishment_method=Resource.ReplenishmentMethod.PURCHASE,
            updated_at=now, rule_version="v1",
        )
        self.member = create_member("mem-ch-1", role_name=ROLE_FORMAL_MEMBER)
        self.governor = create_governance_admin_member("gov-ch-1")

    def _submit_quote(self):
        login_as_member(self.client, self.member)
        self.client.post("/resources/res-ch-ui-1/offers/new/", {
            "offer_type": "quote", "available_quantity": "10", "unit_price": "20", "lead_time_days": "3",
        })
        return SupplierQuote.objects.filter(submitted_by=self.member).first()

    def test_anonymous_cannot_submit_challenge(self):
        quote = self._submit_quote()
        # POST as anonymous should redirect to login (302)
        resp = self.client.post(
            f"/resources/res-ch-ui-1/offers/{quote.quote_id}/challenges/new/",
            {"challenge_type": "question", "public_reason": "x"},
        )
        self.assertIn(resp.status_code, [302, 403])

    def test_member_can_get_challenge_form(self):
        quote = self._submit_quote()
        login_as_member(self.client, create_member("mem-ch-2", role_name=ROLE_FORMAL_MEMBER))
        resp = self.client.get(f"/resources/res-ch-ui-1/offers/{quote.quote_id}/challenges/new/")
        self.assertEqual(resp.status_code, 200)

    def test_member_can_submit_question_challenge(self):
        from core.models import ProcurementChallenge
        quote = self._submit_quote()
        login_as_member(self.client, create_member("mem-ch-3", role_name=ROLE_FORMAL_MEMBER))
        cb = ProcurementChallenge.objects.count()
        resp = self.client.post(
            f"/resources/res-ch-ui-1/offers/{quote.quote_id}/challenges/new/",
            {"challenge_type": "question", "public_reason": "quality?"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ProcurementChallenge.objects.count(), cb + 1)

    def test_lower_price_must_be_less(self):
        quote = self._submit_quote()
        login_as_member(self.client, create_member("mem-ch-4", role_name=ROLE_FORMAL_MEMBER))
        resp = self.client.post(
            f"/resources/res-ch-ui-1/offers/{quote.quote_id}/challenges/new/",
            {"challenge_type": "lower_price", "public_reason": "too high",
             "proposed_unit_price": "30"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_detail_page_shows_challenges(self):
        quote = self._submit_quote()
        login_as_member(self.client, create_member("mem-ch-5", role_name=ROLE_FORMAL_MEMBER))
        self.client.post(
            f"/resources/res-ch-ui-1/offers/{quote.quote_id}/challenges/new/",
            {"challenge_type": "question", "public_reason": "test challenge"},
        )
        resp = self.client.get(f"/resources/res-ch-ui-1/offers/{quote.quote_id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "test challenge")

    def test_detail_page_no_metadata_leak(self):
        quote = self._submit_quote()
        login_as_member(self.client, create_member("mem-ch-6", role_name=ROLE_FORMAL_MEMBER))
        self.client.post(
            f"/resources/res-ch-ui-1/offers/{quote.quote_id}/challenges/new/",
            {"challenge_type": "question", "public_reason": "ok"},
        )
        resp = self.client.get(f"/resources/res-ch-ui-1/offers/{quote.quote_id}/")
        self.assertEqual(resp.status_code, 200)
        c = resp.content.decode()
        self.assertNotIn("metadata", c)
        self.assertNotIn("payload_json", c)
