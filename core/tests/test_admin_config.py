from __future__ import annotations

from decimal import Decimal

from django.contrib import admin as django_admin
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from core.admin import (
    LedgerEntryAdmin,
    MemberAdmin,
    PermissionAdmin,
    ProposalAdmin,
    ProposalExecutionAdmin,
    ProposalVoteAdmin,
    ResourceTransactionAdmin,
    RolePermissionAdmin,
)
from core.admin_identity import RolePermissionInline
from core.admin_proposals import ProposalExecutionInline, ProposalVoteInline
from simulation.admin_feedback import PlanChangeOperationAdmin, PlanChangeSetAdmin, PlanRevisionProposalAdmin
from simulation.admin_planning import PlanNodeAdmin, ProjectPlanAdmin
from simulation.admin_runs import SimulationTurnAdmin
from core.models import (
    CapacityAssessment,
    Event,
    LedgerEntry,
    Member,
    Organization,
    Permission,
    PlanChangeOperation,
    PlanChangeSet,
    PlanNode,
    PlanRevision,
    PlanRevisionProposal,
    Proposal,
    ProposalExecution,
    ProposalVote,
    ProjectPlan,
    Resource,
    ResourceTransaction,
    Role,
    RoleAssignment,
    RolePermission,
    Ruleset,
    SimulationRun,
    SimulationTurn,
)
from core.tests.helpers import create_member


