from __future__ import annotations

from io import StringIO
import json

from django.contrib.admin.sites import AdminSite
from django.contrib.staticfiles import finders
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from core.access import user_has_governance_permission
from core.admin import SystemEventAdmin, MemberAdmin, ProposalAdmin, RoleAdmin
from core.event_ledger import PUBLIC_LEDGER_SCHEMA

_v2 = lambda action="manual": {
    "schema": PUBLIC_LEDGER_SCHEMA,
    "subject": {"type": "test", "ref": action, "label": "测试"},
    "action": action,
    "stage": "test",
    "summary": "测试事件。",
    "public_facts": {},
    "private_commitments": [],
}
from core.event_ledger import append_event
from core.governance_setup import (
    GOVERNANCE_ADMIN_ORGANIZATION_NAME,
    GOVERNANCE_ADMIN_ROLE_NAME,
    GOVERNANCE_VIEW_ADMIN_PERMISSION,
)
from core.member_roles import ROLE_FORMAL_MEMBER
from core.models import Permission, SystemEvent, Member, Organization, Proposal, Role, RoleAssignment, RolePermission
from core.tests.helpers import create_member


class GovernanceAdminUsabilityTests(TestCase):
    def admin_request(self):
        user = get_user_model().objects.create_superuser(
            username="admin-user",
            email="admin@example.com",
            password="test-password",
        )
        request = RequestFactory().get("/admin/")
        request.user = user
        return request

    def test_member_admin_includes_role_assignment_inline(self):
        admin = MemberAdmin(Member, AdminSite())

        inline_models = {inline.model for inline in admin.get_inline_instances(self.admin_request())}

        self.assertIn(RoleAssignment, inline_models)

    def test_role_admin_includes_role_permission_inline(self):
        admin = RoleAdmin(Role, AdminSite())

        inline_models = {inline.model for inline in admin.get_inline_instances(self.admin_request())}

        self.assertIn(RolePermission, inline_models)

    def test_system_event_admin_is_read_only_and_shortens_hash(self):
        event = append_event(
            event_type=SystemEvent.EventType.ROLE_ASSIGNED,
            aggregate_type="RoleAssignment",
            aggregate_id="manual",
            payload_json=_v2(),
        )
        admin = SystemEventAdmin(SystemEvent, AdminSite())
        request = self.admin_request()

        self.assertFalse(admin.has_add_permission(request))
        self.assertFalse(admin.has_change_permission(request, event))
        self.assertFalse(admin.has_delete_permission(request, event))
        self.assertEqual(admin.short_event_hash(event), event.event_hash[:12])

    def test_proposal_admin_uses_chinese_role_identity_label_and_filters_by_proposer(self):
        organization = Organization.objects.create(name="治理委员会")
        role = Role.objects.create(organization=organization, name="委员")
        other_role = Role.objects.create(organization=organization, name="仓库管理员")
        proposer = create_member("member-proposer")
        other_member = create_member("member-other")
        proposer_assignment = RoleAssignment.objects.create(
            member=proposer,
            role=role,
            end_at=timezone.now() + timezone.timedelta(days=30),
        )
        other_assignment = RoleAssignment.objects.create(
            member=other_member,
            role=other_role,
            end_at=timezone.now() + timezone.timedelta(days=30),
        )
        proposal = Proposal.objects.create(
            title="测试提案",
            proposal_type=Proposal.ProposalType.POLICY,
            status=Proposal.Status.DRAFT,
            proposer_member=proposer,
            organization=organization,
            deadline_at=timezone.now() + timezone.timedelta(days=7),
        )
        admin = ProposalAdmin(Proposal, AdminSite())
        form_class = admin.get_form(self.admin_request(), proposal)
        form = form_class(instance=proposal)
        field = form.fields["proposer_role_assignment"]

        self.assertEqual(Proposal._meta.get_field("proposer_role_assignment").verbose_name, "提案时角色身份")
        self.assertEqual(field.label, "提案时角色身份")
        self.assertIn(proposer_assignment, field.queryset)
        self.assertNotIn(other_assignment, field.queryset)

    def test_proposal_admin_role_identity_options_are_limited_to_selected_proposer(self):
        organization = Organization.objects.create(name="治理委员会")
        proposer_role = Role.objects.create(organization=organization, name="委员")
        other_role = Role.objects.create(organization=organization, name="仓库管理员")
        proposer = create_member("member-proposer-options")
        other_member = create_member("member-other-options")
        proposer_assignment = RoleAssignment.objects.create(
            member=proposer,
            role=proposer_role,
            end_at=timezone.now() + timezone.timedelta(days=30),
        )
        suspended_assignment = RoleAssignment.objects.create(
            member=proposer,
            role=other_role,
            status=RoleAssignment.Status.SUSPENDED,
            end_at=timezone.now() + timezone.timedelta(days=30),
        )
        other_assignment = RoleAssignment.objects.create(
            member=other_member,
            role=other_role,
            end_at=timezone.now() + timezone.timedelta(days=30),
        )
        admin = ProposalAdmin(Proposal, AdminSite())
        request = RequestFactory().get(
            "/admin/core/proposal/role-assignment-options/",
            {"member_pk": proposer.pk},
        )
        request.user = self.admin_request().user

        response = admin.role_assignment_options(request)
        payload = json.loads(response.content.decode("utf-8"))
        returned_ids = {item["id"] for item in payload["results"]}

        self.assertIn(proposer_assignment.pk, returned_ids)
        self.assertNotIn(suspended_assignment.pk, returned_ids)
        self.assertNotIn(other_assignment.pk, returned_ids)

    def test_proposal_admin_role_identity_script_waits_for_admin_jquery(self):
        path = finders.find("core/admin/proposal_role_assignment_filter.js")

        self.assertIsNotNone(path)
        with open(path, encoding="utf-8") as script_file:
            script = script_file.read()

        self.assertIn("/admin/core/proposal/role-assignment-options/", script)
        self.assertIn("function boot()", script)
        self.assertIn('typeof django.jQuery === "function"', script)
        self.assertIn("bindProposalRoleAssignmentFilter(adminJQuery)", script)
        self.assertIn("bindProposalRoleAssignmentFilter(globalJQuery)", script)
        self.assertIn('$(document).on("change select2:select"', script)


