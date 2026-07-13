from __future__ import annotations

from django.test import TestCase, override_settings

from core.models import Member
from core.tests.helpers import create_member, login_as_member


FIXED_REALWORLD_SETTINGS = {
    "ROOT_URLCONF": "live_os.urls_real",
    "SITE_ROLE": "real",
    "SITE_FIXED_WORLD": True,
    "SITE_WORLD_ID": "realworld",
    "SITE_WORLD_TYPE": "real",
    "SITE_WORLD_DATABASE_ALIAS": "default",
    "SITE_WORLD_DATABASE_NAME": "test",
    "WORLD_DATABASE_ROUTING_ENABLED": False,
    "DEFAULT_WORLD_DATABASE_ALIAS": "default",
    "DATABASE_ROUTERS": [],
}


class SplitSiteEntrypointTests(TestCase):
    @override_settings(**FIXED_REALWORLD_SETTINGS)
    def test_fixed_world_public_application_url_does_not_require_world_prefix(self) -> None:
        response = self.client.get("/apply/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.wsgi_request.world_id, "realworld")
        self.assertContains(response, "成员报名")

    @override_settings(**FIXED_REALWORLD_SETTINGS)
    def test_legacy_member_application_url_is_removed(self) -> None:
        response = self.client.get("/apply/member/")

        self.assertEqual(response.status_code, 404)

    @override_settings(**FIXED_REALWORLD_SETTINGS)
    def test_fixed_world_workspace_uses_root_links(self) -> None:
        member = create_member(member_no="mem-site-member", status=Member.Status.ACTIVE)
        login_as_member(self.client, member)

        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.wsgi_request.world_id, "realworld")
        self.assertContains(response, "/logout/")
        self.assertNotContains(response, "/world/")

    @override_settings(**FIXED_REALWORLD_SETTINGS)
    def test_fixed_world_site_does_not_expose_live_admin(self) -> None:
        response = self.client.get("/live-admin/")

        self.assertEqual(response.status_code, 404)

    @override_settings(**FIXED_REALWORLD_SETTINGS)
    def test_fixed_world_site_does_not_expose_django_admin(self) -> None:
        response = self.client.get("/admin/")

        self.assertEqual(response.status_code, 404)
