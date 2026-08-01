from __future__ import annotations

from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from core.access import user_has_permission
from core.governance_setup import MAINTENANCE_VIEW_ADMIN_PERMISSION
from core.member_roles import (
    ROLE_DELIBERATOR,
    ROLE_COVENANTER,
    ROLE_MAINTAINER,
    member_has_role,
)
from core.role_catalog import ROLE_CATALOG_ORGANIZATION_NAME
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
            "world_maintainer_password": "world-test-password",
            "stdout": output,
        }
        defaults.update(options)
        call_command("bootstrap_world", **defaults)
        return output.getvalue()

    def maintainer_role(self) -> Role:
        organization = Organization.objects.get(name=ROLE_CATALOG_ORGANIZATION_NAME)
        return Role.objects.get(organization=organization, name=ROLE_MAINTAINER)

    def test_bootstrap_creates_control_admin_and_world_maintainer(self) -> None:
        self.call_bootstrap()

        user_model = get_user_model()
        control_user = user_model.objects.get(username="wzy")
        world_user = user_model.objects.get(username="member-maintainer-0001")
        member = Member.objects.get(member_no="member-maintainer-0001")
        role = self.maintainer_role()

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
        # 典守者与守约者资格是独立的直接事实，不会附带执衡者职责。
        self.assertTrue(member_has_role(member, ROLE_COVENANTER))
        self.assertTrue(member_has_role(member, ROLE_MAINTAINER))
        self.assertFalse(member_has_role(member, ROLE_DELIBERATOR))
        self.assertTrue(user_has_permission(world_user, MAINTENANCE_VIEW_ADMIN_PERMISSION))

    def test_bootstrap_is_idempotent_for_world_maintainer(self) -> None:
        self.call_bootstrap()
        member = Member.objects.get(member_no="member-maintainer-0001")
        role = self.maintainer_role()
        assignment = RoleAssignment.objects.get(member=member, role=role, status=RoleAssignment.Status.ACTIVE)
        event_count = SystemEvent.objects.filter(
            event_type=SystemEvent.EventType.ROLE_ASSIGNED,
            aggregate_type="RoleAssignment",
            aggregate_id=str(assignment.pk),
        ).count()

        self.call_bootstrap()

        self.assertEqual(get_user_model().objects.filter(username="wzy").count(), 1)
        self.assertEqual(get_user_model().objects.filter(username="member-maintainer-0001").count(), 1)
        self.assertEqual(Member.objects.filter(member_no="member-maintainer-0001").count(), 1)
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

    def test_new_world_maintainer_requires_password(self) -> None:
        with self.assertRaises(CommandError) as captured:
            self.call_bootstrap(skip_control_admin=True, world_maintainer_password="")

        self.assertIn("world maintainer requires", str(captured.exception))

    def test_bootstrap_requires_at_least_one_target(self) -> None:
        with self.assertRaises(CommandError) as captured:
            self.call_bootstrap(skip_control_admin=True, skip_world_maintainer=True)

        self.assertIn("Nothing to bootstrap", str(captured.exception))
