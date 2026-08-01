from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from core.access import member_can_maintain, user_can_maintain, user_has_permission
from core.governance_setup import BASE_MAINTENANCE_PERMISSIONS, MAINTENANCE_VIEW_ADMIN_PERMISSION
from core.member_roles import ROLE_DELIBERATOR, ROLE_COVENANTER
from core.role_catalog import ROLE_CATALOG_ORGANIZATION_NAME, ROLE_MAINTAINER
from core.models import Organization, Permission, Role, RoleAssignment, RolePermission
from core.role_assignment_services import create_role_assignment
from core.tests.helpers import create_member


class GovernanceAccessBridgeTests(TestCase):
    def create_user(self, username: str):
        return get_user_model().objects.create_user(username=username, password="test-password")

    def create_maintenance_role_permission(self, user, permission_code=MAINTENANCE_VIEW_ADMIN_PERMISSION):
        organization = Organization.objects.create(
            name=f"Governance Bridge {user.username}",
        )
        role = Role.objects.create(organization=organization, name="Bridge Admin")
        permission, _created = Permission.objects.get_or_create(
            code=permission_code,
            defaults={
                "name": "Governance view",
                "category": "governance",
            },
        )
        member = create_member(user.username, role_name=ROLE_COVENANTER, user=user, display_name=user.username)
        assignment = create_role_assignment(member=member, role=role)
        RolePermission.objects.create(role=role, permission=permission, scope="global")
        return member, assignment, permission

    def test_deliberator_duty_without_role_permission_is_denied(self):
        member = create_member(
            "member-admin-role",
            role_name=ROLE_DELIBERATOR,
            profile={"display_name": "member-admin-role"},
            created_at=timezone.now(),
            skip_role_validation=True,
        )
        user = self.create_user(member.member_no)

        self.assertFalse(user_has_permission(user, MAINTENANCE_VIEW_ADMIN_PERMISSION))
        self.assertFalse(user_can_maintain(user))

    def test_staff_without_governance_permission_is_denied(self):
        user = self.create_user("staff-without-governance")
        user.is_staff = True
        user.save(update_fields=["is_staff"])
        create_member(user.username, user=user, display_name=user.username)

        self.assertFalse(user_has_permission(user, MAINTENANCE_VIEW_ADMIN_PERMISSION))
        self.assertFalse(user_can_maintain(user))

    def test_superuser_without_governance_permission_is_denied(self):
        user = self.create_user("superuser-without-governance")
        user.is_staff = True
        user.is_superuser = True
        user.save(update_fields=["is_staff", "is_superuser"])

        self.assertFalse(user_has_permission(user, MAINTENANCE_VIEW_ADMIN_PERMISSION))
        self.assertFalse(user_can_maintain(user))

    def test_role_permission_allows_maintenance_access_without_deliberator_duty(self):
        user = self.create_user("new-governance-user")
        self.create_maintenance_role_permission(user)

        self.assertTrue(user_has_permission(user, MAINTENANCE_VIEW_ADMIN_PERMISSION))
        self.assertTrue(user_can_maintain(user))

    @override_settings(
        BIG_APPLE_AUTHORIZATION_BACKEND="openfga",
        OPENFGA_SIM_STORE_ID="store-id",
        OPENFGA_SIM_AUTHORIZATION_MODEL_ID="model-id",
        OPENFGA_SIM_PLATFORM_OBJECT="platform:sim",
    )
    def test_governance_access_bridge_denies_when_openfga_denies(self):
        user = self.create_user("openfga-denied-governance-user")
        member, _assignment, _permission = self.create_maintenance_role_permission(user)

        with patch("core.authorization_services.OpenFGAClient") as client_class:
            client_class.return_value.check.return_value = False

            self.assertFalse(user_has_permission(user, MAINTENANCE_VIEW_ADMIN_PERMISSION))
            self.assertFalse(member_can_maintain(member))

        client_class.return_value.check.assert_any_call(
            store_id="store-id",
            authorization_model_id="model-id",
            user=f"member:{member.pk}",
            relation="holder",
            object_=f"guarded_permission:{MAINTENANCE_VIEW_ADMIN_PERMISSION}",
        )

    def test_member_principal_can_use_role_permission(self):
        member = create_member(
            "member-with-role-permission",
            role_name=ROLE_COVENANTER,
            profile={"display_name": "member-with-role-permission"},
        )
        organization = Organization.objects.create(
            name="Member Principal Governance",
        )
        role = Role.objects.create(organization=organization, name="Member Principal Admin")
        permission, _created = Permission.objects.get_or_create(
            code=MAINTENANCE_VIEW_ADMIN_PERMISSION,
            defaults={
                "name": "Governance view",
                "category": "governance",
            },
        )
        create_role_assignment(member=member, role=role)
        RolePermission.objects.create(role=role, permission=permission, scope="global")

        self.assertTrue(member_can_maintain(member))

    def test_user_without_maintainer_member_role_or_role_permission_is_denied(self):
        user = self.create_user("plain-user")
        create_member(user.username, profile={"display_name": user.username})

        self.assertFalse(user_has_permission(user, MAINTENANCE_VIEW_ADMIN_PERMISSION))
        self.assertFalse(user_can_maintain(user))

    def test_inactive_role_assignments_do_not_grant_governance_access(self):
        for status in [
            RoleAssignment.Status.REVOKED,
            RoleAssignment.Status.SUSPENDED,
            RoleAssignment.Status.EXPIRED,
        ]:
            with self.subTest(status=status):
                user = self.create_user(f"user-{status}")
                _member, assignment, _permission = self.create_maintenance_role_permission(user)
                assignment.status = status
                assignment.save(update_fields=["status", "updated_at"])

                self.assertFalse(user_has_permission(user, MAINTENANCE_VIEW_ADMIN_PERMISSION))

    def test_init_maintainer_permissions_command_is_idempotent(self):
        output = StringIO()
        call_command("init_maintainer_permissions", stdout=output)
        call_command("init_maintainer_permissions", stdout=output)

        codes = [item["code"] for item in BASE_MAINTENANCE_PERMISSIONS]
        self.assertEqual(Permission.objects.filter(code__in=codes).count(), len(codes))
        organization = Organization.objects.get(name=ROLE_CATALOG_ORGANIZATION_NAME)
        role = Role.objects.get(organization=organization, name=ROLE_MAINTAINER)
        self.assertEqual(RolePermission.objects.filter(role=role, permission__code__in=codes).count(), len(codes))

    def test_init_maintainer_permissions_reports_explicit_world_id(self):
        output = StringIO()

        call_command("init_maintainer_permissions", "--world-id", "simulation0001", stdout=output)

        self.assertIn("world_id=simulation0001", output.getvalue())

    @override_settings(WORLD_DATABASE_ROUTING_ENABLED=True)
    def test_init_maintainer_permissions_requires_world_when_routing_is_enabled(self):
        with self.assertRaises(CommandError) as captured:
            call_command("init_maintainer_permissions", stdout=StringIO())

        self.assertIn("requires --world-id", str(captured.exception))
