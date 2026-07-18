from __future__ import annotations

from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from core.access import user_has_governance_permission
from core.governance_setup import (
    GOVERNANCE_ADMIN_ORGANIZATION_NAME,
    GOVERNANCE_ADMIN_ROLE_NAME,
    GOVERNANCE_VIEW_ADMIN_PERMISSION,
)
from core.member_roles import (
    MEMBER_ROLE_ORGANIZATION_NAME,
    ROLE_BIG_APPLE_MEMBER,
    ROLE_FORMAL_MEMBER,
    ROLE_GOVERNANCE_MEMBER,
    member_has_role,
)
from core.models import Member, Organization, Role, RoleAssignment, SystemEvent


@override_settings(
    WORLD_DATABASE_ROUTING_ENABLED=False,
    DEFAULT_WORLD_DATABASE_ALIAS="default",
    WORLD_DATABASE_ALIASES=("default",),
)
class BootstrapWorldCommandTests(TestCase):
    def call_bootstrap(self, **options) -> str:
        output = StringIO()
        defaults = {
            "control_password": "control-test-password",
            "world_admin_password": "world-test-password",
            "stdout": output,
        }
        defaults.update(options)
        call_command("bootstrap_world", **defaults)
        return output.getvalue()

    def governance_admin_role(self) -> Role:
        organization = Organization.objects.get(name=GOVERNANCE_ADMIN_ORGANIZATION_NAME)
        return Role.objects.get(organization=organization, name=GOVERNANCE_ADMIN_ROLE_NAME)

    def test_bootstrap_creates_control_admin_and_world_governance_admin(self) -> None:
        self.call_bootstrap()

        user_model = get_user_model()
        control_user = user_model.objects.get(username="wzy")
        world_user = user_model.objects.get(username="member-admin-0001")
        member = Member.objects.get(member_no="member-admin-0001")
        role = self.governance_admin_role()

        self.assertTrue(control_user.is_staff)
        self.assertTrue(control_user.is_superuser)
        self.assertFalse(world_user.is_staff)
        self.assertFalse(world_user.is_superuser)
        self.assertEqual(member.user, world_user)
        self.assertTrue(
            RoleAssignment.objects.filter(
                member=member,
                role=role,
                status=RoleAssignment.Status.ACTIVE,
            ).exists()
        )
        # Verify full role chain
        self.assertTrue(member_has_role(member, ROLE_BIG_APPLE_MEMBER))
        self.assertTrue(member_has_role(member, ROLE_FORMAL_MEMBER))
        self.assertTrue(member_has_role(member, ROLE_GOVERNANCE_MEMBER))
        self.assertTrue(user_has_governance_permission(world_user, GOVERNANCE_VIEW_ADMIN_PERMISSION))
        # No stray "治理管理员" role in the basic-member organization
        basic_org = Organization.objects.get(name="基础角色")
        self.assertFalse(
            Role.objects.filter(organization=basic_org, name="治理管理员").exists()
        )

    def test_bootstrap_is_idempotent_for_world_governance_admin(self) -> None:
        self.call_bootstrap()
        member = Member.objects.get(member_no="member-admin-0001")
        role = self.governance_admin_role()
        assignment = RoleAssignment.objects.get(member=member, role=role, status=RoleAssignment.Status.ACTIVE)
        event_count = SystemEvent.objects.filter(
            event_type=SystemEvent.EventType.ROLE_ASSIGNED,
            aggregate_type="RoleAssignment",
            aggregate_id=str(assignment.pk),
        ).count()

        self.call_bootstrap()

        self.assertEqual(get_user_model().objects.filter(username="wzy").count(), 1)
        self.assertEqual(get_user_model().objects.filter(username="member-admin-0001").count(), 1)
        self.assertEqual(Member.objects.filter(member_no="member-admin-0001").count(), 1)
        self.assertEqual(
            RoleAssignment.objects.filter(member=member, role=role, status=RoleAssignment.Status.ACTIVE).count(),
            1,
        )
        self.assertEqual(
            SystemEvent.objects.filter(
                event_type=SystemEvent.EventType.ROLE_ASSIGNED,
                aggregate_type="RoleAssignment",
                aggregate_id=str(assignment.pk),
            ).count(),
            event_count,
        )

    def test_new_control_admin_requires_password(self) -> None:
        with self.assertRaises(CommandError) as captured:
            self.call_bootstrap(control_password="")

        self.assertIn("control admin requires", str(captured.exception))

    def test_new_world_admin_requires_password(self) -> None:
        with self.assertRaises(CommandError) as captured:
            self.call_bootstrap(skip_control_admin=True, world_admin_password="")

        self.assertIn("world admin requires", str(captured.exception))

    def test_bootstrap_requires_at_least_one_target(self) -> None:
        with self.assertRaises(CommandError) as captured:
            self.call_bootstrap(skip_control_admin=True, skip_world_admin=True)

        self.assertIn("Nothing to bootstrap", str(captured.exception))
