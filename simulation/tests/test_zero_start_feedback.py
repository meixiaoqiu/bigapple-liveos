from __future__ import annotations

from django.test import TestCase
from django.utils import timezone

from core.models import (
    PlanChangeOperation,
    PlanChangeSet,
    PlanNode,
    PlanRequirement,
    PlanRevision,
    PlanRevisionProposal,
    ProjectPlan,
    SimulationFailure,
    SimulationRun,
)
from simulation.form_drivers import FormSubmissionResult
from simulation.zero_start_feedback import (
    create_zero_start_feedback,
    create_zero_start_form_interaction_failure,
    create_zero_start_gate_failure,
    get_or_create_zero_start_feedback,
    plan_revision_has_zero_start_gate,
    zero_start_requirement_coverage,
)
from simulation.zero_start_strategy import (
    STARTUP_CAPABILITY_REQUIREMENTS,
    STARTUP_DOCUMENT_SIGNER_REQUIREMENTS,
)


class ZeroStartFeedbackTests(TestCase):
    def setUp(self) -> None:
        self.now = timezone.now()
        plan = ProjectPlan.objects.create(
            plan_id="plan-feedback-test", name="test plan",
            status=ProjectPlan.Status.ACTIVE, created_at=self.now,
        )
        self.revision = PlanRevision.objects.create(
            revision_id="plan-feedback-test-rev-v0_0_1",
            plan=plan, revision_code="v0.0.1",
            status=PlanRevision.Status.PUBLISHED,
            title="test revision", change_summary="test", created_at=self.now,
        )
        self.run = SimulationRun.objects.create(
            run_id="sim-run-feedback-test",
            plan_revision=self.revision,
            status=SimulationRun.Status.RUNNING,
            max_turns=10, started_at=self.now,
            metadata={"scenario": "zero_start"},
        )

    def _gate(self):
        return {
            "project_phase": "preparation",
            "startup_gate_satisfied": False,
            "capability_coverage": [],
            "document_signer_coverage": [],
            "missing_capabilities": [{"code": "cooking", "name": "做饭"}],
            "missing_document_signers": [{"code": "structural", "name": "结构安全"}],
        }

    # form interaction failure

    def test_create_zero_start_form_interaction_failure_writes_failure(self):
        result = FormSubmissionResult(
            success=False, path="/apply/", status_code=500, errors=["Server Error"],
        )
        ret = create_zero_start_form_interaction_failure(
            run=self.run, hour=5, result=result, simulation_day=1,
        )
        self.assertEqual(ret["run"].status, SimulationRun.Status.FAILED)
        self.assertTrue(SimulationFailure.objects.filter(run=self.run).exists())
        failure = ret["failure"]
        self.assertEqual(failure.failure_type, SimulationFailure.FailureType.EXECUTION_ISSUE)
        self.assertEqual(failure.title, "零起点仿真表单交互失败")
        self.assertEqual(failure.metadata["failure_kind"], "system_form_interaction_failed")

    # gate failure

    def test_create_zero_start_gate_failure_writes_business_failure(self):
        gate = self._gate()
        failure = create_zero_start_gate_failure(
            run=self.run, detected_hour=100, gate=gate, simulation_day=5,
            capability_requirements=(
                {"code": "cooking", "name": "做饭", "min_count": 1, "skill_aliases": ["做饭"]},
            ),
            document_signer_requirements=(
                {"code": "s", "name": "S", "document_examples": [], "acceptable_signers": []},
            ),
        )
        self.assertEqual(failure.failure_type, SimulationFailure.FailureType.RESPONSIBILITY_CLOSURE_MISSING)
        self.assertIn("required_initial_capabilities", failure.metadata)
        self.assertIn("required_document_signers", failure.metadata)
        self.assertIn("missing_capabilities", failure.metadata)
        self.assertIn("missing_document_signers", failure.metadata)

    # get_or_create feedback reuse

    def test_get_or_create_zero_start_feedback_reuses_existing_changeset(self):
        failure = create_zero_start_gate_failure(
            run=self.run, detected_hour=50, gate=self._gate(), simulation_day=3,
        )
        # first call creates
        proposal1, cs1 = create_zero_start_feedback(run=self.run, failure=failure)
        # second call via get_or_create reuses
        proposal2, cs2 = get_or_create_zero_start_feedback(run=self.run, failure=failure)
        self.assertEqual(cs1, cs2)
        self.assertEqual(proposal1, proposal2)

    # create feedback

    def test_create_zero_start_feedback_creates_proposal_changeset_operations(self):
        failure = create_zero_start_gate_failure(
            run=self.run, detected_hour=50, gate=self._gate(), simulation_day=3,
        )
        proposal, change_set = create_zero_start_feedback(run=self.run, failure=failure)
        self.assertIsNotNone(proposal)
        self.assertIsNotNone(change_set)
        self.assertEqual(proposal.run, self.run)
        operations = PlanChangeOperation.objects.filter(change_set=change_set)
        self.assertGreater(operations.count(), 0)
        self.assertTrue(operations.filter(operation_type=PlanChangeOperation.OperationType.ADD_NODE).exists())
        self.assertTrue(operations.filter(operation_type=PlanChangeOperation.OperationType.ADD_REQUIREMENT).exists())

    # plan_revision_has_zero_start_gate

    def test_plan_revision_has_zero_start_gate_true(self):
        PlanNode.objects.create(
            node_id="node-z0", revision=self.revision, sequence=0, code="Z0",
            title="Z0", node_type=PlanNode.NodeType.RECRUITMENT, created_at=self.now, metadata={},
        )
        self.assertTrue(plan_revision_has_zero_start_gate(self.revision))

    def test_plan_revision_has_zero_start_gate_false(self):
        self.assertFalse(plan_revision_has_zero_start_gate(self.revision))

    # Z0-exists feedback (ADD_REQUIREMENT only, no ADD_NODE)

    def test_create_zero_start_feedback_with_z0_existing_no_add_node(self):
        gate_node = PlanNode.objects.create(
            node_id="node-z0-existing", revision=self.revision, sequence=0, code="Z0",
            title="已存在的Z0", node_type=PlanNode.NodeType.RECRUITMENT, created_at=self.now, metadata={},
        )
        failure = create_zero_start_gate_failure(
            run=self.run, detected_hour=50, gate=self._gate(), simulation_day=3,
        )
        proposal, change_set = create_zero_start_feedback(
            run=self.run, failure=failure,
            gate_node=gate_node, include_gate_node=False,
        )
        self.assertEqual(proposal.proposal_type, PlanRevisionProposal.ProposalType.ADD_REQUIREMENT)
        self.assertIsNotNone(proposal.plan_node)
        self.assertEqual(proposal.plan_node, gate_node)

        operations = PlanChangeOperation.objects.filter(change_set=change_set)
        self.assertEqual(operations.filter(operation_type=PlanChangeOperation.OperationType.ADD_NODE).count(), 0)
        self.assertEqual(operations.filter(operation_type=PlanChangeOperation.OperationType.ADD_REQUIREMENT).count(), 11)
        self.assertTrue(operations.filter(metadata__requirement_kind="capability").exists())
        self.assertTrue(operations.filter(metadata__requirement_kind="document").exists())

    def test_get_or_create_zero_start_feedback_with_z0_creates_requirement_only(self):
        PlanNode.objects.create(
            node_id="node-z0-for-feedback", revision=self.revision, sequence=0, code="Z0",
            title="Z0", node_type=PlanNode.NodeType.RECRUITMENT, created_at=self.now, metadata={},
        )
        failure = create_zero_start_gate_failure(
            run=self.run, detected_hour=50, gate=self._gate(), simulation_day=3,
        )
        proposal, change_set = get_or_create_zero_start_feedback(run=self.run, failure=failure)
        self.assertIsNotNone(proposal)
        self.assertIsNotNone(change_set)
        self.assertEqual(proposal.proposal_type, PlanRevisionProposal.ProposalType.ADD_REQUIREMENT)
        self.assertIsNotNone(proposal.plan_node)
        operations = PlanChangeOperation.objects.filter(change_set=change_set)
        self.assertEqual(operations.filter(operation_type=PlanChangeOperation.OperationType.ADD_NODE).count(), 0)
        self.assertEqual(operations.filter(operation_type=PlanChangeOperation.OperationType.ADD_REQUIREMENT).count(), 11)

    def test_create_zero_start_feedback_without_z0_generates_add_node(self):
        failure = create_zero_start_gate_failure(
            run=self.run, detected_hour=50, gate=self._gate(), simulation_day=3,
        )
        proposal, change_set = create_zero_start_feedback(
            run=self.run, failure=failure,
            gate_node=None, include_gate_node=True,
        )
        self.assertEqual(proposal.proposal_type, PlanRevisionProposal.ProposalType.ADD_NODE)
        self.assertIsNone(proposal.plan_node)
        operations = PlanChangeOperation.objects.filter(change_set=change_set)
        self.assertEqual(operations.filter(operation_type=PlanChangeOperation.OperationType.ADD_NODE).count(), 1)
        self.assertEqual(operations.filter(operation_type=PlanChangeOperation.OperationType.ADD_REQUIREMENT).count(), 11)

    # Z0 requirement coverage

    def test_zero_start_requirement_coverage_empty(self):
        gate_node = PlanNode.objects.create(
            node_id="node-z0-empty-coverage", revision=self.revision, sequence=0, code="Z0",
            title="Z0", node_type=PlanNode.NodeType.RECRUITMENT, created_at=self.now, metadata={},
        )
        coverage = zero_start_requirement_coverage(gate_node)
        self.assertFalse(coverage["is_complete"])
        self.assertEqual(len(coverage["missing_capabilities"]), len(STARTUP_CAPABILITY_REQUIREMENTS))
        self.assertEqual(len(coverage["missing_documents"]), len(STARTUP_DOCUMENT_SIGNER_REQUIREMENTS))

    def test_zero_start_requirement_coverage_partial(self):
        gate_node = PlanNode.objects.create(
            node_id="node-z0-partial", revision=self.revision, sequence=0, code="Z0",
            title="Z0", node_type=PlanNode.NodeType.RECRUITMENT, created_at=self.now, metadata={},
        )
        PlanRequirement.objects.create(
            requirement_id="req-z0-cap-1", node=gate_node,
            requirement_type=PlanRequirement.RequirementType.SKILL,
            name="test cap", quantity=1, unit="人", is_must=True,
            metadata={"requirement_kind": "capability", "capability_code": STARTUP_CAPABILITY_REQUIREMENTS[0]["code"]},
        )
        PlanRequirement.objects.create(
            requirement_id="req-z0-doc-1", node=gate_node,
            requirement_type=PlanRequirement.RequirementType.PERMIT,
            name="test doc", quantity=1, unit="项", is_must=True,
            metadata={"requirement_kind": "document", "document_code": STARTUP_DOCUMENT_SIGNER_REQUIREMENTS[0]["code"]},
        )
        coverage = zero_start_requirement_coverage(gate_node)
        self.assertFalse(coverage["is_complete"])
        self.assertEqual(len(coverage["missing_capabilities"]), len(STARTUP_CAPABILITY_REQUIREMENTS) - 1)
        self.assertEqual(len(coverage["missing_documents"]), len(STARTUP_DOCUMENT_SIGNER_REQUIREMENTS) - 1)

    def test_zero_start_requirement_coverage_complete(self):
        gate_node = PlanNode.objects.create(
            node_id="node-z0-complete", revision=self.revision, sequence=0, code="Z0",
            title="Z0", node_type=PlanNode.NodeType.RECRUITMENT, created_at=self.now, metadata={},
        )
        for req in STARTUP_CAPABILITY_REQUIREMENTS:
            PlanRequirement.objects.create(
                requirement_id=f"req-z0-full-cap-{req['code']}", node=gate_node,
                requirement_type=PlanRequirement.RequirementType.SKILL,
                name=req["name"], quantity=req["min_count"], unit="人", is_must=True,
                metadata={"requirement_kind": "capability", "capability_code": req["code"]},
            )
        for req in STARTUP_DOCUMENT_SIGNER_REQUIREMENTS:
            PlanRequirement.objects.create(
                requirement_id=f"req-z0-full-doc-{req['code']}", node=gate_node,
                requirement_type=PlanRequirement.RequirementType.PERMIT,
                name=req["name"], quantity=1, unit="项", is_must=True,
                metadata={"requirement_kind": "document", "document_code": req["code"]},
            )
        coverage = zero_start_requirement_coverage(gate_node)
        self.assertTrue(coverage["is_complete"])
        self.assertEqual(len(coverage["missing_capabilities"]), 0)
        self.assertEqual(len(coverage["missing_documents"]), 0)

    def test_get_or_create_returns_none_when_z0_requirements_complete(self):
        gate_node = PlanNode.objects.create(
            node_id="node-z0-complete-feedback", revision=self.revision, sequence=0, code="Z0",
            title="Z0", node_type=PlanNode.NodeType.RECRUITMENT, created_at=self.now, metadata={},
        )
        for req in STARTUP_CAPABILITY_REQUIREMENTS:
            PlanRequirement.objects.create(
                requirement_id=f"req-z0-cmp-cap-{req['code']}", node=gate_node,
                requirement_type=PlanRequirement.RequirementType.SKILL,
                name=req["name"], quantity=req["min_count"], unit="人", is_must=True,
                metadata={"requirement_kind": "capability", "capability_code": req["code"]},
            )
        for req in STARTUP_DOCUMENT_SIGNER_REQUIREMENTS:
            PlanRequirement.objects.create(
                requirement_id=f"req-z0-cmp-doc-{req['code']}", node=gate_node,
                requirement_type=PlanRequirement.RequirementType.PERMIT,
                name=req["name"], quantity=1, unit="项", is_must=True,
                metadata={"requirement_kind": "document", "document_code": req["code"]},
            )
        failure = create_zero_start_gate_failure(
            run=self.run, detected_hour=50, gate=self._gate(), simulation_day=3,
        )
        proposal, change_set = get_or_create_zero_start_feedback(run=self.run, failure=failure)
        self.assertIsNone(proposal)
        self.assertIsNone(change_set)

    def test_get_or_create_partial_requirement_only_generates_missing(self):
        gate_node = PlanNode.objects.create(
            node_id="node-z0-partial-fb", revision=self.revision, sequence=0, code="Z0",
            title="Z0", node_type=PlanNode.NodeType.RECRUITMENT, created_at=self.now, metadata={},
        )
        covered_cap_code = STARTUP_CAPABILITY_REQUIREMENTS[0]["code"]
        covered_doc_code = STARTUP_DOCUMENT_SIGNER_REQUIREMENTS[0]["code"]
        PlanRequirement.objects.create(
            requirement_id="req-z0-prt-cap-1", node=gate_node,
            requirement_type=PlanRequirement.RequirementType.SKILL,
            name="test", quantity=1, unit="人", is_must=True,
            metadata={"requirement_kind": "capability", "capability_code": covered_cap_code},
        )
        PlanRequirement.objects.create(
            requirement_id="req-z0-prt-doc-1", node=gate_node,
            requirement_type=PlanRequirement.RequirementType.PERMIT,
            name="test", quantity=1, unit="项", is_must=True,
            metadata={"requirement_kind": "document", "document_code": covered_doc_code},
        )
        failure = create_zero_start_gate_failure(
            run=self.run, detected_hour=50, gate=self._gate(), simulation_day=3,
        )
        proposal, change_set = get_or_create_zero_start_feedback(run=self.run, failure=failure)
        self.assertIsNotNone(proposal)
        self.assertIsNotNone(change_set)
        self.assertEqual(proposal.proposal_type, PlanRevisionProposal.ProposalType.ADD_REQUIREMENT)
        operations = PlanChangeOperation.objects.filter(change_set=change_set)
        self.assertEqual(operations.filter(operation_type=PlanChangeOperation.OperationType.ADD_NODE).count(), 0)
        expected_total = (len(STARTUP_CAPABILITY_REQUIREMENTS) - 1) + (len(STARTUP_DOCUMENT_SIGNER_REQUIREMENTS) - 1)
        self.assertEqual(operations.filter(operation_type=PlanChangeOperation.OperationType.ADD_REQUIREMENT).count(), expected_total)

    def test_all_caps_covered_only_missing_docs(self):
        gate_node = PlanNode.objects.create(
            node_id="node-z0-caps-done", revision=self.revision, sequence=0, code="Z0",
            title="Z0", node_type=PlanNode.NodeType.RECRUITMENT, created_at=self.now, metadata={},
        )
        for req in STARTUP_CAPABILITY_REQUIREMENTS:
            PlanRequirement.objects.create(
                requirement_id=f"req-z0-cap-cov-{req['code']}", node=gate_node,
                requirement_type=PlanRequirement.RequirementType.SKILL,
                name=req["name"], quantity=req["min_count"], unit="人", is_must=True,
                metadata={"requirement_kind": "capability", "capability_code": req["code"]},
            )
        failure = create_zero_start_gate_failure(
            run=self.run, detected_hour=50, gate=self._gate(), simulation_day=3,
        )
        proposal, change_set = get_or_create_zero_start_feedback(run=self.run, failure=failure)
        self.assertIsNotNone(proposal)
        self.assertIsNotNone(change_set)
        operations = PlanChangeOperation.objects.filter(change_set=change_set)
        self.assertEqual(operations.filter(operation_type=PlanChangeOperation.OperationType.ADD_NODE).count(), 0)
        self.assertEqual(
            operations.filter(operation_type=PlanChangeOperation.OperationType.ADD_REQUIREMENT).count(),
            len(STARTUP_DOCUMENT_SIGNER_REQUIREMENTS),
        )
        self.assertFalse(operations.filter(metadata__requirement_kind="capability").exists())
        self.assertTrue(operations.filter(metadata__requirement_kind="document").exists())

    def test_all_docs_covered_only_missing_caps(self):
        gate_node = PlanNode.objects.create(
            node_id="node-z0-docs-done", revision=self.revision, sequence=0, code="Z0",
            title="Z0", node_type=PlanNode.NodeType.RECRUITMENT, created_at=self.now, metadata={},
        )
        for req in STARTUP_DOCUMENT_SIGNER_REQUIREMENTS:
            PlanRequirement.objects.create(
                requirement_id=f"req-z0-doc-cov-{req['code']}", node=gate_node,
                requirement_type=PlanRequirement.RequirementType.PERMIT,
                name=req["name"], quantity=1, unit="项", is_must=True,
                metadata={"requirement_kind": "document", "document_code": req["code"]},
            )
        failure = create_zero_start_gate_failure(
            run=self.run, detected_hour=50, gate=self._gate(), simulation_day=3,
        )
        proposal, change_set = get_or_create_zero_start_feedback(run=self.run, failure=failure)
        self.assertIsNotNone(proposal)
        self.assertIsNotNone(change_set)
        operations = PlanChangeOperation.objects.filter(change_set=change_set)
        self.assertEqual(operations.filter(operation_type=PlanChangeOperation.OperationType.ADD_NODE).count(), 0)
        self.assertEqual(
            operations.filter(operation_type=PlanChangeOperation.OperationType.ADD_REQUIREMENT).count(),
            len(STARTUP_CAPABILITY_REQUIREMENTS),
        )
        self.assertTrue(operations.filter(metadata__requirement_kind="capability").exists())
        self.assertFalse(operations.filter(metadata__requirement_kind="document").exists())
