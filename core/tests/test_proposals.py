from __future__ import annotations

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.application_services import submit_member_application
from core.electorate_rules import (
    TEMPLATE_COVENANTER,
    TEMPLATE_PROFESSIONAL,
    current_electorate_rule_version,
    ensure_electorate_rule_baseline,
)
from core.governance_setup import ensure_administrator_role
from core.proposals.execution import execute_proposal
from core.proposals.lifecycle import create_proposal, create_role_appointment_proposal
from core.proposals.voting import cast_proposal_vote
from core.professional_qualification_services import (
    ensure_professional_domain,
    record_external_professional_qualification,
    revoke_professional_qualification,
)
from core.role_assignment_services import create_role_assignment, revoke_role_assignment
from core.member_roles import ROLE_DELIBERATOR, ROLE_COVENANTER, ensure_catalog_role
from core.models import Proposal, ProposalVote
from core.tests.helpers import create_member, ensure_login_user_for_member


class ProposalVotingPolicyTests(TestCase):
    """提案使用受类型约束的版本化选民规则。"""

    def setUp(self) -> None:
        self.covenanter_role = ensure_catalog_role(ROLE_COVENANTER)
        self.deliberator_role = ensure_catalog_role(ROLE_DELIBERATOR)
        self.administrator_role = ensure_administrator_role()["role"]
        self.deliberator_1 = self._member("policy-deliberator-1")
        self.deliberator_2 = self._member("policy-deliberator-2")
        self.covenanter_only = self._member("policy-covenanter-only")
        self.administrator_only = self._member("policy-administrator-only")
        self.target = self._member("policy-target")
        self.finance_domain = ensure_professional_domain(code="finance", name="财务")
        self.construction_domain = ensure_professional_domain(code="construction", name="建设")
        ensure_electorate_rule_baseline()

        for member in (self.deliberator_1, self.deliberator_2):
            self._grant_covenanter_and_deliberator(member)
        create_role_assignment(member=self.covenanter_only, role=self.covenanter_role)
        create_role_assignment(member=self.administrator_only, role=self.covenanter_role)
        create_role_assignment(member=self.administrator_only, role=self.administrator_role)
        create_role_assignment(member=self.target, role=self.covenanter_role)

    def _member(self, member_no: str):
        member = create_member(member_no)
        ensure_login_user_for_member(member)
        return member

    def _grant_covenanter_and_deliberator(self, member) -> None:
        create_role_assignment(member=member, role=self.covenanter_role)
        create_role_assignment(member=member, role=self.deliberator_role)

    def _general_proposal(self, *, start_at=None, deadline_at=None) -> Proposal:
        starts_at = start_at or timezone.now()
        return create_proposal(
            title="普通议事提案",
            proposal_type=Proposal.ProposalType.POLICY,
            proposer_member=self.deliberator_1,
            electorate_rule_version=current_electorate_rule_version(TEMPLATE_COVENANTER),
            start_at=starts_at,
            deadline_at=deadline_at or starts_at + timedelta(days=7),
        )

    def _professional_proposal(self, *, domain=None, start_at=None, deadline_at=None) -> Proposal:
        starts_at = start_at or timezone.now()
        return create_proposal(
            title="专业议事提案",
            proposal_type=Proposal.ProposalType.BUDGET,
            proposer_member=self.deliberator_1,
            electorate_rule_version=current_electorate_rule_version(TEMPLATE_PROFESSIONAL),
            professional_domain=domain or self.finance_domain,
            start_at=starts_at,
            deadline_at=deadline_at or starts_at + timedelta(days=7),
        )

    def test_general_policy_snapshot_is_intersection_of_covenanters_and_deliberators(self) -> None:
        proposal = self._general_proposal()

        self.assertEqual(proposal.electorate_rule_version.template.code, TEMPLATE_COVENANTER)
        self.assertIsNone(proposal.professional_domain)
        self.assertEqual(
            set(proposal.eligible_voters_snapshot_json),
            {self.deliberator_1.pk, self.deliberator_2.pk},
        )

    def test_professional_policy_snapshot_requires_matching_qualification(self) -> None:
        record_external_professional_qualification(
            member=self.deliberator_1,
            domain=self.finance_domain,
            confirmed_by=self.administrator_only,
            external_confirmation_source="外部财务资格核验",
        )
        record_external_professional_qualification(
            member=self.deliberator_2,
            domain=self.construction_domain,
            confirmed_by=self.administrator_only,
            external_confirmation_source="外部建设资格核验",
        )

        proposal = self._professional_proposal()

        self.assertEqual(set(proposal.eligible_voters_snapshot_json), {self.deliberator_1.pk})

    def test_unclassified_or_invalid_professional_policy_fails_closed(self) -> None:
        with self.assertRaises(ValidationError):
            create_proposal(
                title="无效政策",
                proposal_type=Proposal.ProposalType.RULE,
                electorate_rule_version=None,
                deadline_at=timezone.now() + timedelta(days=1),
            )
        with self.assertRaises(ValidationError):
            create_proposal(
                title="缺少领域",
                proposal_type=Proposal.ProposalType.BUDGET,
                electorate_rule_version=current_electorate_rule_version(TEMPLATE_PROFESSIONAL),
                deadline_at=timezone.now() + timedelta(days=1),
            )
        with self.assertRaises(ValidationError):
            create_proposal(
                title="普通提案错误指定领域",
                proposal_type=Proposal.ProposalType.RULE,
                electorate_rule_version=current_electorate_rule_version(TEMPLATE_COVENANTER),
                professional_domain=self.finance_domain,
                deadline_at=timezone.now() + timedelta(days=1),
            )
        self.finance_domain.status = self.finance_domain.Status.ARCHIVED
        self.finance_domain.save(update_fields=["status", "updated_at"])
        with self.assertRaises(ValidationError):
            self._professional_proposal(domain=self.finance_domain)

    def test_covenanter_or_administrator_without_deliberator_term_cannot_vote(self) -> None:
        proposal = self._general_proposal()

        with self.assertRaises(ValidationError):
            cast_proposal_vote(proposal=proposal, voter_member=self.covenanter_only, choice=ProposalVote.Choice.YES)
        with self.assertRaises(ValidationError):
            cast_proposal_vote(proposal=proposal, voter_member=self.administrator_only, choice=ProposalVote.Choice.YES)

    def test_current_deliberator_term_is_rechecked_after_snapshot(self) -> None:
        proposal = self._general_proposal()
        assignment = self.deliberator_1.role_assignments.get(role=self.deliberator_role)
        revoke_role_assignment(assignment=assignment, revoked_by=self.administrator_only)

        self.assertIn(self.deliberator_1.pk, proposal.eligible_voters_snapshot_json)
        with self.assertRaises(ValidationError):
            cast_proposal_vote(proposal=proposal, voter_member=self.deliberator_1, choice=ProposalVote.Choice.YES)

    def test_current_professional_qualification_is_rechecked_after_snapshot(self) -> None:
        qualification = record_external_professional_qualification(
            member=self.deliberator_1,
            domain=self.finance_domain,
            confirmed_by=self.administrator_only,
            external_confirmation_source="外部财务资格核验",
        )
        proposal = self._professional_proposal()
        revoke_professional_qualification(qualification=qualification, revoked_by=self.administrator_only)

        self.assertIn(self.deliberator_1.pk, proposal.eligible_voters_snapshot_json)
        with self.assertRaises(ValidationError):
            cast_proposal_vote(proposal=proposal, voter_member=self.deliberator_1, choice=ProposalVote.Choice.YES)

    def test_matching_professional_deliberator_can_vote(self) -> None:
        record_external_professional_qualification(
            member=self.deliberator_1,
            domain=self.finance_domain,
            confirmed_by=self.administrator_only,
            external_confirmation_source="外部财务资格核验",
        )
        proposal = self._professional_proposal()

        vote = cast_proposal_vote(proposal=proposal, voter_member=self.deliberator_1, choice=ProposalVote.Choice.YES)

        self.assertEqual(vote.voter_role_assignment.role, self.deliberator_role)
        self.assertEqual(vote.choice, ProposalVote.Choice.YES)

    def test_role_appointment_proposal_uses_covenanter_rule(self) -> None:
        proposal = create_role_appointment_proposal(
            target_member=self.target,
            target_role=self.administrator_role,
            proposer_member=self.deliberator_1,
        )

        self.assertEqual(proposal.electorate_rule_version.template.code, TEMPLATE_COVENANTER)
        self.assertEqual(
            set(proposal.eligible_voters_snapshot_json),
            {self.deliberator_1.pk, self.deliberator_2.pk},
        )

    def test_member_admission_proposal_uses_covenanter_rule(self) -> None:
        application = submit_member_application(
            applicant_name="申请者",
            contact="applicant@example.test",
            motivation="希望参与社区。",
            role_gap="ai_engineer",
            availability_slots=["weekend"],
            capability_scores={"开发": 80},
            requested_member_no="policy-applicant",
        )
        proposal = application.admission_proposal

        self.assertEqual(proposal.electorate_rule_version.template.code, TEMPLATE_COVENANTER)
        self.assertEqual(
            set(proposal.eligible_voters_snapshot_json),
            {self.deliberator_1.pk, self.deliberator_2.pk},
        )
        cast_proposal_vote(proposal=proposal, voter_member=self.deliberator_1, choice=ProposalVote.Choice.YES)
        cast_proposal_vote(proposal=proposal, voter_member=self.deliberator_2, choice=ProposalVote.Choice.YES)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.Status.PASSED)
        execution = execute_proposal(proposal=proposal, executor_member=self.administrator_only)
        self.assertEqual(execution.status, execution.Status.SUCCEEDED)