class GrantGovernanceAdminCommandTests(TestCase):
    def _formal_member(self, member_no: str, user=None):
        return create_member(member_no, role_name=ROLE_FORMAL_MEMBER, user=user)

    def test_grant_governance_admin_assigns_role_and_permission(self):
        user = get_user_model().objects.create_user(
            username="governance-admin-target",
            email="target@example.com",
            password="test-password",
        )
        member = self._formal_member("member-governance-admin-target", user=user)
        output = StringIO()

        call_command("grant_governance_admin", username=user.username, stdout=output)

        organization = Organization.objects.get(name=GOVERNANCE_ADMIN_ORGANIZATION_NAME)
        role = Role.objects.get(organization=organization, name=GOVERNANCE_ADMIN_ROLE_NAME)
        assignment = RoleAssignment.objects.get(member=member, role=role, status=RoleAssignment.Status.ACTIVE)
        self.assertTrue(
            SystemEvent.objects.filter(
                event_type=SystemEvent.EventType.ROLE_ASSIGNED,
                aggregate_type="RoleAssignment",
                aggregate_id=str(assignment.pk),
            ).exists()
        )
        self.assertTrue(user_has_governance_permission(user, GOVERNANCE_VIEW_ADMIN_PERMISSION))
        user.refresh_from_db()
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertIn("world_id=default", output.getvalue())

    def test_grant_governance_admin_is_idempotent_for_active_assignment(self):
        user = get_user_model().objects.create_user(username="repeat-admin", password="test-password")
        member = self._formal_member("member-repeat-admin", user=user)
        output = StringIO()

        call_command("grant_governance_admin", username=user.username, stdout=output)
        call_command("grant_governance_admin", username=user.username, stdout=output)

        organization = Organization.objects.get(name=GOVERNANCE_ADMIN_ORGANIZATION_NAME)
        role = Role.objects.get(organization=organization, name=GOVERNANCE_ADMIN_ROLE_NAME)
        assignments = RoleAssignment.objects.filter(member=member, role=role, status=RoleAssignment.Status.ACTIVE)
        self.assertEqual(assignments.count(), 1)
        self.assertEqual(
            SystemEvent.objects.filter(
                event_type=SystemEvent.EventType.ROLE_ASSIGNED,
                aggregate_type="RoleAssignment",
                aggregate_id=str(assignments.get().pk),
            ).count(),
            1,
        )

    def test_grant_governance_admin_fails_without_formal_member(self):
        user = get_user_model().objects.create_user(username="no-formal-admin", password="test-password")
        create_member("member-no-formal", user=user)
        with self.assertRaises(CommandError) as captured:
            call_command("grant_governance_admin", username=user.username, stdout=StringIO())
        self.assertIn("正式成员", str(captured.exception))

    def test_grant_governance_admin_reports_explicit_world_id(self):
        user = get_user_model().objects.create_user(username="world-admin-target", password="test-password")
        self._formal_member("member-world-admin-target", user=user)
        output = StringIO()

        call_command("grant_governance_admin", "--world-id", "simulation0001", username=user.username, stdout=output)

        self.assertIn("world_id=simulation0001", output.getvalue())

    @override_settings(WORLD_DATABASE_ROUTING_ENABLED=True)
    def test_grant_governance_admin_requires_world_when_routing_is_enabled(self):
        with self.assertRaises(CommandError) as captured:
            call_command("grant_governance_admin", username="requires-world", stdout=StringIO())

        self.assertIn("requires --world-id", str(captured.exception))

    def test_governance_permission_role_requires_formal_member(self):
        """A non-basic role with governance.* permissions cannot be granted without ROLE_FORMAL_MEMBER."""
        from core.exceptions import DomainError
        from core.role_assignment_services import create_role_assignment

        member = create_member("member-no-formal-gov-role")
        org = Organization.objects.create(name="自定义治理组")
        gov_role = Role.objects.create(organization=org, name="自定义管理员", status=Role.Status.ACTIVE)
        perm = Permission.objects.create(code="governance.custom", name="自定义治理权", category="governance")
        RolePermission.objects.create(role=gov_role, permission=perm, scope="global")
        with self.assertRaises(DomainError) as ctx:
            create_role_assignment(member=member, role=gov_role, source_type="direct")
        self.assertIn("正式成员", str(ctx.exception))

    def test_bootstrap_first_governance_member_fails_for_suspended_member(self):
        from core.exceptions import DomainError
        from core.role_assignment_services import bootstrap_first_governance_member

        member = create_member("susp-bootstrap-test", status=Member.Status.SUSPENDED, skip_role_validation=True)
        ra_count_before = RoleAssignment.objects.filter(member=member).count()
        with self.assertRaises(DomainError):
            bootstrap_first_governance_member(member)
        self.assertEqual(RoleAssignment.objects.filter(member=member).count(), ra_count_before)

    def test_bootstrap_first_governance_member_fails_for_exited_member(self):
        from core.exceptions import DomainError
        from core.role_assignment_services import bootstrap_first_governance_member

        member = create_member("exit-bootstrap-test", status=Member.Status.EXITED, skip_role_validation=True)
        ra_count_before = RoleAssignment.objects.filter(member=member).count()
        with self.assertRaises(DomainError):
            bootstrap_first_governance_member(member)
        self.assertEqual(RoleAssignment.objects.filter(member=member).count(), ra_count_before)
