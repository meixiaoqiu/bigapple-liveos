from __future__ import annotations

from django.test import TestCase
from django.utils import timezone

from core.models import (
    PlanChangeOperation,
    PlanChangeSet,
    PlanNode,
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
