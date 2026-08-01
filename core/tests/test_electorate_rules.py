from __future__ import annotations

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.electorate_rules import (
    TEMPLATE_COMMUNITY,
    TEMPLATE_COVENANTER,
    TEMPLATE_MAINTAINER,
    current_electorate_rule_version,
    ensure_electorate_rule_baseline,
    evaluate_condition_tree,
    validate_condition_tree,
)
from core.member_roles import ROLE_COVENANTER, ROLE_DELIBERATOR, ROLE_MAINTAINER, ensure_catalog_role
from core.models import Proposal
from core.proposals.lifecycle import create_proposal
from core.role_assignment_services import create_role_assignment
from core.tests.helpers import create_member, ensure_login_user_for_member


class ElectorateRuleTests(TestCase):
    def setUp(self) -> None:
        ensure_electorate_rule_baseline()
        self.contributor = create_member("electorate-contributor")
        ensure_login_user_for_member(self.contributor)
        self.covenanter = create_member("electorate-covenanter")
        ensure_login_user_for_member(self.covenanter)
        create_role_assignment(member=self.covenanter, role=ensure_catalog_role(ROLE_COVENANTER))
        self.deliberator = create_member("electorate-deliberator")
        ensure_login_user_for_member(self.deliberator)
        create_role_assignment(member=self.deliberator, role=ensure_catalog_role(ROLE_COVENANTER))
        create_role_assignment(member=self.deliberator, role=ensure_catalog_role(ROLE_DELIBERATOR))
        self.maintainer = create_member("electorate-maintainer")
        ensure_login_user_for_member(self.maintainer)
        create_role_assignment(member=self.maintainer, role=ensure_catalog_role(ROLE_COVENANTER))
        create_role_assignment(member=self.maintainer, role=ensure_catalog_role(ROLE_MAINTAINER))

    def _proposal(self, proposal_type: str, template_code: str) -> Proposal:
        now = timezone.now()
        return create_proposal(
            title="选民规则测试",
            proposal_type=proposal_type,
            electorate_rule_version=current_electorate_rule_version(template_code),
            start_at=now,
            deadline_at=now + timedelta(days=7),
        )

    def test_community_deliberation_includes_contributor(self) -> None:
        proposal = self._proposal(Proposal.ProposalType.COMMUNITY, TEMPLATE_COMMUNITY)
        self.assertIn(self.contributor.pk, proposal.eligible_voters_snapshot_json)
        self.assertFalse(self.contributor.role_assignments.exists())

    def test_maintainer_does_not_inherit_deliberator_vote(self) -> None:
        proposal = self._proposal(Proposal.ProposalType.POLICY, TEMPLATE_COVENANTER)
        self.assertNotIn(self.maintainer.pk, proposal.eligible_voters_snapshot_json)
        self.assertIn(self.deliberator.pk, proposal.eligible_voters_snapshot_json)

    def test_maintainer_matter_selects_maintainer_without_deliberator(self) -> None:
        proposal = self._proposal(Proposal.ProposalType.MAINTENANCE, TEMPLATE_MAINTAINER)
        self.assertIn(self.maintainer.pk, proposal.eligible_voters_snapshot_json)
        self.assertNotIn(self.deliberator.pk, proposal.eligible_voters_snapshot_json)

    def test_rule_template_cannot_be_used_by_unapproved_proposal_type(self) -> None:
        with self.assertRaises(ValidationError):
            self._proposal(Proposal.ProposalType.BUDGET, TEMPLATE_COMMUNITY)

    def test_condition_validator_rejects_unknown_or_executable_nodes(self) -> None:
        for condition in (
            {"op": "SQL", "query": "select * from core_member"},
            {"op": "SELECTOR", "selector": "python", "value": "danger"},
            {"op": "NOT", "conditions": []},
        ):
            with self.subTest(condition=condition), self.assertRaises(ValidationError):
                validate_condition_tree(condition)

    def test_all_any_not_use_stable_set_semantics(self) -> None:
        condition = {
            "op": "ALL",
            "conditions": [
                {"op": "SELECTOR", "selector": "registered_member"},
                {
                    "op": "NOT",
                    "conditions": [
                        {"op": "SELECTOR", "selector": "catalog_role", "value": "maintainer"}
                    ],
                },
            ],
        }
        member_ids = set(evaluate_condition_tree(condition).values_list("pk", flat=True))
        self.assertIn(self.contributor.pk, member_ids)
        self.assertNotIn(self.maintainer.pk, member_ids)
