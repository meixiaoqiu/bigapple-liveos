from __future__ import annotations

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.application_services import create_member_application_admission_proposal, submit_member_application
from core.member_roles import ROLE_FORMAL_MEMBER
from core.permission_services import member_has_permission
from core.proposals.execution import execute_proposal
from core.proposals.lifecycle import create_proposal, create_role_appointment_proposal
from core.proposals.voting import cast_proposal_vote, fail_expired_proposal
from core.role_assignment_services import create_role_assignment
from core.models import (
    SystemEvent,
    Organization,
    Permission,
    Proposal,
    ProposalExecution,
    ProposalVote,
    Role,
    RoleAssignment,
    RolePermission,
)
from core.tests.helpers import create_member


class ProposalTests(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="proposal committee")
        self.committee_role = Role.objects.create(
            organization=self.organization,
            name="committee member",
            description="Can vote on advanced governance proposals.",
        )
        self.admin_role = Role.objects.create(
            organization=self.organization,
            name="governance admin",
            description="Advanced role that requires unanimous approval.",
            appointment_electorate_role=self.committee_role,
            appointment_required_percent=100,
            appointment_deadline_days=3,
        )
        self.target = create_member("member-target")
        self.voter_1 = create_member("member-voter-1")
        self.voter_2 = create_member("member-voter-2")
        self.voter_3 = create_member("member-voter-3")
        self.outsider = create_member("member-outsider")
        for voter in (self.voter_1, self.voter_2, self.voter_3):
            create_role_assignment(member=voter, role=self.committee_role)

    def create_majority_role(self) -> Role:
        return Role.objects.create(
            organization=self.organization,
            name="team lead",
            appointment_electorate_role=self.committee_role,
            appointment_required_percent=50,
            appointment_deadline_days=3,
        )

    def vote_yes(self, proposal: Proposal, voter) -> ProposalVote:
        return cast_proposal_vote(
            proposal=proposal,
            voter_member=voter,
            choice=ProposalVote.Choice.YES,
        )

    def test_can_create_general_proposal(self) -> None:
        deadline_at = timezone.now() + timezone.timedelta(days=2)

        proposal = create_proposal(
            title="Adopt resource policy",
            body="Policy body",
            proposal_type=Proposal.ProposalType.POLICY,
            proposer_member=self.voter_1,
            organization=self.organization,
            voter_scope_type=Proposal.VoterScopeType.ROLE,
            voter_scope_role=self.committee_role,
            pass_ratio=50,
            deadline_at=deadline_at,
        )

        self.assertEqual(proposal.status, Proposal.Status.VOTING)
        self.assertEqual(proposal.proposal_type, Proposal.ProposalType.POLICY)
        self.assertEqual(set(proposal.eligible_voters_snapshot_json), {self.voter_1.pk, self.voter_2.pk, self.voter_3.pk})
        self.assertTrue(proposal.proposal_no)

    def test_can_create_role_appointment_proposal(self) -> None:
        proposal = create_role_appointment_proposal(
            target_member=self.target,
            target_role=self.admin_role,
            proposer_member=self.voter_1,
            reason="Needs admin access.",
        )

        self.assertEqual(proposal.proposal_type, Proposal.ProposalType.ROLE_APPOINTMENT)
        self.assertEqual(proposal.payload_json["target_member_id"], self.target.pk)
        self.assertEqual(proposal.payload_json["role_id"], self.admin_role.pk)
        self.assertEqual(set(proposal.eligible_voters_snapshot_json), {self.voter_1.pk, self.voter_2.pk, self.voter_3.pk})

    def test_eligible_member_can_vote_and_ineligible_member_cannot_vote(self) -> None:
        proposal = create_role_appointment_proposal(target_member=self.target, target_role=self.admin_role)

        vote = self.vote_yes(proposal, self.voter_1)

        self.assertEqual(vote.choice, ProposalVote.Choice.YES)
        with self.assertRaises(ValidationError):
            self.vote_yes(proposal, self.outsider)

    def test_vote_can_be_changed_before_deadline(self) -> None:
        proposal = create_role_appointment_proposal(target_member=self.target, target_role=self.admin_role)

        cast_proposal_vote(proposal=proposal, voter_member=self.voter_1, choice=ProposalVote.Choice.NO)
        cast_proposal_vote(proposal=proposal, voter_member=self.voter_1, choice=ProposalVote.Choice.YES)

        self.assertEqual(ProposalVote.objects.filter(proposal=proposal, voter_member=self.voter_1).count(), 1)
        self.assertEqual(ProposalVote.objects.get(proposal=proposal, voter_member=self.voter_1).choice, ProposalVote.Choice.YES)
        self.assertTrue(
            SystemEvent.objects.filter(
                event_type=SystemEvent.EventType.PROPOSAL_VOTE_CHANGED,
                aggregate_type="ProposalVote",
            ).exists()
        )

    def test_vote_cannot_be_changed_after_deadline(self) -> None:
        now = timezone.now()
        proposal = create_role_appointment_proposal(
            target_member=self.target,
            target_role=self.admin_role,
            deadline_at=now + timezone.timedelta(minutes=1),
        )
        cast_proposal_vote(
            proposal=proposal,
            voter_member=self.voter_1,
            choice=ProposalVote.Choice.NO,
            at_time=now,
        )

        with self.assertRaises(ValidationError):
            cast_proposal_vote(
                proposal=proposal,
                voter_member=self.voter_1,
                choice=ProposalVote.Choice.YES,
                at_time=now + timezone.timedelta(minutes=2),
            )

    def test_pass_ratio_marks_proposal_passed_without_immediate_execution(self) -> None:
        proposal = create_role_appointment_proposal(target_member=self.target, target_role=self.admin_role)

        self.vote_yes(proposal, self.voter_1)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.Status.VOTING)

        self.vote_yes(proposal, self.voter_2)
        self.vote_yes(proposal, self.voter_3)
        proposal.refresh_from_db()

        self.assertEqual(proposal.status, Proposal.Status.PASSED)
        self.assertFalse(
            RoleAssignment.objects.filter(member=self.target, role=self.admin_role, status=RoleAssignment.Status.ACTIVE).exists()
        )

    def test_majority_proposal_passes_after_required_percent(self) -> None:
        leader_role = self.create_majority_role()
        proposal = create_role_appointment_proposal(target_member=self.target, target_role=leader_role)

        self.vote_yes(proposal, self.voter_1)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.Status.VOTING)

        self.vote_yes(proposal, self.voter_2)
        proposal.refresh_from_db()

        self.assertEqual(proposal.status, Proposal.Status.PASSED)
        self.assertEqual(proposal.result_json["required_yes"], 2)

    def test_two_voter_majority_requires_both_votes(self) -> None:
        two_person_role = Role.objects.create(
            organization=self.organization,
            name="two person committee",
        )
        create_role_assignment(member=self.voter_1, role=two_person_role)
        create_role_assignment(member=self.voter_2, role=two_person_role)
        proposal = create_proposal(
            title="Two person majority",
            proposal_type=Proposal.ProposalType.POLICY,
            voter_scope_type=Proposal.VoterScopeType.ROLE,
            voter_scope_role=two_person_role,
            pass_ratio=50,
        )

        self.vote_yes(proposal, self.voter_1)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.Status.VOTING)
        self.assertEqual(proposal.result_json["required_yes"], 2)

        self.vote_yes(proposal, self.voter_2)
        proposal.refresh_from_db()

        self.assertEqual(proposal.status, Proposal.Status.PASSED)

    def test_pending_proposal_fails_after_deadline(self) -> None:
        now = timezone.now()
        proposal = create_role_appointment_proposal(
            target_member=self.target,
            target_role=self.admin_role,
            start_at=now - timezone.timedelta(days=2),
            deadline_at=now - timezone.timedelta(days=1),
        )

        fail_expired_proposal(proposal, at_time=now)
        proposal.refresh_from_db()

        self.assertEqual(proposal.status, Proposal.Status.FAILED)
        self.assertFalse(
            RoleAssignment.objects.filter(member=self.target, role=self.admin_role, status=RoleAssignment.Status.ACTIVE).exists()
        )

    def test_role_appointment_proposal_execution_creates_role_assignment(self) -> None:
        proposal = create_role_appointment_proposal(target_member=self.target, target_role=self.admin_role)
        for voter in (self.voter_1, self.voter_2, self.voter_3):
            self.vote_yes(proposal, voter)
        proposal.refresh_from_db()

        execution = execute_proposal(proposal=proposal, executor_member=self.voter_1)
        proposal.refresh_from_db()

        self.assertEqual(execution.status, ProposalExecution.Status.SUCCEEDED)
        self.assertEqual(proposal.status, Proposal.Status.EXECUTED)
        assignment = RoleAssignment.objects.get(
            member=self.target,
            role=self.admin_role,
            status=RoleAssignment.Status.ACTIVE,
        )
        self.assertEqual(assignment.source_type, RoleAssignment.SourceType.PROPOSAL)
        self.assertEqual(assignment.source_proposal, proposal)
        self.assertEqual(assignment.source_proposal_execution, execution)
        self.assertEqual(execution.result_json["source_type"], RoleAssignment.SourceType.PROPOSAL)

    def test_member_admission_proposal_execution_admits_linked_applicant(self) -> None:
        application = submit_member_application(
            applicant_name="准入申请者",
            contact="applicant@example.test",
            motivation="想加入社区。",
            role_gap="developer_ai_engineer",
            availability_slots=["weekend"],
            capability_scores={"开发": 80},
            requested_member_no="admission-applicant",
        )

        proposal = create_member_application_admission_proposal(
            application=application,
            proposer_member=self.voter_1,
            voter_scope_role=self.committee_role,
            reason="符合当前开发缺口。",
        )
        self.vote_yes(proposal, self.voter_1)
        self.vote_yes(proposal, self.voter_2)
        proposal.refresh_from_db()

        execution = execute_proposal(proposal=proposal, executor_member=self.voter_1)
        application.refresh_from_db()
        member = application.linked_member
        member.refresh_from_db()

        self.assertEqual(proposal.status, Proposal.Status.EXECUTED)
        self.assertEqual(execution.action_type, ProposalExecution.ActionType.ADMIT_MEMBER_APPLICATION)
        self.assertEqual(application.status, application.Status.ADMITTED)
        self.assertEqual(member.status, member.Status.ADMITTED)
        self.assertIn(ROLE_FORMAL_MEMBER, member.active_role_names())

    def test_repeated_proposal_execution_is_idempotent(self) -> None:
        proposal = create_role_appointment_proposal(target_member=self.target, target_role=self.admin_role)
        for voter in (self.voter_1, self.voter_2, self.voter_3):
            self.vote_yes(proposal, voter)

        first = execute_proposal(proposal=proposal, executor_member=self.voter_1)
        second = execute_proposal(proposal=proposal, executor_member=self.voter_1)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(
            RoleAssignment.objects.filter(member=self.target, role=self.admin_role, status=RoleAssignment.Status.ACTIVE).count(),
            1,
        )

    def test_proposal_events_are_appended(self) -> None:
        proposal = create_role_appointment_proposal(target_member=self.target, target_role=self.admin_role)
        for voter in (self.voter_1, self.voter_2, self.voter_3):
            self.vote_yes(proposal, voter)
        execute_proposal(proposal=proposal, executor_member=self.voter_1)

        event_types = set(SystemEvent.objects.values_list("event_type", flat=True))

        self.assertIn(SystemEvent.EventType.PROPOSAL_CREATED, event_types)
        self.assertIn(SystemEvent.EventType.PROPOSAL_VOTE_CAST, event_types)
        self.assertIn(SystemEvent.EventType.PROPOSAL_PASSED, event_types)
        self.assertIn(SystemEvent.EventType.PROPOSAL_EXECUTED, event_types)
        self.assertIn(SystemEvent.EventType.ROLE_ASSIGNED, event_types)

    def test_member_has_permission_is_unchanged_after_proposal_execution(self) -> None:
        permission = Permission.objects.create(
            code="governance.test_permission",
            name="Test permission",
            category="governance",
        )
        RolePermission.objects.create(role=self.admin_role, permission=permission, scope="global")
        proposal = create_role_appointment_proposal(target_member=self.target, target_role=self.admin_role)
        for voter in (self.voter_1, self.voter_2, self.voter_3):
            self.vote_yes(proposal, voter)
        execute_proposal(proposal=proposal, executor_member=self.voter_1)

        self.assertTrue(member_has_permission(self.target, "governance.test_permission"))
