from __future__ import annotations

from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.member_roles import ROLE_CONTRIBUTOR
from core.models import (
    CapacityAssessment,
    Event,
    LedgerEntry,
    Member,
    PlanChangeOperation,
    PlanChangeSet,
    PlanDependency,
    PlanNode,
    PlanNodeRunState,
    PlanRevision,
    PlanRevisionProposal,
    ProjectPlan,
    Resource,
    SimulationFailure,
    SimulationRun,
    SimulationTurn,
    Task,
)
from simulation.engine import run_active_plan_until_failure
from simulation.responsibility_closure import RESPONSIBILITY_DOCUMENTS_KEY, photovoltaic_responsibility_closure_requirements
from core.tests.helpers import create_governance_admin_member, create_member, login_as_member


class SimulationPlanFeedbackTests(TestCase):
    """验证自动模拟可以按主线推进、失败，并生成计划修订建议。"""

    def setUp(self) -> None:
        now = timezone.now()
        self.governance_member = create_governance_admin_member(
            member_no="member-admin-0001",
            status=Member.Status.ACTIVE,
            joined_simulation_day=1,
            credit_floor=-500,
            profile={"display_name": "开荒队治理成员"},
            created_at=now,
        )
        create_member(
            member_no="mem-0001",
            role_name=ROLE_CONTRIBUTOR,
            status=Member.Status.ADMITTED,
            joined_simulation_day=1,
            credit_floor=-300,
            profile={"skills": {"厨房建设": 80, "食品安全": 72, "光伏": 90, "电气": 88, "结构": 86}},
            created_at=now,
        )
        CapacityAssessment.objects.create(
            assessment_id="capacity-0001",
            simulation_day=3,
            current_formal_members=10,
            current_candidate_members=0,
            maximum_admissible_members=12,
            recommended_new_members=0,
            bottlenecks=[],
            risk_indicators={"average_fatigue": 40},
            reasons=["测试自动模拟。"],
            rule_version="ruleset-v0.1.0",
            created_at=now,
        )
        Resource.objects.create(
            resource_id="res-cash",
            resource_type=Resource.ResourceType.CASH,
            unit=Resource.Unit.YUAN,
            current_stock=Decimal("10000.000"),
            daily_consumption_estimate=Decimal("0.000"),
            replenishment_method=Resource.ReplenishmentMethod.MANUAL_ADJUSTMENT,
            loss_rate=Decimal("0.00000"),
            warning_threshold=Decimal("1000.000"),
            shortage_impact={},
            updated_at=now,
            rule_version="ruleset-v0.1.0",
        )
        plan = ProjectPlan.objects.create(
            plan_id="plan-bigapple001",
            name="bigapple001据点执行计划",
            status=ProjectPlan.Status.ACTIVE,
            description="测试计划。",
            target_location="bigapple001据点",
            created_at=now,
            updated_at=now,
        )
        revision = PlanRevision.objects.create(
            revision_id="plan-bigapple001-rev-v0_1_0",
            plan=plan,
            revision_code="v0.1.0",
            status=PlanRevision.Status.PUBLISHED,
            title="测试计划版本",
            change_summary="用于自动模拟测试。",
            created_at=now,
            published_at=now,
        )
        self.canteen = PlanNode.objects.create(
            node_id="node-bigapple001-b1",
            revision=revision,
            sequence=10,
            code="B1",
            title="建立临时公共食堂",
            node_type=PlanNode.NodeType.WORK_PACKAGE,
            status=PlanNode.Status.PLANNED,
            planned_duration_days=2,
            estimated_cost_expected=Decimal("1000.00"),
            required_people_min=2,
            required_people_max=4,
            required_person_days=Decimal("8.00"),
            required_skills=["厨房建设"],
            completion_criteria=["可供餐"],
            created_at=now,
            updated_at=now,
        )
        self.pv = PlanNode.objects.create(
            node_id="node-bigapple001-c3",
            revision=revision,
            sequence=20,
            code="C3",
            title="光伏一期 0.5MW",
            node_type=PlanNode.NodeType.EXPANSION,
            status=PlanNode.Status.PLANNED,
            planned_duration_days=21,
            estimated_cost_expected=Decimal("2000.00"),
            required_people_min=2,
            required_people_max=6,
            required_person_days=Decimal("60.00"),
            required_skills=[],
            completion_criteria=["装机完成"],
            metadata={
                "required_responsibility_closures": photovoltaic_responsibility_closure_requirements(),
                RESPONSIBILITY_DOCUMENTS_KEY: [],
            },
            created_at=now,
            updated_at=now,
        )
        PlanDependency.objects.create(
            dependency_id="dep-b1-c3",
            revision=revision,
            node=self.pv,
            depends_on=self.canteen,
            dependency_type=PlanDependency.DependencyType.FINISH_TO_START,
            description="先完成食堂，再启动光伏。",
        )

    def valid_responsibility_documents(self) -> list[dict[str, object]]:
        return [
            {
                "closure_code": requirement["code"],
                "issuer": f"{requirement['label']}出具主体",
                "document_name": f"{requirement['label']}归档文件",
                "signed_or_sealed": True,
                "clear_conclusion": True,
                "applicable_to_current_site": True,
                "applicable_to_current_scale": True,
                "restrictions_converted_to_constraints": True,
            }
            for requirement in photovoltaic_responsibility_closure_requirements()
        ]

    def test_auto_run_fails_on_missing_responsibility_closure_and_generates_revision_proposal(self) -> None:
        result = run_active_plan_until_failure(max_turns=5)
        run = result["run"]

        self.assertEqual(run.status, SimulationRun.Status.FAILED)
        self.assertEqual(run.metadata["source"], "observer_auto_run")
        canteen_state = PlanNodeRunState.objects.get(run=run, plan_node=self.canteen)
        pv_state = PlanNodeRunState.objects.get(run=run, plan_node=self.pv)
        self.assertEqual(canteen_state.status, PlanNodeRunState.Status.COMPLETED)
        self.assertEqual(pv_state.status, PlanNodeRunState.Status.FAILED)

        failure = SimulationFailure.objects.get(run=run)
        self.assertEqual(failure.failure_type, SimulationFailure.FailureType.RESPONSIBILITY_CLOSURE_MISSING)
        self.assertIn("责任闭环", failure.description)
        self.assertIn("结构/建筑安全责任文件", failure.description)
        self.assertEqual(len(failure.metadata["missing_responsibility_closures"]), 5)

        proposal = PlanRevisionProposal.objects.get(run=run)
        self.assertEqual(proposal.proposal_type, PlanRevisionProposal.ProposalType.ADD_REQUIREMENT)
        self.assertEqual(proposal.status, PlanRevisionProposal.Status.DRAFT)
        self.assertIn("责任主体和责任文件", proposal.suggested_changes["change"])
        self.assertIn("C3-GRID-PRESCREEN", proposal.suggested_changes["recommended_predecessor_nodes"])

        change_set = PlanChangeSet.objects.get(proposal=proposal)
        self.assertEqual(change_set.status, PlanChangeSet.Status.DRAFT)
        operations = list(PlanChangeOperation.objects.filter(change_set=change_set).order_by("sequence"))
        operation_types = [operation.operation_type for operation in operations]
        self.assertEqual(operation_types.count(PlanChangeOperation.OperationType.ADD_NODE), 7)
        self.assertEqual(operation_types.count(PlanChangeOperation.OperationType.ADD_DEPENDENCY), 7)
        self.assertEqual(operation_types.count(PlanChangeOperation.OperationType.ADD_REQUIREMENT), 5)
        self.assertEqual(
            [operation.new_value["code"] for operation in operations if operation.operation_type == PlanChangeOperation.OperationType.ADD_NODE],
            [
                "C3-GRID-PRESCREEN",
                "C3-LEASE-REVIEW",
                "C3-STRUCTURE-DOC",
                "C3-PV-DESIGN-DOC",
                "C3-GRID-DOC",
                "C3-CONSTRUCTION-QA",
                "C3-ACCEPTANCE-ARCHIVE",
            ],
        )
        dependency_descriptions = [
            operation.new_value["description"]
            for operation in operations
            if operation.operation_type == PlanChangeOperation.OperationType.ADD_DEPENDENCY
        ]
        self.assertTrue(all("C3 启动前必须完成" in description for description in dependency_descriptions))

        self.assertGreaterEqual(SimulationTurn.objects.filter(run=run).count(), 2)
        event = Event.objects.get(
            generated_by=Event.GeneratedBy.SIMULATION_ENGINE,
            simulation_run=run,
            payload__run_id=run.run_id,
            payload__failure_id=failure.failure_id,
            payload__change_set_id=change_set.change_set_id,
        )
        self.assertEqual(event.simulation_run, run)
        self.canteen.refresh_from_db()
        self.pv.refresh_from_db()
        self.assertEqual(self.canteen.status, PlanNode.Status.PLANNED)
        self.assertEqual(self.pv.status, PlanNode.Status.PLANNED)
        self.assertEqual(Resource.objects.get(resource_id="res-cash").current_stock, Decimal("10000.000"))
        self.assertFalse(LedgerEntry.objects.exists())
        self.assertFalse(Task.objects.exists())
        self.assertEqual(Member.objects.get(member_no="member-admin-0001").status, Member.Status.ACTIVE)
        self.assertEqual(Member.objects.get(member_no="mem-0001").status, Member.Status.ADMITTED)

    def test_auto_run_can_pass_c3_after_responsibility_documents_are_complete(self) -> None:
        self.pv.metadata = {
            **self.pv.metadata,
            RESPONSIBILITY_DOCUMENTS_KEY: self.valid_responsibility_documents(),
        }
        self.pv.save(update_fields=["metadata"])

        result = run_active_plan_until_failure(max_turns=5)
        run = result["run"]

        self.assertEqual(run.status, SimulationRun.Status.COMPLETED)
        self.assertFalse(SimulationFailure.objects.filter(run=run).exists())
        self.assertEqual(PlanNodeRunState.objects.get(run=run, plan_node=self.pv).status, PlanNodeRunState.Status.COMPLETED)

    def test_simulation_engine_event_requires_run(self) -> None:
        with self.assertRaisesMessage(ValueError, "Simulation-generated Event records must be linked"):
            Event.objects.create(
                event_id="event-sim-unscoped",
                event_type=Event.EventType.SIMULATION_DAY,
                simulation_day=1,
                severity=Event.Severity.INFO,
                title="未绑定仿真运行",
                summary="这条事件不应被允许写入。",
                occurred_at=timezone.now(),
                generated_by=Event.GeneratedBy.SIMULATION_ENGINE,
                visibility=Event.Visibility.PUBLIC,
                payload={},
            )

    def test_admin_simulation_lab_can_start_auto_run_without_redirecting_to_observer(self) -> None:
        user = login_as_member(self.client, self.governance_member, is_staff=True)
        user.is_superuser = True
        user.save(update_fields=["is_superuser"])
        response = self.client.post("/admin/simulation-lab/run-until-failure/", {"max_turns": "5"}, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "仿真实验后台")
        self.assertContains(response, "仿真运行")
        self.assertContains(response, "启动门槛仍未满足")
        self.assertNotContains(response, "今日事件时间线（实时指挥）")
