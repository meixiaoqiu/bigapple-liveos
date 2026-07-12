from __future__ import annotations

from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from core.access import is_governance_principal, user_has_governance_permission
from core.governance_setup import (
    BASE_GOVERNANCE_PERMISSIONS,
    GOVERNANCE_ADMIN_ORGANIZATION_NAME,
    GOVERNANCE_ADMIN_ROLE_NAME,
    GOVERNANCE_VIEW_ADMIN_PERMISSION,
)
from core.member_roles import ROLE_CONTRIBUTOR, ROLE_GOVERNANCE_MEMBER
from core.models import Organization, Permission, Role, RoleAssignment, RolePermission
from core.role_assignment_services import create_role_assignment
from core.tests.helpers import create_member


class GovernanceAccessBridgeTests(TestCase):
    def create_user(self, username: str):
        return get_user_model().objects.create_user(username=username, password="test-password")

    def create_governance_role_permission(self, user, permission_code=GOVERNANCE_VIEW_ADMIN_PERMISSION):
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
        member = create_member(user.username, role_name=ROLE_CONTRIBUTOR, user=user, display_name=user.username)
        assignment = create_role_assignment(member=member, role=role)
        RolePermission.objects.create(role=role, permission=permission, scope="global")
        return member, assignment, permission

    def test_governance_member_role_without_role_permission_is_denied(self):
        member = create_member(
            "member-admin-role",
            role_name=ROLE_GOVERNANCE_MEMBER,
            profile={"display_name": "member-admin-role"},
            created_at=timezone.now(),
        )
        user = self.create_user(member.member_no)

        self.assertFalse(user_has_governance_permission(user, GOVERNANCE_VIEW_ADMIN_PERMISSION))
        self.assertFalse(is_governance_principal(user))

    def test_staff_without_governance_permission_is_denied(self):
        user = self.create_user("staff-without-governance")
        user.is_staff = True
        user.save(update_fields=["is_staff"])
        create_member(user.username, role_name=ROLE_CONTRIBUTOR, user=user, display_name=user.username)

        self.assertFalse(user_has_governance_permission(user, GOVERNANCE_VIEW_ADMIN_PERMISSION))
        self.assertFalse(is_governance_principal(user))

    def test_role_permission_allows_governance_access_without_governance_member_role(self):
        user = self.create_user("new-governance-user")
        self.create_governance_role_permission(user)

        self.assertTrue(user_has_governance_permission(user, GOVERNANCE_VIEW_ADMIN_PERMISSION))
        self.assertTrue(is_governance_principal(user))

    def test_member_principal_can_use_role_permission(self):
        member = create_member(
            "member-with-role-permission",
            role_name=ROLE_CONTRIBUTOR,
            profile={"display_name": "member-with-role-permission"},
        )
        organization = Organization.objects.create(
            name="Member Principal Governance",
        )
        role = Role.objects.create(organization=organization, name="Member Principal Admin")
        permission, _created = Permission.objects.get_or_create(
            code=GOVERNANCE_VIEW_ADMIN_PERMISSION,
            defaults={
                "name": "Governance view",
                "category": "governance",
            },
        )
        create_role_assignment(member=member, role=role)
        RolePermission.objects.create(role=role, permission=permission, scope="global")

        self.assertTrue(is_governance_principal(member))

    def test_user_without_governance_member_role_or_role_permission_is_denied(self):
        user = self.create_user("plain-user")
        create_member(user.username, role_name=ROLE_CONTRIBUTOR, profile={"display_name": user.username})

        self.assertFalse(user_has_governance_permission(user, GOVERNANCE_VIEW_ADMIN_PERMISSION))
        self.assertFalse(is_governance_principal(user))

    def test_inactive_role_assignments_do_not_grant_governance_access(self):
        for status in [
            RoleAssignment.Status.REVOKED,
            RoleAssignment.Status.SUSPENDED,
            RoleAssignment.Status.EXPIRED,
        ]:
            with self.subTest(status=status):
                user = self.create_user(f"user-{status}")
                _member, assignment, _permission = self.create_governance_role_permission(user)
                assignment.status = status
                assignment.save(update_fields=["status", "updated_at"])

                self.assertFalse(user_has_governance_permission(user, GOVERNANCE_VIEW_ADMIN_PERMISSION))

    def test_init_governance_permissions_command_is_idempotent(self):
        output = StringIO()
        call_command("init_governance_permissions", stdout=output)
        call_command("init_governance_permissions", stdout=output)

        codes = [item["code"] for item in BASE_GOVERNANCE_PERMISSIONS]
        self.assertEqual(Permission.objects.filter(code__in=codes).count(), len(codes))
        organization = Organization.objects.get(name=GOVERNANCE_ADMIN_ORGANIZATION_NAME)
        role = Role.objects.get(organization=organization, name=GOVERNANCE_ADMIN_ROLE_NAME)
        self.assertEqual(RolePermission.objects.filter(role=role, permission__code__in=codes).count(), len(codes))

    def test_init_governance_permissions_reports_explicit_world_id(self):
        output = StringIO()

        call_command("init_governance_permissions", "--world-id", "simulation0001", stdout=output)

        self.assertIn("world_id=simulation0001", output.getvalue())

    @override_settings(WORLD_DATABASE_ROUTING_ENABLED=True)
    def test_init_governance_permissions_requires_world_when_routing_is_enabled(self):
        with self.assertRaises(CommandError) as captured:
            call_command("init_governance_permissions", stdout=StringIO())

        self.assertIn("requires --world-id", str(captured.exception))
