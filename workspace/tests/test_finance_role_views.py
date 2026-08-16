from django.test import TestCase

from core.finance_role_services import nominate_finance_reviewer
from core.proposal_migration import PROPOSAL_FLOW_UNAVAILABLE_MESSAGE, ProposalFlowUnavailable
from core.tests.helpers import create_member


class FinanceRoleWorkspaceClosureTests(TestCase):
    def test_nomination_fails_closed_without_changing_authority(self) -> None:
        actor = create_member("finance-actor", display_name="发起人")
        target = create_member("finance-target", display_name="候选人")
        before = target.role_assignments.count()

        with self.assertRaisesMessage(ProposalFlowUnavailable, PROPOSAL_FLOW_UNAVAILABLE_MESSAGE):
            nominate_finance_reviewer(actor=actor, target_member=target, reason="测试")

        self.assertEqual(target.role_assignments.count(), before)
