from __future__ import annotations

import json
from io import StringIO
from unittest.mock import ANY, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from core.member_roles import ROLE_DELIBERATOR, ROLE_FORMAL_MEMBER, ROLE_MAINTAINER, member_has_role
from core.models import Member, MemberProfessionalQualification, Organization, ProfessionalDomain, Role, RoleAssignment
from core.openfga_client import OpenFGARequestError
from core.role_baseline import clear_role_permission_baseline, load_role_permission_baseline
from core.role_catalog import ROLE_CATALOG_ORGANIZATION_NAME
from worlds.models import WorldRegistry


class RolePermissionBaselineServiceTests(TestCase):
    def test_reset_then_seed_only_keeps_new_role_baseline(self):
        clear_role_permission_baseline()
        report = load_role_permission_baseline()

        self.assertEqual(report["roles"], 3)
        self.assertEqual(
            set(Role.objects.values_list("organization__name", "name")),
            {
                (ROLE_CATALOG_ORGANIZATION_NAME, ROLE_FORMAL_MEMBER),
                (ROLE_CATALOG_ORGANIZATION_NAME, ROLE_DELIBERATOR),
                (ROLE_CATALOG_ORGANIZATION_NAME, ROLE_MAINTAINER),
            },
        )
        contributor = Member.objects.get(member_no="role-baseline-contributor")
        deliberator = Member.objects.get(member_no="role-baseline-deliberator")
        maintainer = Member.objects.get(member_no="role-baseline-maintainer")
        qualified = Member.objects.get(member_no="role-baseline-finance")
        self.assertFalse(RoleAssignment.objects.filter(member=contributor).exists())
        self.assertTrue(member_has_role(deliberator, ROLE_FORMAL_MEMBER))
        self.assertTrue(member_has_role(deliberator, ROLE_DELIBERATOR))
        self.assertTrue(member_has_role(maintainer, ROLE_MAINTAINER))
        self.assertFalse(member_has_role(maintainer, ROLE_DELIBERATOR))
        self.assertTrue(
            MemberProfessionalQualification.objects.filter(member=qualified, domain__code="finance").exists()
        )

    def test_repeated_reset_and_seed_is_stable(self):
        clear_role_permission_baseline()
        first = load_role_permission_baseline()
        clear_role_permission_baseline()
        second = load_role_permission_baseline()

        self.assertEqual(first["roles"], second["roles"])
        self.assertEqual(first["role_assignments"], second["role_assignments"])
        self.assertEqual(first["professional_domains"], second["professional_domains"])
        self.assertEqual(ProfessionalDomain.objects.count(), 3)


@override_settings(
    WORLD_DATABASE_ROUTING_ENABLED=False,
    DEFAULT_WORLD_DATABASE_ALIAS="default",
    WORLD_DATABASE_ALIASES=("default",),
    OPENFGA_SIM_STORE_ID="",
    OPENFGA_SIM_AUTHORIZATION_MODEL_ID="",
)
class ResetRolePermissionBaselineCommandTests(TestCase):
    def create_world(self, *, world_id: str, world_type: str):
        return WorldRegistry.objects.create(
            world_id=world_id,
            name=world_id,
            world_type=world_type,
            database_alias="default",
            database_name="test_default",
            status=WorldRegistry.Status.ACTIVE,
        )

    def test_command_requires_an_active_simulation_world_and_reports_baseline(self):
        self.create_world(world_id="simulation-role-baseline", world_type=WorldRegistry.WorldType.SIMULATION)
        output = StringIO()

        call_command(
            "reset_role_permission_baseline",
            "--world-id",
            "simulation-role-baseline",
            "--format",
            "json",
            stdout=output,
        )

        report = json.loads(output.getvalue())
        self.assertEqual(report["result"], "PASS")
        self.assertEqual(report["world_id"], "simulation-role-baseline")
        self.assertEqual(report["openfga"], "SKIP:not_configured")

    def test_command_refuses_a_real_world(self):
        self.create_world(world_id="real-role-baseline", world_type=WorldRegistry.WorldType.REAL)

        with self.assertRaises(CommandError):
            call_command("reset_role_permission_baseline", "--world-id", "real-role-baseline")

    @override_settings(
        OPENFGA_SIM_STORE_ID="test-store",
        OPENFGA_SIM_AUTHORIZATION_MODEL_ID="test-model",
    )
    def test_openfga_preflight_failure_does_not_clear_the_simulation_world(self):
        self.create_world(world_id="simulation-role-baseline", world_type=WorldRegistry.WorldType.SIMULATION)
        organization = Organization.objects.create(name="预检保护组织")
        protected_role = Role.objects.create(
            organization=organization,
            name="预检保护角色",
            status=Role.Status.ACTIVE,
        )

        with patch(
            "core.management.commands.reset_role_permission_baseline.OpenFGAClient"
        ) as client_class:
            client_class.return_value.check.side_effect = OpenFGARequestError("模型不匹配")
            with self.assertRaisesMessage(CommandError, "基线未作任何修改"):
                call_command("reset_role_permission_baseline", "--world-id", "simulation-role-baseline")

        self.assertTrue(Role.objects.filter(pk=protected_role.pk).exists())

    @override_settings(
        OPENFGA_SIM_STORE_ID="test-store",
        OPENFGA_SIM_AUTHORIZATION_MODEL_ID="test-model",
    )
    def test_configured_reset_rebuilds_tuples_for_the_selected_simulation_world(self):
        self.create_world(world_id="simulation-role-baseline", world_type=WorldRegistry.WorldType.SIMULATION)

        with patch(
            "core.management.commands.reset_role_permission_baseline.OpenFGAClient"
        ) as client_class, patch(
            "core.management.commands.reset_role_permission_baseline.call_command"
        ) as call_command_mock:
            client_class.return_value.check.return_value = False
            call_command(
                "reset_role_permission_baseline",
                "--world-id",
                "simulation-role-baseline",
            )

        call_command_mock.assert_called_once_with(
            "openfga_rebuild_tuples",
            "--world-id",
            "simulation-role-baseline",
            "--world-kind",
            "sim",
            stdout=ANY,
        )