class AdminConfigTests(TestCase):
    """验证 Django Admin 内部维护后台的高风险保护边界。"""

    def setUp(self) -> None:
        user_model = get_user_model()
        self.user = user_model.objects.create_superuser(
            username="admin",
            email="admin@example.test",
            password="password",
        )
        self.request = RequestFactory().get("/admin/")
        self.request.user = self.user
        self.site = AdminSite()
        self.now = timezone.now()
        self.member = create_member(
            member_no="mem-0001",
            status=Member.Status.ADMITTED,
            batch_id="batch-opening",
            joined_simulation_day=1,
            credit_floor=-300,
            profile={"satisfaction": 64},
            created_at=self.now,
        )
    def test_member_primary_key_becomes_readonly_after_creation(self) -> None:
        admin = MemberAdmin(Member, self.site)

        self.assertNotIn("member_no", admin.get_readonly_fields(self.request, None))
        self.assertIn("member_no", admin.get_readonly_fields(self.request, self.member))

    def test_member_kind_virtual_and_single_role_field_are_removed(self) -> None:
        field_names = {field.name for field in Member._meta.fields}

        self.assertNotIn("role", field_names)
        self.assertNotIn("kind", field_names)
        self.assertNotIn("is_virtual", field_names)
        self.assertEqual(RoleAssignment._meta.get_field("member").remote_field.model, Member)

    def test_member_admin_uses_role_assignments_instead_of_single_role_field(self) -> None:
        admin = MemberAdmin(Member, self.site)
        fieldset_fields = {
            field
            for _, fieldset in admin.fieldsets
            for field in fieldset["fields"]
        }

        self.assertIn("active_roles", admin.list_display)
        self.assertNotIn("role", admin.list_display)
        self.assertNotIn("role", admin.list_filter)
        self.assertNotIn("role", fieldset_fields)
        self.assertNotIn("kind", admin.list_display)
        self.assertNotIn("kind", admin.list_filter)
        self.assertNotIn("kind", fieldset_fields)
        self.assertNotIn("is_virtual", admin.list_display)
        self.assertNotIn("is_virtual", admin.list_filter)
        self.assertNotIn("is_virtual", fieldset_fields)

    def test_control_admin_index_exposes_bottom_data_business_models(self) -> None:
        app_list = django_admin.site.get_app_list(self.request)
        all_model_names = {
            model["object_name"]
            for app in app_list
            for model in app["models"]
        }

        self.assertIn("Member", all_model_names)
        self.assertIn("Role", all_model_names)
        self.assertIn("RoleAssignment", all_model_names)
        self.assertIn("Proposal", all_model_names)
        self.assertIn("Task", all_model_names)
        self.assertIn("Dispute", all_model_names)
        self.assertIn("Resource", all_model_names)
        self.assertIn("SupplierQuote", all_model_names)
        self.assertIn("ProjectPlan", all_model_names)
        self.assertIn("SimulationRun", all_model_names)

    def test_technical_admin_index_only_exposes_audit_and_configuration_models(self) -> None:
        app_list = django_admin.site.get_app_list(self.request)
        technical_group = next(app for app in app_list if app["app_label"] == "technical_admin")
        model_names = {model["object_name"] for model in technical_group["models"]}

        self.assertIn("SystemEvent", model_names)
        self.assertIn("LedgerEntry", model_names)
        self.assertNotIn("SimulationLab", model_names)
        self.assertNotIn("SimulationSnapshot", model_names)
        self.assertNotIn("SimulationSnapshotItem", model_names)
        self.assertNotIn("SimulationRunDisposition", model_names)
        self.assertNotIn("Proposal", model_names)
        self.assertNotIn("Task", model_names)
        self.assertNotIn("Dispute", model_names)

    def test_simulation_admin_index_exposes_simulation_archive_and_lab_models(self) -> None:
        app_list = django_admin.site.get_app_list(self.request)
        simulation_group = next(app for app in app_list if app["app_label"] == "simulation_admin")
        model_names = {model["object_name"] for model in simulation_group["models"]}

        self.assertIn("SimulationSnapshot", model_names)
        self.assertIn("SimulationSnapshotItem", model_names)
        self.assertIn("SimulationRunDisposition", model_names)
        self.assertIn("SimulationLab", model_names)
        self.assertNotIn("SystemEvent", model_names)
        self.assertNotIn("LedgerEntry", model_names)
        self.assertNotIn("SimulationRun", model_names)

        simulation_lab_link = next(model for model in simulation_group["models"] if model["object_name"] == "SimulationLab")
        self.assertEqual(simulation_lab_link["admin_url"], "/admin/simulation-lab/")

    def test_core_admin_app_index_exposes_business_models(self) -> None:
        app_list = django_admin.site.get_app_list(self.request, app_label="core")
        model_names = {
            model["object_name"]
            for app in app_list
            for model in app["models"]
        }

        self.assertIn("SystemEvent", model_names)
        self.assertIn("LedgerEntry", model_names)
        self.assertIn("Member", model_names)
        self.assertIn("Task", model_names)
        self.assertIn("Proposal", model_names)

    def test_permission_support_models_are_hidden_from_top_level_admin_menus(self) -> None:
        permission_admin = PermissionAdmin(Permission, self.site)
        role_permission_admin = RolePermissionAdmin(RolePermission, self.site)

        self.assertEqual(permission_admin.get_model_perms(self.request), {})
        self.assertEqual(role_permission_admin.get_model_perms(self.request), {})

    def test_role_permissions_are_readonly_history_in_admin(self) -> None:
        organization = Organization.objects.create(name="Governance", status=Organization.Status.ACTIVE)
        role = Role.objects.create(organization=organization, name="Reviewer", status=Role.Status.ACTIVE)
        permission = Permission.objects.create(
            code="governance.review",
            name="Review",
            category="governance",
            description="Review governance records.",
        )
        role_permission = RolePermission.objects.create(
            role=role,
            permission=permission,
            scope="global",
            constraints_json={"level": "standard"},
        )
        role_permission_admin = RolePermissionAdmin(RolePermission, self.site)
        role_permission_inline = RolePermissionInline(Role, self.site)

        self.assertFalse(role_permission_admin.has_add_permission(self.request))
        self.assertFalse(role_permission_admin.has_change_permission(self.request, role_permission))
        self.assertFalse(role_permission_admin.has_delete_permission(self.request, role_permission))
        self.assertIn("constraints_json", role_permission_admin.get_readonly_fields(self.request, role_permission))
        self.assertFalse(role_permission_inline.has_add_permission(self.request, role))
        self.assertFalse(role_permission_inline.has_delete_permission(self.request, role))
        self.assertIn("constraints_json", role_permission_inline.get_readonly_fields(self.request, role))

    def test_project_plan_and_nodes_are_editable_but_not_deletable(self) -> None:
        plan = ProjectPlan.objects.create(
            plan_id="plan-bigapple001",
            name="bigapple001据点执行计划",
            status=ProjectPlan.Status.ACTIVE,
            description="测试计划",
            target_location="bigapple001据点",
            created_at=self.now,
        )
        revision = PlanRevision.objects.create(
            revision_id="plan-bigapple001-rev-v0_1_0",
            plan=plan,
            revision_code="v0.1.0",
            status=PlanRevision.Status.PUBLISHED,
            title="测试版本",
            change_summary="测试计划版本",
            created_at=self.now,
            published_at=self.now,
        )
        node = PlanNode.objects.create(
            node_id="node-bigapple001-b1",
            revision=revision,
            sequence=10,
            code="B1",
            title="建立临时公共食堂",
            node_type=PlanNode.NodeType.WORK_PACKAGE,
            status=PlanNode.Status.IN_PROGRESS,
            planned_duration_days=5,
            created_at=self.now,
        )
        plan_admin = ProjectPlanAdmin(ProjectPlan, self.site)
        node_admin = PlanNodeAdmin(PlanNode, self.site)

        self.assertTrue(plan_admin.has_change_permission(self.request, plan))
        self.assertFalse(plan_admin.has_delete_permission(self.request, plan))
        self.assertIn("plan_id", plan_admin.get_readonly_fields(self.request, plan))
        self.assertTrue(node_admin.has_change_permission(self.request, node))
        self.assertFalse(node_admin.has_delete_permission(self.request, node))
        self.assertIn("node_id", node_admin.get_readonly_fields(self.request, node))

    def test_ledger_entries_are_readonly_history(self) -> None:
        entry = LedgerEntry.objects.create(
            ledger_entry_id="ledger-0001",
            member=self.member,
            amount=20,
            entry_type=LedgerEntry.EntryType.CONTRIBUTION,
            reason="测试流水",
            rule_version="ruleset-v0.1.0",
            created_at=self.now,
            created_by={"actor_id": "admin"},
            reviewer={"actor_id": "admin"},
            status=LedgerEntry.Status.POSTED,
        )
        admin = LedgerEntryAdmin(LedgerEntry, self.site)

        self.assertFalse(admin.has_add_permission(self.request))
        self.assertFalse(admin.has_change_permission(self.request, entry))
        self.assertFalse(admin.has_delete_permission(self.request, entry))
        self.assertIn("system_event", admin.get_readonly_fields(self.request, entry))

    def test_proposal_votes_and_executions_are_readonly_history(self) -> None:
        proposal = Proposal.objects.create(
            title="Admin history proposal",
            proposal_type=Proposal.ProposalType.POLICY,
            status=Proposal.Status.VOTING,
            proposer_member=self.member,
            deadline_at=self.now + timezone.timedelta(days=7),
        )
        vote = ProposalVote.objects.create(
            proposal=proposal,
            voter_member=self.member,
            choice=ProposalVote.Choice.YES,
            reason="Admin history vote",
            voted_at=self.now,
        )
        execution = ProposalExecution.objects.create(
            proposal=proposal,
            executor_member=self.member,
            action_type=ProposalExecution.ActionType.MANUAL,
            status=ProposalExecution.Status.SUCCEEDED,
            payload_json={"action": "manual"},
            result_json={"ok": True},
            executed_at=self.now,
        )
        proposal_admin = ProposalAdmin(Proposal, self.site)
        vote_admin = ProposalVoteAdmin(ProposalVote, self.site)
        execution_admin = ProposalExecutionAdmin(ProposalExecution, self.site)

        self.assertTrue(proposal_admin.has_add_permission(self.request))
        self.assertFalse(proposal_admin.has_change_permission(self.request, proposal))
        self.assertFalse(vote_admin.has_add_permission(self.request))
        self.assertFalse(vote_admin.has_change_permission(self.request, vote))
        self.assertFalse(vote_admin.has_delete_permission(self.request, vote))
        self.assertIn("choice", vote_admin.get_readonly_fields(self.request, vote))
        self.assertFalse(execution_admin.has_add_permission(self.request))
        self.assertFalse(execution_admin.has_change_permission(self.request, execution))
        self.assertFalse(execution_admin.has_delete_permission(self.request, execution))
        self.assertIn("status", execution_admin.get_readonly_fields(self.request, execution))

        vote_inline = ProposalVoteInline(Proposal, self.site)
        execution_inline = ProposalExecutionInline(Proposal, self.site)
        self.assertFalse(vote_inline.has_add_permission(self.request, proposal))
        self.assertFalse(vote_inline.has_delete_permission(self.request, proposal))
        self.assertIn("choice", vote_inline.get_readonly_fields(self.request, proposal))
        self.assertIn("reason", vote_inline.get_readonly_fields(self.request, proposal))
        self.assertFalse(execution_inline.has_add_permission(self.request, proposal))
        self.assertFalse(execution_inline.has_delete_permission(self.request, proposal))
        self.assertIn("status", execution_inline.get_readonly_fields(self.request, proposal))
        self.assertIn("payload_json", execution_inline.get_readonly_fields(self.request, proposal))

    def test_resource_transactions_are_readonly_history(self) -> None:
        resource = Resource.objects.create(
            resource_id="res-admin-tx",
            resource_type=Resource.ResourceType.TOOLS,
            unit=Resource.Unit.COUNT,
            current_stock=Decimal("3"),
            daily_consumption_estimate=Decimal("1"),
            replenishment_method=Resource.ReplenishmentMethod.PURCHASE,
            loss_rate=Decimal("0.00000"),
            warning_threshold=Decimal("1"),
            shortage_impact={},
            updated_at=self.now,
            rule_version="ruleset-v0.1.0",
        )
        transaction = ResourceTransaction.objects.create(
            transaction_id="res-tx-admin-0001",
            resource=resource,
            transaction_type=ResourceTransaction.TransactionType.INBOUND,
            quantity_delta=Decimal("2"),
            stock_before=Decimal("1"),
            stock_after=Decimal("3"),
            reason="测试库存流水。",
            operator={"actor_id": "admin"},
            occurred_at=self.now,
            created_at=self.now,
        )
        admin = ResourceTransactionAdmin(ResourceTransaction, self.site)

        self.assertFalse(admin.has_add_permission(self.request))
        self.assertFalse(admin.has_change_permission(self.request, transaction))
        self.assertFalse(admin.has_delete_permission(self.request, transaction))
        self.assertIn("system_event", admin.get_readonly_fields(self.request, transaction))

    def test_business_events_and_capacity_assessments_are_not_registered_in_django_admin(self) -> None:
        capacity = CapacityAssessment.objects.create(
            assessment_id="capacity-0001",
            simulation_day=1,
            current_formal_members=10,
            current_candidate_members=20,
            maximum_admissible_members=12,
            recommended_new_members=2,
            bottlenecks=[],
            risk_indicators={},
            reasons=[],
            rule_version="ruleset-v0.1.0",
            created_at=self.now,
        )

        self.assertNotIn(Event, django_admin.site._registry)
        self.assertNotIn(CapacityAssessment, django_admin.site._registry)
        self.assertEqual(capacity.assessment_id, "capacity-0001")

    def test_rulesets_are_not_registered_in_django_admin(self) -> None:
        ruleset = Ruleset.objects.create(
            ruleset_id="ruleset-v0_1_0",
            version="ruleset-v0.1.0",
            status=Ruleset.Status.ACTIVE,
            effective_from=self.now.date(),
            negative_point_floor={"ordinary_member": -300},
            task_point_rules=[{"task_type": "cooking", "base_points": 30}],
            created_at=self.now,
            created_by={"actor_id": "admin"},
            change_summary="测试规则版本",
            metadata={"seed": True},
        )

        self.assertNotIn(Ruleset, django_admin.site._registry)
        self.assertEqual(ruleset.version, "ruleset-v0.1.0")

    def test_simulation_history_is_readonly_but_proposal_status_is_editable(self) -> None:
        plan = ProjectPlan.objects.create(
            plan_id="plan-bigapple001",
            name="bigapple001据点执行计划",
            status=ProjectPlan.Status.ACTIVE,
            description="测试计划",
            target_location="bigapple001据点",
            created_at=self.now,
        )
        revision = PlanRevision.objects.create(
            revision_id="plan-bigapple001-rev-v0_1_0",
            plan=plan,
            revision_code="v0.1.0",
            status=PlanRevision.Status.PUBLISHED,
            title="测试版本",
            change_summary="测试计划版本",
            created_at=self.now,
            published_at=self.now,
        )
        run = SimulationRun.objects.create(
            run_id="sim-run-0001",
            plan_revision=revision,
            status=SimulationRun.Status.FAILED,
            current_day=12,
            max_turns=30,
            started_at=self.now,
            ended_at=self.now,
            failure_summary="技能不足。",
        )
        turn = SimulationTurn.objects.create(
            turn_id="turn-0001",
            run=run,
            turn_number=1,
            simulation_day=12,
            summary="测试推进日志。",
            occurred_at=self.now,
        )
        proposal = PlanRevisionProposal.objects.create(
            proposal_id="proposal-0001",
            run=run,
            plan_revision=revision,
            proposal_type=PlanRevisionProposal.ProposalType.ADD_REQUIREMENT,
            status=PlanRevisionProposal.Status.DRAFT,
            title="补充技能要求",
            rationale="技能不足。",
            suggested_changes={"missing_skills": ["光伏"]},
            created_at=self.now,
        )
        change_set = PlanChangeSet.objects.create(
            change_set_id="changeset-0001",
            run=run,
            proposal=proposal,
            plan_revision=revision,
            status=PlanChangeSet.Status.DRAFT,
            title="结构化变更",
            summary="测试结构化变更。",
            created_at=self.now,
        )
        operation = PlanChangeOperation.objects.create(
            operation_id="changeop-0001",
            change_set=change_set,
            sequence=10,
            operation_type=PlanChangeOperation.OperationType.ADD_NODE,
            target_model="PlanNode",
            target_id="",
            target_field="",
            old_value={},
            new_value={"code": "C3-SKILL"},
            rationale="测试结构化操作。",
        )

        turn_admin = SimulationTurnAdmin(SimulationTurn, self.site)
        proposal_admin = PlanRevisionProposalAdmin(PlanRevisionProposal, self.site)
        change_set_admin = PlanChangeSetAdmin(PlanChangeSet, self.site)
        operation_admin = PlanChangeOperationAdmin(PlanChangeOperation, self.site)

        self.assertFalse(turn_admin.has_add_permission(self.request))
        self.assertFalse(turn_admin.has_change_permission(self.request, turn))
        self.assertFalse(turn_admin.has_delete_permission(self.request, turn))
        self.assertFalse(proposal_admin.has_add_permission(self.request))
        self.assertTrue(proposal_admin.has_change_permission(self.request, proposal))
        self.assertFalse(proposal_admin.has_delete_permission(self.request, proposal))
        self.assertFalse(change_set_admin.has_add_permission(self.request))
        self.assertTrue(change_set_admin.has_change_permission(self.request, change_set))
        self.assertFalse(change_set_admin.has_delete_permission(self.request, change_set))
        self.assertNotIn("apply_as_plan_revision", change_set_admin.get_actions(self.request))
        self.assertFalse(operation_admin.has_add_permission(self.request))
        self.assertFalse(operation_admin.has_change_permission(self.request, operation))
        self.assertFalse(operation_admin.has_delete_permission(self.request, operation))

    def test_role_assignment_admin_has_add_permission_false(self) -> None:
        from core.admin_identity import RoleAssignmentAdmin
        admin_instance = RoleAssignmentAdmin(RoleAssignment, self.site)
        self.assertFalse(admin_instance.has_add_permission(self.request))

    def test_role_assignment_admin_readonly_fields(self) -> None:
        from core.admin_identity import RoleAssignmentAdmin
        admin_instance = RoleAssignmentAdmin(RoleAssignment, self.site)
        protected = {"member", "role", "status", "source_type", "granted_by", "revoked_by"}
        for field in protected:
            self.assertIn(field, admin_instance.readonly_fields, f"{field} must be readonly in RoleAssignmentAdmin")

    def test_member_role_assignment_inline_has_add_permission_false(self) -> None:
        from core.admin_identity import MemberRoleAssignmentInline
        inline = MemberRoleAssignmentInline(Member, self.site)
        self.assertFalse(inline.has_add_permission(self.request))

    def test_role_assignment_inline_has_add_permission_false(self) -> None:
        from core.admin_identity import RoleAssignmentInline
        inline = RoleAssignmentInline(Role, self.site)
        self.assertFalse(inline.has_add_permission(self.request))

    def test_credential_template_admin_has_add_permission_false(self) -> None:
        from core.admin_identity import CredentialTemplateAdmin
        from core.models import CredentialTemplate
        admin_instance = CredentialTemplateAdmin(CredentialTemplate, self.site)
        self.assertFalse(admin_instance.has_add_permission(self.request))

    def test_credential_template_admin_readonly_fields_contains_all_model_fields(self) -> None:
        from core.admin_identity import CredentialTemplateAdmin
        from core.admin_support import model_field_names
        from core.models import CredentialTemplate
        admin_instance = CredentialTemplateAdmin(CredentialTemplate, self.site)
        all_fields = set(model_field_names(CredentialTemplate))
        readonly = set(admin_instance.readonly_fields)
        self.assertEqual(all_fields, readonly, "All CredentialTemplate fields must be readonly")

    def test_credential_grant_admin_has_add_permission_false(self) -> None:
        from core.admin_identity import CredentialGrantAdmin
        from core.models import CredentialGrant
        admin_instance = CredentialGrantAdmin(CredentialGrant, self.site)
        self.assertFalse(admin_instance.has_add_permission(self.request))

    def test_credential_grant_admin_has_delete_permission_false(self) -> None:
        from core.admin_identity import CredentialGrantAdmin
        from core.models import CredentialGrant
        admin_instance = CredentialGrantAdmin(CredentialGrant, self.site)
        self.assertFalse(admin_instance.has_delete_permission(self.request))

    def test_finance_admins_are_readonly(self) -> None:
        from core.admin_finance import ExpenseClaimAdmin, FinanceReviewAdmin, FinanceTransactionAdmin
        from core.admin_support import model_field_names
        from core.models import ExpenseClaim, FinanceReview, FinanceTransaction

        for model, admin_class in (
            (ExpenseClaim, ExpenseClaimAdmin),
            (FinanceReview, FinanceReviewAdmin),
            (FinanceTransaction, FinanceTransactionAdmin),
        ):
            admin_instance = admin_class(model, self.site)
            self.assertFalse(admin_instance.has_add_permission(self.request))
            self.assertFalse(admin_instance.has_delete_permission(self.request))
            self.assertEqual(set(model_field_names(model)), set(admin_instance.readonly_fields))
