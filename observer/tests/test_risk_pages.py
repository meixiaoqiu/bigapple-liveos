"""Tests for public risk pages."""

from django.test import TestCase, override_settings

from core.credential_services import ensure_builtin_credential_templates
from core.models import RiskAlert
from core.risk_services import ensure_builtin_risk_rules


FIXED_WORLD_SETTINGS = {"WORLD_ROUTER_FORCE_ID": "wt-risk-test"}


@override_settings(**FIXED_WORLD_SETTINGS)
class PublicRiskPageTests(TestCase):

    def setUp(self):
        ensure_builtin_credential_templates()
        ensure_builtin_risk_rules()

    def _create_alert(self, **kw):
        defaults = {
            "alert_id": f"risk-test-{kw.get('title','x')}",
            "domain": "resource",
            "severity": "high",
            "visibility": "public",
            "status": "active",
            "title": kw.pop("title", "Test Alert"),
            "summary": "Test",
            "dedupe_key": f"test:{kw.pop('title','x')}:{id(kw)}",
            "source_type": "resource",
            "source_id": "res-test",
        }
        defaults.update(kw)
        return RiskAlert.objects.create(**defaults)

    def test_risks_page_returns_200(self):
        resp = self.client.get("/risks/")
        self.assertEqual(resp.status_code, 200)

    def test_risks_page_no_500_with_alerts(self):
        self._create_alert(title="Stock Low", severity="critical")
        resp = self.client.get("/risks/")
        self.assertEqual(resp.status_code, 200)

    def test_risks_page_shows_public_active_alert(self):
        self._create_alert(title="Public Alert", visibility="public", status="active")
        resp = self.client.get("/risks/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Public Alert")

    def test_risks_page_hides_internal_alert(self):
        self._create_alert(title="Internal Alert", visibility="internal", status="active",
                           alert_id="risk-int-1", dedupe_key="test:int:1")
        resp = self.client.get("/risks/")
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Internal Alert")

    def test_risks_page_no_metadata_leak(self):
        self._create_alert(title="Leak Test", metadata={"secret": "x"})
        resp = self.client.get("/risks/")
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertNotIn("metadata", content)
        self.assertNotIn("payload_json", content)

    def test_homepage_shows_risk_section(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "高风险")
        self.assertContains(resp, "查看全部风险")

    def test_homepage_has_risk_link(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "/risks/")

    def test_risk_partial_returns_200(self):
        resp = self.client.get("/dashboard/partials/risk/")
        self.assertIn(resp.status_code, [200, 302])

    def test_risks_page_empty_state(self):
        RiskAlert.objects.all().delete()
        resp = self.client.get("/risks/")
        self.assertEqual(resp.status_code, 200)
