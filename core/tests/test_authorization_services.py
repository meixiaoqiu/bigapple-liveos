from __future__ import annotations

from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from core.authorization_services import (
    OpenFGACheck,
    AuthorizationService,
    openfga_global_resource_permission_object,
    openfga_check_for_member_permission,
    openfga_context_for_world_kind,
    openfga_permission_object,
    openfga_resource_permission_object,
)
from core.governance_setup import MAINTENANCE_VIEW_ADMIN_PERMISSION, ensure_maintainer_role
from core.finance_setup import FINANCE_REVIEW_PERMISSION, ensure_finance_roles
from core.member_roles import ROLE_COVENANTER, ROLE_MAINTAINER
from core.models import Organization, Permission, Role, RoleAssignment, RolePermission
from core.permission_services import member_has_permission
from core.role_assignment_services import create_role_assignment, revoke_role_assignment
from core.tests.helpers import create_maintainer_member, create_member
from core.management.commands.openfga_rebuild_tuples import _project_authorization_tuples, _unique_tuples


class AuthorizationServiceTests(TestCase):
    def test_governance_permission_requires_covenanter_to_remain_active(self) -> None:
        member = create_maintainer_member("auth-gov")

        self.assertTrue(member_has_permission(member, MAINTENANCE_VIEW_ADMIN_PERMISSION))

        covenanter_assignment = RoleAssignment.objects.get(
            member=member,
            role__name=ROLE_COVENANTER,
            status=RoleAssignment.Status.ACTIVE,
        )
        revoke_role_assignment(assignment=covenanter_assignment)

        self.assertFalse(member_has_permission(member, MAINTENANCE_VIEW_ADMIN_PERMISSION))

    def test_openfga_check_uses_guarded_permission_for_governance_codes(self) -> None:
        member = create_maintainer_member("auth-fga-object")

        check = openfga_check_for_member_permission(member, MAINTENANCE_VIEW_ADMIN_PERMISSION)

        self.assertEqual(
            check,
            OpenFGACheck(
                user=f"member:{member.pk}",
                relation="holder",
                object_=f"guarded_permission:{MAINTENANCE_VIEW_ADMIN_PERMISSION}",
            ),
        )

    def test_non_governance_permission_uses_plain_permission_object(self) -> None:
        self.assertEqual(openfga_permission_object("workspace.view"), "permission:workspace.view")

    @override_settings(BIG_APPLE_AUTHORIZATION_BACKEND="openfga", OPENFGA_SIM_STORE_ID="")
    def test_openfga_backend_fails_closed_without_store(self) -> None:
        member = create_maintainer_member("auth-fga-no-store")

        self.assertFalse(AuthorizationService().member_has_permission(member, MAINTENANCE_VIEW_ADMIN_PERMISSION))

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
        create_maintainer_member("auth-fga-dry-run")
        output = StringIO()

        call_command("openfga_rebuild_tuples", "--world-kind", "sim", "--dry-run", stdout=output)

        self.assertIn("Would delete all existing OpenFGA tuples and rebuild", output.getvalue())

    @override_settings(OPENFGA_SIM_STORE_ID="store-id", OPENFGA_SIM_AUTHORIZATION_MODEL_ID="model-id")
    def test_openfga_rebuild_tuples_deletes_all_existing_tuples_before_rebuild(self) -> None:
        create_maintainer_member("auth-fga-stale")

        with patch("core.management.commands.openfga_rebuild_tuples.OpenFGAClient") as client_class:
            client = client_class.return_value
            client.read_tuples.return_value = [
                {
                    "key": {
                        "user": "member:stale",
                        "relation": "assignee",
                        "object": "role:stale",
                    }
                }
            ]
            output = StringIO()

            call_command("openfga_rebuild_tuples", "--world-kind", "sim", stdout=output)

        client.delete_tuples.assert_called_once_with(
            store_id="store-id",
            authorization_model_id="model-id",
            deletes=[
                {
                    "user": "member:stale",
                    "relation": "assignee",
                    "object": "role:stale",
                }
            ],
        )
        client.write_tuples.assert_called()
        self.assertIn("deleted 1 existing tuples", output.getvalue())
        self.assertIn("rebuilt tuples", output.getvalue())

    @override_settings(
        BIG_APPLE_AUTHORIZATION_BACKEND="openfga",
        OPENFGA_SIM_STORE_ID="store-id",
        OPENFGA_SIM_AUTHORIZATION_MODEL_ID="model-id",
    )
    def test_openfga_authorization_probe_reports_new_policy_result(self) -> None:
        member = create_maintainer_member("auth-fga-probe")
        output = StringIO()

        with patch("core.authorization_services.OpenFGAClient") as client_class:
            client_class.return_value.check.return_value = True
            call_command(
                "openfga_authorization_probe",
                "--world-kind",
                "sim",
                "--member-no",
                member.member_no,
                stdout=output,
            )

        probe_output = output.getvalue()
        self.assertIn("capability=maintenance", probe_output)
        self.assertIn("allowed=true", probe_output)

    def test_openfga_projection_removes_covenanter_after_revocation(self) -> None:
        member = create_maintainer_member("auth-fga-revoked-covenanter")
        covenanter_assignment = RoleAssignment.objects.get(
            member=member,
            role__name=ROLE_COVENANTER,
            status=RoleAssignment.Status.ACTIVE,
        )
        maintainer_assignment = RoleAssignment.objects.get(member=member, role__name=ROLE_MAINTAINER)

        revoke_role_assignment(assignment=covenanter_assignment)

        tuples = set(
            (item["user"], item["relation"], item["object"])
            for item in _unique_tuples(_project_authorization_tuples(platform_object="platform:test"))
        )
        self.assertNotIn((f"member:{member.pk}", "covenanter", "platform:test"), tuples)
        self.assertNotIn((f"member:{member.pk}", "maintainer", "platform:test"), tuples)
        self.assertNotIn((f"member:{member.pk}", "assignee", f"role:{maintainer_assignment.role_id}"), tuples)

    @override_settings(
        BIG_APPLE_AUTHORIZATION_BACKEND="openfga",
        OPENFGA_SIM_STORE_ID="store-id",
        OPENFGA_SIM_AUTHORIZATION_MODEL_ID="model-id",
    )
    def test_incremental_projection_deletes_tuple_after_revocation(self) -> None:
        member = create_maintainer_member("auth-fga-delete-revoked")
        assignment = RoleAssignment.objects.get(member=member, role__name=ROLE_MAINTAINER)

        with patch("core.openfga_projection_services.OpenFGAClient") as client_class:
            with self.captureOnCommitCallbacks(execute=True):
                revoke_role_assignment(assignment=assignment)

        client_class.return_value.delete_tuples.assert_called_once()
        deleted = client_class.return_value.delete_tuples.call_args.kwargs["deletes"]
        self.assertIn(
            {
                "user": f"member:{member.pk}",
                "relation": "assignee",
                "object": f"role:{assignment.role_id}",
            },
            deleted,
        )

    @override_settings(
        BIG_APPLE_AUTHORIZATION_BACKEND="openfga",
        OPENFGA_SIM_STORE_ID="store-id",
        OPENFGA_SIM_AUTHORIZATION_MODEL_ID="model-id",
    )
    def test_future_assignment_is_not_incrementally_written(self) -> None:
        member = create_member("auth-fga-future", role_name=ROLE_COVENANTER)
        role = ensure_finance_roles()["review_role"]
        now = timezone.now()

        with patch("core.openfga_projection_services.OpenFGAClient") as client_class:
            with self.captureOnCommitCallbacks(execute=True):
                create_role_assignment(
                    member=member,
                    role=role,
                    start_at=now + timedelta(days=1),
                    end_at=now + timedelta(days=2),
                )

        client_class.return_value.write_tuples.assert_not_called()

    @override_settings(
        BIG_APPLE_AUTHORIZATION_BACKEND="openfga",
        OPENFGA_SIM_STORE_ID="store-id",
        OPENFGA_SIM_AUTHORIZATION_MODEL_ID="model-id",
    )
    def test_stale_openfga_tuple_cannot_restore_expired_permission(self) -> None:
        member = create_member("auth-fga-expired", role_name=ROLE_COVENANTER)
        role = ensure_finance_roles()["review_role"]
        assignment = create_role_assignment(member=member, role=role)
        now = timezone.now()
        RoleAssignment.objects.filter(pk=assignment.pk).update(
            start_at=now - timedelta(days=2),
            end_at=now - timedelta(days=1),
        )

        with patch("core.authorization_services.OpenFGAClient") as client_class, patch(
            "core.openfga_projection_services.OpenFGAClient",
        ) as projection_client_class:
            client_class.return_value.check.return_value = True
            allowed = AuthorizationService().member_has_permission(member, FINANCE_REVIEW_PERMISSION)

        self.assertFalse(allowed)
        client_class.return_value.check.assert_not_called()
        projection_client_class.return_value.delete_tuples.assert_called_once()

    @override_settings(
        BIG_APPLE_AUTHORIZATION_BACKEND="openfga",
        OPENFGA_SIM_STORE_ID="store-id",
        OPENFGA_SIM_AUTHORIZATION_MODEL_ID="model-id",
    )
    def test_openfga_backend_rejects_governance_permission_when_openfga_denies(self) -> None:
        member = create_maintainer_member("auth-fga-denied-covenanter")

        with patch("core.authorization_services.OpenFGAClient") as client_class:
            client_class.return_value.check.return_value = False

            self.assertFalse(member_has_permission(member, MAINTENANCE_VIEW_ADMIN_PERMISSION))

    @override_settings(
        BIG_APPLE_AUTHORIZATION_BACKEND="openfga",
        OPENFGA_SIM_STORE_ID="store-id",
        OPENFGA_SIM_AUTHORIZATION_MODEL_ID="model-id",
        OPENFGA_SIM_PLATFORM_OBJECT="platform:sim",
    )
    def test_openfga_backend_allows_permission_only_from_openfga_check(self) -> None:
        member = create_maintainer_member("auth-fga-allowed")

        with patch("core.authorization_services.OpenFGAClient") as client_class:
            client_class.return_value.check.return_value = True

            self.assertTrue(member_has_permission(member, MAINTENANCE_VIEW_ADMIN_PERMISSION))

        client_class.return_value.check.assert_called_once_with(
            store_id="store-id",
            authorization_model_id="model-id",
            user=f"member:{member.pk}",
            relation="holder",
            object_=f"guarded_permission:{MAINTENANCE_VIEW_ADMIN_PERMISSION}",
        )

    @override_settings(
        BIG_APPLE_AUTHORIZATION_BACKEND="openfga",
        OPENFGA_SIM_STORE_ID="store-id",
        OPENFGA_SIM_AUTHORIZATION_MODEL_ID="model-id",
    )
    def test_openfga_backend_checks_resource_scoped_permission_objects(self) -> None:
        member = create_maintainer_member("auth-fga-resource-denied")
        resource = type("ResourceStub", (), {"pk": "resource-auth-fga"})()

        with patch("core.authorization_services.OpenFGAClient") as client_class:
            client_class.return_value.check.side_effect = [False, True]

            self.assertTrue(
                AuthorizationService().member_has_permission(
                    member,
                    MAINTENANCE_VIEW_ADMIN_PERMISSION,
                    resource=resource,
                )
            )

        client_class.return_value.check.assert_any_call(
            store_id="store-id",
            authorization_model_id="model-id",
            user=f"member:{member.pk}",
            relation="holder",
            object_=openfga_global_resource_permission_object(MAINTENANCE_VIEW_ADMIN_PERMISSION),
        )
        client_class.return_value.check.assert_any_call(
            store_id="store-id",
            authorization_model_id="model-id",
            user=f"member:{member.pk}",
            relation="holder",
            object_=openfga_resource_permission_object(MAINTENANCE_VIEW_ADMIN_PERMISSION, resource.pk),
        )

    def test_openfga_projection_includes_global_resource_permission_object(self) -> None:
        role = ensure_maintainer_role()["role"]

        tuples = set(
            (item["user"], item["relation"], item["object"])
            for item in _unique_tuples(_project_authorization_tuples(platform_object="platform:test"))
        )

        self.assertIn(
            (f"role:{role.pk}", "role", openfga_permission_object(MAINTENANCE_VIEW_ADMIN_PERMISSION)),
            tuples,
        )
        self.assertIn(
            (f"role:{role.pk}", "role", openfga_global_resource_permission_object(MAINTENANCE_VIEW_ADMIN_PERMISSION)),
            tuples,
        )

    def test_openfga_projection_rejects_unclassified_role_permission_tuples(self) -> None:
        organization = Organization.objects.create(name="auth-fga-scoped-resource-org")
        role = Role.objects.create(organization=organization, name="auth-fga-scoped-resource-role")
        permission = Permission.objects.create(code="access.warehouse", name="warehouse", category="access")
        RolePermission.objects.create(
            role=role,
            permission=permission,
            scope="resource",
            constraints_json={"resource_id": "auth-fga-scoped-resource"},
        )

        tuples = set(
            (item["user"], item["relation"], item["object"])
            for item in _unique_tuples(_project_authorization_tuples(platform_object="platform:test"))
        )

        self.assertNotIn(
            (f"role:{role.pk}", "role", openfga_permission_object("access.warehouse")),
            tuples,
        )
        self.assertNotIn(
            (f"role:{role.pk}", "role", openfga_global_resource_permission_object("access.warehouse")),
            tuples,
        )

    def test_openfga_projection_rejects_unclassified_finance_role_permission_tuples(self) -> None:
        organization = Organization.objects.create(name="auth-fga-guarded-resource-org")
        role = Role.objects.create(organization=organization, name="auth-fga-guarded-resource-role")
        permission = Permission.objects.create(code="finance.review", name="finance review", category="finance")
        RolePermission.objects.create(role=role, permission=permission, scope="global")

        permission_object = openfga_global_resource_permission_object("finance.review")
        tuples = set(
            (item["user"], item["relation"], item["object"])
            for item in _unique_tuples(_project_authorization_tuples(platform_object="platform:test"))
        )

        self.assertNotIn((f"role:{role.pk}", "role", permission_object), tuples)
        self.assertNotIn(("platform:test", "platform", permission_object), tuples)

    def test_openfga_projection_includes_canonical_finance_reviewer(self) -> None:
        from core.finance_setup import FINANCE_REVIEW_PERMISSION, ensure_finance_roles

        member = create_member("auth-fga-finance-reviewer", role_name=ROLE_COVENANTER)
        role = ensure_finance_roles()["review_role"]
        create_role_assignment(member=member, role=role)
        tuples = {
            (item["user"], item["relation"], item["object"])
            for item in _unique_tuples(_project_authorization_tuples(platform_object="platform:test"))
        }

        self.assertIn((f"member:{member.pk}", "assignee", f"role:{role.pk}"), tuples)
        self.assertIn(
            (f"role:{role.pk}", "role", openfga_permission_object(FINANCE_REVIEW_PERMISSION)),
            tuples,
        )
        self.assertIn(
            ("platform:test", "platform", openfga_global_resource_permission_object(FINANCE_REVIEW_PERMISSION)),
            tuples,
        )

    @override_settings(
        BIG_APPLE_AUTHORIZATION_BACKEND="openfga",
        OPENFGA_SIM_STORE_ID="store-id",
        OPENFGA_SIM_AUTHORIZATION_MODEL_ID="model-id",
        OPENFGA_SIM_PLATFORM_OBJECT="platform:sim",
    )
    def test_full_workspace_access_uses_openfga_covenanter_relation(self) -> None:
        member = create_maintainer_member("auth-fga-workspace")

        with patch("core.authorization_services.OpenFGAClient") as client_class:
            client_class.return_value.check.return_value = True

            self.assertTrue(AuthorizationService().member_has_full_workspace_access(member))

        client_class.return_value.check.assert_called_once_with(
            store_id="store-id",
            authorization_model_id="model-id",
            user=f"member:{member.pk}",
            relation="covenanter",
            object_="platform:sim",
        )
