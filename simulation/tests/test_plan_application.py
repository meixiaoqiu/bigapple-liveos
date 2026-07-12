from __future__ import annotations

from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.exceptions import DomainError
from core.models import (
    PlanCapacityImpact,
    PlanChangeOperation,
    PlanChangeSet,
    PlanDependency,
    PlanNode,
    PlanRequirement,
    PlanRevision,
    PlanRevisionProposal,
    ProjectPlan,
    SimulationRun,
)
from simulation.plan_application import apply_plan_change_set


class PlanChangeSetApplicationTests(TestCase):
    """PlanChangeSet 应用必须复制并强化现有 PlanRevision 体系。"""

    def setUp(self) -> None:
        self.now = timezone.now()
        self.plan = ProjectPlan.objects.create(
            plan_id="plan-apply",
            name="计划应用测试",
            status=ProjectPlan.Status.ACTIVE,
            description="测试计划。",
            target_location="测试据点",
            created_at=self.now,
            updated_at=self.now,
        )
        self.revision = PlanRevision.objects.create(
            revision_id="plan-apply-rev-v0_0_1",
            plan=self.plan,
            revision_code="v0.0.1",
            status=PlanRevision.Status.PUBLISHED,
            title="源计划版本",
            change_summary="源版本。",
            created_at=self.now,
            published_at=self.now,
        )
        self.node_a = PlanNode.objects.create(
            node_id="node-apply-a",
            revision=self.revision,
            sequence=10,
            code="A",
            title="源节点 A",
            node_type=PlanNode.NodeType.STAGE,
            status=PlanNode.Status.PLANNED,
            planned_duration_days=3,
            estimated_cost_expected=Decimal("100.00"),
            required_people_min=1,
            required_people_max=2,
            required_person_days=Decimal("3.00"),
            created_at=self.now,
            updated_at=self.now,
        )
        self.node_b = PlanNode.objects.create(
            node_id="node-apply-b",
            revision=self.revision,
            parent=self.node_a,
            sequence=20,
            code="B",
            title="源节点 B",
            node_type=PlanNode.NodeType.WORK_PACKAGE,
            status=PlanNode.Status.PLANNED,
            planned_duration_days=5,
            estimated_cost_expected=Decimal("200.00"),
            required_people_min=2,
            required_people_max=4,
            required_person_days=Decimal("10.00"),
            required_skills=["施工"],
            created_at=self.now,
            updated_at=self.now,
        )
        self.dependency = PlanDependency.objects.create(
            dependency_id="dep-apply-a-b",
            revision=self.revision,
            node=self.node_b,
            depends_on=self.node_a,
            dependency_type=PlanDependency.DependencyType.FINISH_TO_START,
            description="A 完成后启动 B。",
        )
        self.requirement = PlanRequirement.objects.create(
            requirement_id="req-apply-a-budget",
            node=self.node_a,
            requirement_type=PlanRequirement.RequirementType.BUDGET,
            name="启动预算",
            quantity=Decimal("100.000"),
            unit="元",
            unit_cost=Decimal("1.00"),
            total_cost_estimate=Decimal("100.00"),
            is_must=True,
            notes="源需求。",
        )
        self.impact = PlanCapacityImpact.objects.create(
            impact_id="impact-apply-b-member",
            node=self.node_b,
            impact_type=PlanCapacityImpact.ImpactType.MEMBER_CAPACITY,
            delta=Decimal("5.000"),
            unit="人",
            description="源容量影响。",
        )
        self.run = SimulationRun.objects.create(
            run_id="sim-run-apply",
            plan_revision=self.revision,
            status=SimulationRun.Status.FAILED,
            current_day=1,
            max_turns=1,
            started_at=self.now,
            ended_at=self.now,
            failure_summary="测试失败。",
        )
        self.proposal = PlanRevisionProposal.objects.create(
            proposal_id="proposal-apply",
            run=self.run,
            plan_revision=self.revision,
            proposal_type=PlanRevisionProposal.ProposalType.ADD_NODE,
            status=PlanRevisionProposal.Status.DRAFT,
            title="测试修订建议",
            rationale="测试需要。",
            suggested_changes={},
            created_at=self.now,
        )

    def create_change_set(self, change_set_id: str = "changeset-apply") -> PlanChangeSet:
        return PlanChangeSet.objects.create(
            change_set_id=change_set_id,
            run=self.run,
            proposal=self.proposal,
            plan_revision=self.revision,
            status=PlanChangeSet.Status.DRAFT,
            title="测试结构化变更",
            summary="测试应用计划变更。",
            created_at=self.now,
        )

    def create_operation(
        self,
        change_set: PlanChangeSet,
        *,
        sequence: int,
        operation_type: str,
        target_model: str,
        new_value: dict,
        target_id: str = "",
        target_field: str = "",
        is_required: bool = True,
    ) -> PlanChangeOperation:
        return PlanChangeOperation.objects.create(
            operation_id=f"changeop-{change_set.change_set_id}-{sequence}",
            change_set=change_set,
            sequence=sequence,
            operation_type=operation_type,
            target_model=target_model,
            target_id=target_id,
            target_field=target_field,
            old_value={},
            new_value=new_value,
            rationale="测试操作。",
            is_required=is_required,
        )

    def test_apply_copies_source_revision_without_mutating_it(self) -> None:
        change_set = self.create_change_set()
        self.create_operation(
            change_set,
            sequence=10,
            operation_type=PlanChangeOperation.OperationType.NOTE,
            target_model="PlanRevision",
            new_value={"note": "只记录说明。"},
            is_required=False,
        )

        new_revision = apply_plan_change_set(change_set, actor="tester")

        self.assertNotEqual(new_revision.revision_id, self.revision.revision_id)
        self.assertEqual(new_revision.revision_code, "v0.0.2")
        self.assertEqual(new_revision.status, PlanRevision.Status.DRAFT)
        self.assertEqual(PlanNode.objects.filter(revision=self.revision).count(), 2)
        copied_nodes = {node.code: node for node in PlanNode.objects.filter(revision=new_revision)}
        self.assertEqual(set(copied_nodes), {"A", "B"})
        self.assertNotEqual(copied_nodes["A"].node_id, self.node_a.node_id)
        self.assertEqual(copied_nodes["B"].parent, copied_nodes["A"])

        copied_dependency = PlanDependency.objects.get(revision=new_revision)
        self.assertEqual(copied_dependency.node, copied_nodes["B"])
        self.assertEqual(copied_dependency.depends_on, copied_nodes["A"])
        self.assertEqual(PlanRequirement.objects.get(node=copied_nodes["A"]).name, self.requirement.name)
        self.assertEqual(PlanCapacityImpact.objects.get(node=copied_nodes["B"]).delta, self.impact.delta)

        change_set.refresh_from_db()
        self.assertEqual(change_set.status, PlanChangeSet.Status.APPLIED)
        self.assertEqual(change_set.applied_revision, new_revision)
        self.assertIsNotNone(change_set.applied_at)
        self.assertEqual(change_set.metadata["application_result"]["notes"][0]["note"], "只记录说明。")

    def test_apply_rejects_malformed_required_operation_before_creating_revision(self) -> None:
        change_set = self.create_change_set("changeset-malformed")
        self.create_operation(
            change_set,
            sequence=10,
            operation_type=PlanChangeOperation.OperationType.ADD_NODE,
            target_model="PlanNode",
            new_value={"scenario": "zero_start"},
        )

        with self.assertRaisesMessage(DomainError, "缺少必填字段：code"):
            apply_plan_change_set(change_set, publish=True)

        self.assertEqual(PlanRevision.objects.filter(plan=self.plan).count(), 1)
        change_set.refresh_from_db()
        self.assertEqual(change_set.status, PlanChangeSet.Status.DRAFT)

    def test_apply_operations_add_and_update_only_new_revision_nodes(self) -> None:
        change_set = self.create_change_set("changeset-apply-ops")
        self.create_operation(
            change_set,
            sequence=10,
            operation_type=PlanChangeOperation.OperationType.ADD_NODE,
            target_model="PlanNode",
            new_value={
                "code": "C",
                "title": "新增节点 C",
                "node_type": PlanNode.NodeType.WORK_PACKAGE,
                "planned_duration_days": 2,
                "estimated_cost_expected": "300.00",
                "requirements": [
                    {
                        "requirement_type": PlanRequirement.RequirementType.SKILL,
                        "name": "节点内嵌技能需求",
                        "quantity": 1,
                        "unit": "项",
                    }
                ],
            },
        )
        self.create_operation(
            change_set,
            sequence=20,
            operation_type=PlanChangeOperation.OperationType.ADD_DEPENDENCY,
            target_model="PlanDependency",
            new_value={
                "node_id": self.node_b.node_id,
                "depends_on_code": "C",
                "dependency_type": PlanDependency.DependencyType.FINISH_TO_START,
                "description": "C 完成后启动 B。",
            },
        )
        self.create_operation(
            change_set,
            sequence=30,
            operation_type=PlanChangeOperation.OperationType.ADD_REQUIREMENT,
            target_model="PlanRequirement",
            new_value={
                "node_code": "C",
                "requirement_type": PlanRequirement.RequirementType.MATERIAL,
                "name": "新增节点材料",
                "quantity": 2,
                "unit": "套",
            },
        )
        self.create_operation(
            change_set,
            sequence=40,
            operation_type=PlanChangeOperation.OperationType.ADD_REQUIREMENT,
            target_model="PlanRequirement",
            new_value={
                "node_id": self.node_a.node_id,
                "requirement_type": PlanRequirement.RequirementType.PERMIT,
                "name": "已有节点许可",
                "quantity": 1,
                "unit": "份",
            },
        )
        self.create_operation(
            change_set,
            sequence=50,
            operation_type=PlanChangeOperation.OperationType.ADD_CAPACITY_IMPACT,
            target_model="PlanCapacityImpact",
            new_value={
                "node_code": "C",
                "impact_type": PlanCapacityImpact.ImpactType.BED_SLOTS,
                "delta": "8",
                "unit": "张",
                "description": "新增床位。",
            },
        )
        self.create_operation(
            change_set,
            sequence=60,
            operation_type=PlanChangeOperation.OperationType.UPDATE_NODE_FIELD,
            target_model="PlanNode",
            target_id=self.node_b.node_id,
            target_field="title",
            new_value={"value": "只修改新版本 B"},
        )
        self.create_operation(
            change_set,
            sequence=70,
            operation_type=PlanChangeOperation.OperationType.NOTE,
            target_model="PlanRevision",
            new_value={"note": "这是一条说明。"},
            is_required=False,
        )

        new_revision = apply_plan_change_set(change_set, actor={"actor_id": "tester"})

        self.node_b.refresh_from_db()
        self.assertEqual(self.node_b.title, "源节点 B")
        copied_b = PlanNode.objects.get(revision=new_revision, code="B")
        new_c = PlanNode.objects.get(revision=new_revision, code="C")
        self.assertEqual(copied_b.title, "只修改新版本 B")
        dependency = PlanDependency.objects.get(revision=new_revision, node=copied_b, depends_on=new_c)
        self.assertEqual(dependency.description, "C 完成后启动 B。")
        self.assertTrue(PlanRequirement.objects.filter(node=new_c, name="节点内嵌技能需求").exists())
        self.assertTrue(PlanRequirement.objects.filter(node=new_c, name="新增节点材料").exists())
        copied_a = PlanNode.objects.get(revision=new_revision, code="A")
        self.assertTrue(PlanRequirement.objects.filter(node=copied_a, name="已有节点许可").exists())
        self.assertEqual(PlanCapacityImpact.objects.get(node=new_c).delta, Decimal("8.000"))
        change_set.refresh_from_db()
        self.assertEqual(change_set.status, PlanChangeSet.Status.APPLIED)

    def test_reapplying_same_change_set_is_idempotent(self) -> None:
        change_set = self.create_change_set("changeset-apply-idempotent")
        self.create_operation(
            change_set,
            sequence=10,
            operation_type=PlanChangeOperation.OperationType.NOTE,
            target_model="PlanRevision",
            new_value={"note": "幂等测试。"},
            is_required=False,
        )

        first_revision = apply_plan_change_set(change_set, actor="tester")
        revision_count = PlanRevision.objects.count()
        node_count = PlanNode.objects.count()
        second_revision = apply_plan_change_set(change_set, actor="tester")

        self.assertEqual(second_revision, first_revision)
        self.assertEqual(PlanRevision.objects.count(), revision_count)
        self.assertEqual(PlanNode.objects.count(), node_count)

    def test_apply_can_publish_generated_revision_as_current_baseline(self) -> None:
        change_set = self.create_change_set("changeset-apply-published")
        self.create_operation(
            change_set,
            sequence=10,
            operation_type=PlanChangeOperation.OperationType.NOTE,
            target_model="PlanRevision",
            new_value={"note": "发布为下一轮基线。"},
            is_required=False,
        )

        new_revision = apply_plan_change_set(change_set, actor="tester", publish=True)

        self.revision.refresh_from_db()
        new_revision.refresh_from_db()
        self.assertEqual(self.revision.status, PlanRevision.Status.RETIRED)
        self.assertEqual(new_revision.status, PlanRevision.Status.PUBLISHED)
        self.assertIsNotNone(new_revision.published_at)
        change_set.refresh_from_db()
        self.assertEqual(change_set.status, PlanChangeSet.Status.APPLIED)
        self.assertEqual(change_set.applied_revision, new_revision)

    def test_application_failure_rolls_back_new_revision(self) -> None:
        change_set = self.create_change_set("changeset-apply-fails")
        self.create_operation(
            change_set,
            sequence=10,
            operation_type=PlanChangeOperation.OperationType.ADD_NODE,
            target_model="PlanNode",
            new_value={"code": "C", "title": "新增节点 C"},
        )
        self.create_operation(
            change_set,
            sequence=20,
            operation_type=PlanChangeOperation.OperationType.ADD_DEPENDENCY,
            target_model="PlanDependency",
            new_value={"node_code": "C", "depends_on_code": "MISSING"},
        )

        with self.assertRaises(DomainError):
            apply_plan_change_set(change_set, actor="tester")

        self.assertEqual(PlanRevision.objects.count(), 1)
        self.assertFalse(PlanNode.objects.filter(code="C").exists())
        change_set.refresh_from_db()
        self.assertEqual(change_set.status, PlanChangeSet.Status.DRAFT)
        self.assertIsNone(change_set.applied_revision)

    def test_revision_code_conflict_uses_next_available_patch(self) -> None:
        PlanRevision.objects.create(
            revision_id="plan-apply-rev-v0_0_2",
            plan=self.plan,
            revision_code="v0.0.2",
            status=PlanRevision.Status.DRAFT,
            title="已有冲突版本",
            change_summary="测试冲突。",
            created_at=self.now,
        )
        change_set = self.create_change_set("changeset-apply-version-conflict")

        new_revision = apply_plan_change_set(change_set, actor="tester")

        self.assertEqual(new_revision.revision_code, "v0.0.3")
