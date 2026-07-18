from __future__ import annotations

from django.contrib.auth import SESSION_KEY, get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import Member
from core.tests.helpers import create_governance_admin_member, create_member, login_as_member
from worlds.models import WorldRegistry
from worlds.views import SESSION_WORLD_DATABASE_ALIAS, SESSION_WORLD_ID


class WorldRouteTests(TestCase):
    def test_default_realworld_registry_exists(self) -> None:
        world = WorldRegistry.objects.get(world_id="realworld")

        self.assertEqual(world.world_type, WorldRegistry.WorldType.REAL)
        self.assertEqual(world.database_alias, "realworld")
        self.assertEqual(world.status, WorldRegistry.Status.ACTIVE)

        simulation = WorldRegistry.objects.get(world_id="simulation0001")
        self.assertEqual(simulation.world_type, WorldRegistry.WorldType.SIMULATION)
        self.assertEqual(simulation.database_alias, "simulation0001")

    def test_world_prefixed_live_admin_route_is_removed(self) -> None:
        response = self.client.get("/world/realworld/live-admin/")

        self.assertEqual(response.status_code, 404)

    def test_world_prefixed_member_route_is_removed(self) -> None:
        response = self.client.get("/world/realworld/member/")

        self.assertEqual(response.status_code, 404)

    def test_realworld_live_admin_route_is_not_exposed(self) -> None:
        operator = create_governance_admin_member(
            member_no="member-admin-0001",
            status=Member.Status.ACTIVE,
            batch_id="batch-opening",
            joined_simulation_day=1,
            credit_floor=-500,
            profile={"display_name": "governance operator"},
            created_at=timezone.now(),
        )
        login_as_member(self.client, operator)

        response = self.client.get("/live-admin/")

        self.assertEqual(response.status_code, 404)

    def test_realworld_workspace_route_binds_world_context(self) -> None:
        member = create_member(
            member_no="mem-0001",
            status=Member.Status.ACTIVE,
            batch_id="batch-opening",
            joined_simulation_day=1,
            credit_floor=-100,
            profile={"display_name": "member one"},
            created_at=timezone.now(),
        )
        login_as_member(self.client, member)

        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.wsgi_request.world_id, "realworld")
        self.assertEqual(response.wsgi_request.world.database_alias, "realworld")

    def test_legacy_member_route_is_not_exposed(self) -> None:
        response = self.client.get("/member/")

        self.assertEqual(response.status_code, 404)

    def test_unknown_world_route_returns_404(self) -> None:
        response = self.client.get("/world/missing-world/live-admin/")

        self.assertEqual(response.status_code, 404)

    def test_world_login_records_session_world(self) -> None:
        user = get_user_model().objects.create_user(username="mem-0001", password="test-password")
        create_member(
            member_no="mem-0001",
            user=user,
            status=Member.Status.ACTIVE,
            batch_id="batch-opening",
            joined_simulation_day=1,
            credit_floor=-100,
            profile={"display_name": "member one"},
            created_at=timezone.now(),
        )

        response = self.client.post(
            "/login/",
            {"world_id": "realworld", "username": "mem-0001", "password": "test-password"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/workspace/")
        self.assertEqual(self.client.session[SESSION_WORLD_ID], "realworld")

    def test_world_login_redirects_governance_member_to_workspace(self) -> None:
        user = get_user_model().objects.create_user(username="member-admin-0001", password="test-password")
        create_governance_admin_member(
            member_no="member-admin-0001",
            user=user,
            status=Member.Status.ACTIVE,
            batch_id="batch-opening",
            joined_simulation_day=1,
            credit_floor=-500,
            profile={"display_name": "governance operator"},
            created_at=timezone.now(),
        )

        response = self.client.post(
            "/login/",
            {"world_id": "realworld", "username": "member-admin-0001", "password": "test-password"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/workspace/")
        self.assertEqual(self.client.session[SESSION_WORLD_ID], "realworld")

    def test_world_login_can_authenticate_against_simulation_world(self) -> None:
        user = get_user_model().objects.create_user(username="mem-0001", password="test-password")
        create_member(
            member_no="mem-0001",
            user=user,
            status=Member.Status.ACTIVE,
            batch_id="batch-opening",
            joined_simulation_day=1,
            credit_floor=-100,
            profile={"display_name": "member one"},
            created_at=timezone.now(),
        )

        response = self.client.post(
            "/login/",
            {"world_id": "simulation0001", "username": "mem-0001", "password": "test-password"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/workspace/")
        self.assertEqual(self.client.session[SESSION_WORLD_ID], "simulation0001")
        self.assertEqual(self.client.session[SESSION_WORLD_DATABASE_ALIAS], "simulation0001")

    @override_settings(SITE_FIXED_WORLD=True, SITE_WORLD_ID="simulation0001")
    def test_fixed_world_login_defaults_to_configured_world(self) -> None:
        response = self.client.get("/login/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"]["world_id"].value(), "simulation0001")
        self.assertContains(response, 'data-theme="corporate"')
        self.assertContains(response, 'type="hidden" name="world_id" value="simulation0001"')
        self.assertContains(response, "input input-bordered w-full")
        self.assertContains(response, "btn btn-primary w-full")

    def test_world_logout_returns_to_login_root(self) -> None:
        user = get_user_model().objects.create_user(username="mem-0001", password="test-password")
        self.client.force_login(user)
        session = self.client.session
        session[SESSION_WORLD_ID] = "simulation0001"
        session.save()

        response = self.client.post("/logout/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/login/")
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_world_logout_rejects_get_without_ending_session(self) -> None:
        user = get_user_model().objects.create_user(username="mem-logout-get", password="test-password")
        self.client.force_login(user)
        session = self.client.session
        session[SESSION_WORLD_ID] = "realworld"
        session.save()

        response = self.client.get("/logout/")

        self.assertEqual(response.status_code, 405)
        self.assertIn(SESSION_KEY, self.client.session)

    def test_world_prefixed_logout_route_is_removed(self) -> None:
        user = get_user_model().objects.create_user(username="mem-0001", password="test-password")
        self.client.force_login(user)
        session = self.client.session
        session[SESSION_WORLD_ID] = "realworld"
        session.save()

        response = self.client.post("/world/simulation0001/logout/")

        self.assertEqual(response.status_code, 404)

    @override_settings(SITE_FIXED_WORLD=True, SITE_WORLD_ID="simulation0001")
    def test_world_session_does_not_cross_to_another_world(self) -> None:
        member = create_member(
            member_no="mem-0001",
            status=Member.Status.ACTIVE,
            batch_id="batch-opening",
            joined_simulation_day=1,
            credit_floor=-100,
            profile={"display_name": "member one"},
            created_at=timezone.now(),
        )
        login_as_member(self.client, member)
        session = self.client.session
        session[SESSION_WORLD_ID] = "realworld"
        session.save()

        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertContains(response, "登录")
        self.assertContains(response, "注册")
