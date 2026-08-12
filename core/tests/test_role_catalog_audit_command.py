from __future__ import annotations

from datetime import timedelta
from io import StringIO
import json

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from core.governance_setup import ADMINISTRATION_VIEW_ADMIN_PERMISSION
from core.role_catalog import ROLE_CATALOG_ORGANIZATION_NAME, ROLE_COVENANTER, ROLE_ADMINISTRATOR
from core.models import Organization, Permission, Role, RoleAssignment, RolePermission
from core.tests.helpers import create_administrator_member, create_member


class AuditRoleCatalogCommandTests(TestCase):
    def test_json_report_lists_catalog_roles_permissions_and_world_scope(self):
        member = create_administrator_member("role-audit-administrator")
        assignment_count_before = RoleAssignment.objects.count()
        output = StringIO()

        call_command("audit_role_catalog", "--format", "json", stdout=output)

        report = json.loads(output.getvalue())
        self.assertEqual(report["scope"]["world_id"], "default")
        self.assertEqual(report["summary"]["role_assignments"], assignment_count_before)
        self.assertEqual(RoleAssignment.objects.count(), assignment_count_before)

        administrator = next(entry for entry in report["roles"] if entry["role"]["name"] == ROLE_ADMINISTRATOR)
        self.assertTrue(administrator["role"]["exists"])
        self.assertTrue(administrator["catalog"]["requires_covenanter"])
        self.assertEqual(administrator["assignment_counts"]["currently_effective"], 1)
        self.assertIn(
            ADMINISTRATION_VIEW_ADMIN_PERMISSION,
            {binding["permission_code"] for binding in administrator["permission_bindings"]},
        )
        bootstrap_path = next(
            item for item in report["assignment_creation_paths"] if item["id"] == "initial-administrator-bootstrap"
        )
        self.assertEqual(bootstrap_path["direct_role_facts"], [ROLE_COVENANTER, ROLE_ADMINISTRATOR])
        self.assertEqual(member.member_no, "role-audit-administrator")

    def test_report_detects_effective_unclassified_duty_without_covenanter(self):
        member = create_member("role-audit-missing-covenanter")
        organization = Organization.objects.create(name="盘点职责")
        role = Role.objects.create(organization=organization, name="盘点管理员")
        permission = Permission.objects.create(
            code="governance.role_audit",
            name="盘点维护权限",
            category="governance",
        )
        RolePermission.objects.create(role=role, permission=permission, scope="global")
        RoleAssignment.objects.create(
            member=member,
            role=role,
            start_at=timezone.now() - timedelta(minutes=1),
            end_at=timezone.now() + timedelta(days=1),
        )
        output = StringIO()

        call_command("audit_role_catalog", "--format", "json", stdout=output)

        report = json.loads(output.getvalue())
        entry = next(entry for entry in report["roles"] if entry["role"]["id"] == role.pk)
        self.assertEqual(entry["catalog"]["dimension"], "unclassified")
        self.assertTrue(entry["prerequisite_compliance"]["requires_covenanter"])
        self.assertEqual(entry["prerequisite_compliance"]["missing_covenanter"], 1)

    def test_text_report_includes_catalog_roles_missing_from_database(self):
        output = StringIO()

        call_command("audit_role_catalog", stdout=output)

        report = output.getvalue()
        self.assertIn("角色盘点：world_id=default", report)
        self.assertIn(f"{ROLE_CATALOG_ORGANIZATION_NAME} / {ROLE_COVENANTER}", report)
        self.assertIn("存在=False", report)
