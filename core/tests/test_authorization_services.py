from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings

from core.authorization_services import (
    OpenFGACheck,
    AuthorizationService,
    openfga_check_for_member_permission,
    openfga_context_for_world_kind,
    openfga_permission_object,
)
from core.governance_setup import GOVERNANCE_VIEW_ADMIN_PERMISSION
from core.member_roles import ROLE_FORMAL_MEMBER
from core.models import RoleAssignment
from core.permission_services import member_has_permission
from core.role_assignment_services import revoke_role_assignment
from core.tests.helpers import create_governance_admin_member
from core.management.commands.openfga_rebuild_tuples import _project_authorization_tuples, _unique_tuples


class AuthorizationServiceTests(TestCase):
    def test_governance_permission_requires_formal_member_to_remain_active(self) -> None:
        member = create_governance_admin_member("auth-gov")

        self.assertTrue(member_has_permission(member, GOVERNANCE_VIEW_ADMIN_PERMISSION))

        formal_assignment = RoleAssignment.objects.get(
            member=member,
            role__name=ROLE_FORMAL_MEMBER,
            status=RoleAssignment.Status.ACTIVE,
        )
        revoke_role_assignment(assignment=formal_assignment)

        self.assertFalse(member_has_permission(member, GOVERNANCE_VIEW_ADMIN_PERMISSION))

    def test_openfga_check_uses_guarded_permission_for_governance_codes(self) -> None:
        member = create_governance_admin_member("auth-fga-object")

        check = openfga_check_for_member_permission(member, GOVERNANCE_VIEW_ADMIN_PERMISSION)

        self.assertEqual(
            check,
            OpenFGACheck(
                user=f"member:{member.pk}",
                relation="holder",
                object_=f"guarded_permission:{GOVERNANCE_VIEW_ADMIN_PERMISSION}",
            ),
        )

    def test_non_governance_permission_uses_plain_permission_object(self) -> None:
        self.assertEqual(openfga_permission_object("workspace.view"), "permission:workspace.view")

    @override_settings(BIG_APPLE_AUTHORIZATION_BACKEND="openfga", OPENFGA_SIM_STORE_ID="")
    def test_openfga_backend_fails_closed_without_store(self) -> None:
        member = create_governance_admin_member("auth-fga-no-store")

        self.assertFalse(AuthorizationService().member_has_permission(member, GOVERNANCE_VIEW_ADMIN_PERMISSION))

    @override_settings(
        OPENFGA_REAL_API_URL="http://real-fga:8080",
        OPENFGA_REAL_STORE_NAME="real-store",
        OPENFGA_REAL_STORE_ID="real-store-id",
        OPENFGA_REAL_AUTHORIZATION_MODEL_ID="real-model-id",
        OPENFGA_REAL_PLATFORM_OBJECT="platform:real",
        OPENFGA_SIM_API_URL="http://sim-fga:8080",
        OPENFGA_SIM_STORE_NAME="sim-store",
        OPENFGA_SIM_STORE_ID="sim-store-id",
        OPENFGA_SIM_AUTHORIZATION_MODEL_ID="sim-model-id",
        OPENFGA_SIM_PLATFORM_OBJECT="platform:sim",
    )
    def test_openfga_context_is_split_between_real_and_sim(self) -> None:
        real_context = openfga_context_for_world_kind("real")
        sim_context = openfga_context_for_world_kind("sim")

        self.assertEqual(real_context.api_url, "http://real-fga:8080")
        self.assertEqual(real_context.store_id, "real-store-id")
        self.assertEqual(real_context.platform_object, "platform:real")
        self.assertEqual(sim_context.api_url, "http://sim-fga:8080")
        self.assertEqual(sim_context.store_id, "sim-store-id")
        self.assertEqual(sim_context.platform_object, "platform:sim")

    def test_openfga_rebuild_tuples_dry_run_does_not_require_store_id(self) -> None:
        create_governance_admin_member("auth-fga-dry-run")
        output = StringIO()

        call_command("openfga_rebuild_tuples", "--world-kind", "sim", "--dry-run", stdout=output)

        self.assertIn("Would write", output.getvalue())

    @override_settings(OPENFGA_SIM_STORE_ID="store-id", OPENFGA_SIM_AUTHORIZATION_MODEL_ID="model-id")
    def test_openfga_authorization_probe_reports_matching_result(self) -> None:
        create_governance_admin_member("auth-fga-probe")
        output = StringIO()

        with patch("core.management.commands.openfga_authorization_probe.OpenFGAClient") as client_class:
            client_class.return_value.check.return_value = True
            call_command("openfga_authorization_probe", "--world-kind", "sim", stdout=output)

        probe_output = output.getvalue()
        self.assertIn("status=OK", probe_output)
        self.assertIn("diffs=0", probe_output)

    def test_openfga_projection_removes_formal_member_after_revocation(self) -> None:
        member = create_governance_admin_member("auth-fga-revoked-formal")
        formal_assignment = RoleAssignment.objects.get(
            member=member,
            role__name=ROLE_FORMAL_MEMBER,
            status=RoleAssignment.Status.ACTIVE,
        )
        governance_assignment = RoleAssignment.objects.get(
            member=member,
            role__role_permissions__permission__code=GOVERNANCE_VIEW_ADMIN_PERMISSION,
            status=RoleAssignment.Status.ACTIVE,
        )

        revoke_role_assignment(assignment=formal_assignment)

        tuples = set(
            (item["user"], item["relation"], item["object"])
            for item in _unique_tuples(_project_authorization_tuples(platform_object="platform:test"))
        )
        self.assertNotIn((f"member:{member.pk}", "formal_member", "platform:test"), tuples)
        self.assertIn((f"member:{member.pk}", "assignee", f"role:{governance_assignment.role_id}"), tuples)

    @override_settings(
        BIG_APPLE_AUTHORIZATION_BACKEND="openfga",
        OPENFGA_SIM_STORE_ID="store-id",
        OPENFGA_SIM_AUTHORIZATION_MODEL_ID="model-id",
    )
    def test_openfga_backend_rejects_governance_permission_when_openfga_denies(self) -> None:
        member = create_governance_admin_member("auth-fga-denied-formal")

        with patch("core.authorization_services.OpenFGAClient") as client_class:
            client_class.return_value.check.return_value = False

            self.assertFalse(member_has_permission(member, GOVERNANCE_VIEW_ADMIN_PERMISSION))
