from __future__ import annotations

from unittest import mock, skipUnless
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from core.application_services import submit_member_application
from core.authorization_services import AuthorizationService
from core.electorate_rule_services import (
    create_electorate_rule_template,
    electorate_eligibility_for_proposal,
    publish_electorate_rule_version,
    validate_selector_config,
)
from core.exceptions import DomainError
from core.openfga_client import OpenFGARequestError
from core.member_roles import ROLE_ADMINISTRATOR, ROLE_COVENANTER, ensure_catalog_role, member_has_role
from core.models import (
    ApprovalProposal,
    ElectorateRuleVersion,
    Member,
    ProposalBallot,
    ProposalExecutionRecord,
    RoleAssignment,
    SystemEvent,
)
from core.role_assignment_services import create_role_assignment
from core.proposal_adapters import proposal_adapter_for, registered_proposal_types
from core.tests.helpers import create_administrator_member, create_member, login_as_member
from core.unified_proposal_services import (
    attach_rule_version,
    cast_electorate_ballot,
    create_electorate_proposal,
    execute_electorate_proposal,
    finalize_electorate_proposal,
    proposal_tally,
    start_electorate_voting,
)


class UnifiedMemberAdmissionProposalTests(TestCase):
    def setUp(self) -> None:
        self.administrator = create_administrator_member("proposal-administrator")

    def submit_application(self, member_no: str = "proposal-applicant"):
        return submit_member_application(
            applicant_name="统一提案申请人",
            contact="proposal-applicant@example.test",
            motivation="希望承担守约者义务。",
            role_gap="ai_engineer",
            availability_slots=["weekend"],
            requested_member_no=member_no,
        )

    def publish_policy(self, selector_config: dict, *, approve=1, reject=1, minimum=1):
        template = create_electorate_rule_template(
            proposal_type=ApprovalProposal.ProposalType.MEMBER_APPLICATION,
            rule_code="member-admission",
            name="守约者准入",
            created_by=self.administrator,
        )
        return publish_electorate_rule_version(
            template=template,
            selector_config=selector_config,
            approve_threshold=approve,
            reject_threshold=reject,
            minimum_participation=minimum,
            voting_duration_hours=168,
            unresolved_outcome=ElectorateRuleVersion.UnresolvedOutcome.EXPIRED,
            published_by=self.administrator,
        )

    def test_application_without_policy_creates_waiting_proposal(self):
        application = self.submit_application()

        self.assertIsNotNone(application.admission_proposal_id)
        self.assertEqual(application.admission_proposal.status, ApprovalProposal.Status.AWAITING_POLICY)
        self.assertEqual(application.status, application.Status.SUBMITTED)

    def test_published_policy_allows_complete_admission_flow(self):
        policy = self.publish_policy({"role_code": "administrator"})
        application = self.submit_application()
        proposal = application.admission_proposal

        self.assertEqual(proposal.status, ApprovalProposal.Status.VOTING)
        cast_electorate_ballot(
            proposal=proposal,
            voter=self.administrator,
            choice=ProposalBallot.Choice.APPROVE,
            reason="同意申请人承担守约义务。",
        )
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, ApprovalProposal.Status.APPROVED)

        record = execute_electorate_proposal(proposal=proposal, actor=self.administrator)

        self.assertEqual(record.status, ProposalExecutionRecord.Status.SUCCEEDED)
        application.refresh_from_db()
        application.linked_member.refresh_from_db()
        self.assertEqual(application.status, application.Status.ADMITTED)
        self.assertTrue(member_has_role(application.linked_member, ROLE_COVENANTER))
        assignment = application.linked_member.role_assignments.get(role__name=ROLE_COVENANTER)
        self.assertGreaterEqual((assignment.end_at - assignment.start_at).days, 364)
        self.assertLessEqual((assignment.end_at - assignment.start_at).days, 365)

        same_record = execute_electorate_proposal(proposal=proposal, actor=self.administrator)
        self.assertEqual(same_record.pk, record.pk)
        self.assertEqual(application.linked_member.role_assignments.filter(role__name=ROLE_COVENANTER).count(), 1)

    def test_applicant_is_excluded_even_when_contributor_rule_matches(self):
        policy = self.publish_policy({"participation_status": "contributor"})
        application = self.submit_application()
        proposal = application.admission_proposal

        decision = electorate_eligibility_for_proposal(
            proposal=proposal,
            member=application.linked_member,
            excluded_member_id=application.linked_member_id,
        )

        self.assertFalse(decision.allowed)
        with self.assertRaises(DomainError):
            cast_electorate_ballot(
                proposal=proposal,
                voter=application.linked_member,
                choice=ProposalBallot.Choice.APPROVE,
            )

    def test_ballot_revision_is_append_only_and_only_latest_counts(self):
        policy = self.publish_policy({"role_code": "administrator"}, approve=2, reject=2)
        application = self.submit_application()
        proposal = application.admission_proposal

        cast_electorate_ballot(
            proposal=proposal, voter=self.administrator, choice=ProposalBallot.Choice.REJECT,
        )
        cast_electorate_ballot(
            proposal=proposal, voter=self.administrator, choice=ProposalBallot.Choice.APPROVE,
        )

        ballots = list(ProposalBallot.objects.filter(proposal=proposal).order_by("revision"))
        self.assertEqual([item.revision for item in ballots], [1, 2])
        self.assertEqual([item.choice for item in ballots], ["reject", "approve"])

    def test_ballot_from_member_who_lost_qualification_no_longer_counts(self):
        second_administrator = create_administrator_member("proposal-second-administrator")
        self.publish_policy({"role_code": "administrator"}, approve=2, reject=2, minimum=2)
        application = self.submit_application("proposal-revoked-voter-applicant")
        proposal = application.admission_proposal

        cast_electorate_ballot(
            proposal=proposal,
            voter=self.administrator,
            choice=ProposalBallot.Choice.APPROVE,
        )
        self.administrator.role_assignments.filter(
            role__name=ROLE_ADMINISTRATOR,
            status=RoleAssignment.Status.ACTIVE,
        ).update(status=RoleAssignment.Status.REVOKED)
        cast_electorate_ballot(
            proposal=proposal,
            voter=second_administrator,
            choice=ProposalBallot.Choice.APPROVE,
        )

        proposal.refresh_from_db()
        tally = proposal_tally(proposal)
        self.assertEqual(tally.participation_count, 1)
        self.assertEqual(tally.approve_count, 1)
        self.assertEqual(proposal.status, ApprovalProposal.Status.VOTING)

    def test_contributor_in_snapshot_can_open_proposal_page_and_vote(self):
        contributor = create_member("proposal-contributor-voter")
        self.publish_policy({"participation_status": "contributor"}, approve=1, reject=1, minimum=1)
        application = self.submit_application("proposal-contributor-applicant")
        proposal = application.admission_proposal
        login_as_member(self.client, contributor)

        page = self.client.get("/workspace/proposals/")
        response = self.client.post(
            f"/workspace/proposals/{proposal.proposal_id}/vote/",
            {"choice": ProposalBallot.Choice.APPROVE},
        )

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, proposal.title)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ProposalBallot.objects.filter(proposal=proposal, voter=contributor).exists())

    def test_proposal_page_uses_distinct_policy_resolution_and_execution_permissions(self):
        from core.electorate_rule_services import MANAGE_PROPOSAL_POLICIES_PERMISSION
        from core.member_admission_proposal_adapter import (
            MEMBER_ADMISSION_EXECUTION_PERMISSION,
            MEMBER_ADMISSION_RESOLUTION_PERMISSION,
        )

        self.publish_policy({"role_code": "administrator"}, approve=2, reject=2, minimum=2)
        application = self.submit_application("proposal-distinct-page-permissions")
        proposal = application.admission_proposal
        login_as_member(self.client, self.administrator)

        def resolution_only(_member, permission_code, **_kwargs):
            return permission_code == MEMBER_ADMISSION_RESOLUTION_PERMISSION

        with mock.patch.object(
            AuthorizationService, "member_has_permission", side_effect=resolution_only,
        ):
            response = self.client.get("/workspace/proposals/")

        display = next(item for item in response.context["recent"] if item["proposal_id"] == proposal.proposal_id)
        self.assertFalse(response.context["can_manage_proposal_policies"])
        self.assertTrue(display["can_resolve_electorate"])
        self.assertFalse(display["can_execute_electorate"])
        self.assertContains(response, "截止后判定")
        self.assertNotContains(response, "配置守约者准入政策")
        self.assertNotContains(response, "执行已通过提案")

        def policy_only(_member, permission_code, **_kwargs):
            return permission_code == MANAGE_PROPOSAL_POLICIES_PERMISSION

        with mock.patch.object(
            AuthorizationService, "member_has_permission", side_effect=policy_only,
        ):
            response = self.client.get("/workspace/proposals/")

        display = next(item for item in response.context["recent"] if item["proposal_id"] == proposal.proposal_id)
        self.assertTrue(response.context["can_manage_proposal_policies"])
        self.assertFalse(display["can_resolve_electorate"])
        self.assertFalse(display["can_execute_electorate"])
        self.assertContains(response, "配置守约者准入政策")
        self.assertNotContains(response, "截止后判定")

        proposal.status = ApprovalProposal.Status.APPROVED
        proposal.save(update_fields=["status"])

        def execution_only(_member, permission_code, **_kwargs):
            return permission_code == MEMBER_ADMISSION_EXECUTION_PERMISSION

        with mock.patch.object(
            AuthorizationService, "member_has_permission", side_effect=execution_only,
        ):
            response = self.client.get("/workspace/proposals/")

        display = next(item for item in response.context["recent"] if item["proposal_id"] == proposal.proposal_id)
        self.assertFalse(response.context["can_manage_proposal_policies"])
        self.assertFalse(display["can_resolve_electorate"])
        self.assertTrue(display["can_execute_electorate"])
        self.assertEqual(response.context["execute_count"], 1)
        self.assertEqual(response.context["executable"], [])
        self.assertContains(response, "执行已通过提案")
        self.assertContains(
            response,
            f'/workspace/proposals/{proposal.proposal_id}/execute/',
        )
        self.assertNotContains(
            response,
            f'/workspace/approval-proposals/{proposal.proposal_id}/execute/',
        )
        self.assertNotContains(response, "截止后判定")

    def test_non_snapshot_authority_holder_can_see_electorate_proposal(self):
        from core.member_admission_proposal_adapter import MEMBER_ADMISSION_RESOLUTION_PERMISSION

        authority_holder = create_member("proposal-resolution-only-viewer", role_name=ROLE_COVENANTER)
        self.publish_policy({"role_code": "administrator"}, approve=2, reject=2, minimum=2)
        application = self.submit_application("proposal-authority-visibility-applicant")
        proposal = application.admission_proposal
        self.assertFalse(proposal.elector_snapshots.filter(member=authority_holder).exists())
        login_as_member(self.client, authority_holder)

        def resolution_only(_member, permission_code, **_kwargs):
            return permission_code == MEMBER_ADMISSION_RESOLUTION_PERMISSION

        with mock.patch.object(
            AuthorizationService, "member_has_permission", side_effect=resolution_only,
        ):
            response = self.client.get("/workspace/proposals/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, proposal.title)
        self.assertContains(response, "截止后判定")

    def test_rule_validation_rejects_unknown_or_executable_conditions(self):
        with self.assertRaises(DomainError):
            validate_selector_config({"role_code": "founder"})
        with self.assertRaises(DomainError):
            validate_selector_config({"query": "Member.objects.all()"})

    def test_only_member_admission_is_registered_and_other_governance_flows_fail_closed(self):
        proposal_adapter_for(ApprovalProposal.ProposalType.MEMBER_APPLICATION)
        self.assertEqual(registered_proposal_types(), (ApprovalProposal.ProposalType.MEMBER_APPLICATION,))
        for proposal_type in (
            "role_appointment",
            "finance_role_appointment",
            "community_deliberation",
            "covenant_matter",
            "professional_matter",
            "administration_matter",
            "feedback_action",
            "simulation_automatic_decision",
        ):
            with self.subTest(proposal_type=proposal_type), self.assertRaisesRegex(DomainError, "尚未迁移"):
                proposal_adapter_for(proposal_type)

    def test_new_catalog_role_needs_only_catalog_data_not_proposal_branch(self):
        future_role = SimpleNamespace(display_name="管理员", openfga_relation="administrator")
        with mock.patch(
            "core.electorate_rule_services.role_definition_for_code",
            return_value=future_role,
        ), mock.patch(
            "core.role_catalog.role_definition_for_code",
            return_value=future_role,
        ):
            policy = self.publish_policy({"role_code": "future_catalog_role"})
            application = self.submit_application("proposal-catalog-extension")
            proposal = application.admission_proposal
            decision = electorate_eligibility_for_proposal(
                proposal=proposal,
                member=self.administrator,
                excluded_member_id=application.linked_member_id,
            )

        self.assertEqual(policy.selector_config, {"role_code": "future_catalog_role"})
        self.assertTrue(decision.allowed)

    def test_execution_failure_rolls_back_role_assignment_and_records_failure(self):
        self.publish_policy({"role_code": "administrator"})
        application = self.submit_application()
        proposal = application.admission_proposal
        cast_electorate_ballot(
            proposal=proposal, voter=self.administrator, choice=ProposalBallot.Choice.APPROVE,
        )

        with mock.patch(
            "core.member_admission_proposal_adapter.create_role_assignment",
            side_effect=DomainError("测试执行失败"),
        ):
            record = execute_electorate_proposal(proposal=proposal, actor=self.administrator)

        proposal.refresh_from_db()
        self.assertEqual(record.status, ProposalExecutionRecord.Status.FAILED)
        self.assertEqual(proposal.status, ApprovalProposal.Status.EXECUTION_FAILED)
        self.assertFalse(member_has_role(application.linked_member, ROLE_COVENANTER))

    def test_electorate_execution_rejects_fixed_strategy_with_same_proposal_type(self):
        application = self.submit_application("proposal-fixed-strategy-applicant")
        fixed = ApprovalProposal.objects.create(
            proposal_id="proposal-fixed-member-application",
            proposal_type=ApprovalProposal.ProposalType.MEMBER_APPLICATION,
            title="固定审批伪装的成员准入",
            status=ApprovalProposal.Status.APPROVED,
            strategy_type=ApprovalProposal.StrategyType.APPROVAL_SLOTS,
            dedupe_key="fixed-member-application",
            target_type="member_application",
            target_id=application.application_id,
            submitted_by=self.administrator,
        )

        with self.assertRaisesRegex(DomainError, "不属于统一选民表决生命周期"):
            execute_electorate_proposal(proposal=fixed, actor=self.administrator)

        self.assertFalse(ProposalExecutionRecord.objects.filter(proposal=fixed).exists())

    def test_electorate_execution_requires_approved_resolution_evidence(self):
        self.publish_policy({"role_code": "administrator"}, approve=2, reject=2, minimum=2)
        application = self.submit_application("proposal-missing-resolution-applicant")
        proposal = application.admission_proposal
        proposal.status = ApprovalProposal.Status.APPROVED
        proposal.save(update_fields=["status"])

        with self.assertRaisesRegex(DomainError, "缺少已通过的确定性判定证据"):
            execute_electorate_proposal(proposal=proposal, actor=self.administrator)

        self.assertFalse(ProposalExecutionRecord.objects.filter(proposal=proposal).exists())

    def test_non_administrator_cannot_publish_policy(self):
        regular = create_member("proposal-policy-regular", status=Member.Status.ACTIVE)
        create_role_assignment(member=regular, role=ensure_catalog_role(ROLE_COVENANTER))

        with self.assertRaisesRegex(DomainError, "无权"):
            create_electorate_rule_template(
                proposal_type=ApprovalProposal.ProposalType.MEMBER_APPLICATION,
                rule_code="unauthorized-member-admission",
                name="无权政策",
                created_by=regular,
            )

    def test_rejected_vote_maps_application_and_keeps_evidence(self):
        self.publish_policy({"role_code": "administrator"})
        application = self.submit_application("proposal-rejected-applicant")
        proposal = application.admission_proposal

        cast_electorate_ballot(
            proposal=proposal,
            voter=self.administrator,
            choice=ProposalBallot.Choice.REJECT,
            reason="申请说明不足。",
        )

        proposal.refresh_from_db()
        application.refresh_from_db()
        self.assertEqual(proposal.status, ApprovalProposal.Status.REJECTED)
        self.assertEqual(application.status, application.Status.REJECTED)
        self.assertEqual(proposal.resolution.evidence["reject_count"], 1)
        self.assertEqual(proposal.resolution.decided_by, self.administrator)
        self.assertEqual(application.decided_by, self.administrator)
        self.assertEqual(proposal.ballots.get().reason, "申请说明不足。")
        event = SystemEvent.objects.filter(
            aggregate_id=proposal.proposal_id,
            event_type=SystemEvent.EventType.APPROVAL_PROPOSAL_REJECTED,
        ).latest("occurred_at")
        self.assertEqual(event.actor_member, self.administrator)

    def test_expired_vote_maps_application_without_deleting_history(self):
        self.publish_policy({"role_code": "administrator"}, approve=2, reject=2, minimum=2)
        application = self.submit_application("proposal-expired-applicant")
        proposal = application.admission_proposal
        proposal.voting_deadline = timezone.now() - timezone.timedelta(seconds=1)
        proposal.save(update_fields=["voting_deadline"])

        finalize_electorate_proposal(proposal=proposal, actor=self.administrator)

        proposal.refresh_from_db()
        application.refresh_from_db()
        self.assertEqual(proposal.status, ApprovalProposal.Status.EXPIRED)
        self.assertEqual(application.status, application.Status.REJECTED)
        self.assertEqual(proposal.resolution.decided_by, self.administrator)
        self.assertEqual(application.decided_by, self.administrator)
        self.assertTrue(application.metadata["proposal_resolution_reason"].startswith("deadline_"))

    def test_deadline_finalization_uses_permission_distinct_from_execution(self):
        from core.member_admission_proposal_adapter import MEMBER_ADMISSION_RESOLUTION_PERMISSION

        self.publish_policy({"role_code": "administrator"}, approve=2, reject=2, minimum=2)
        application = self.submit_application("proposal-resolution-permission-applicant")
        proposal = application.admission_proposal
        proposal.voting_deadline = timezone.now() - timezone.timedelta(seconds=1)
        proposal.save(update_fields=["voting_deadline"])

        with mock.patch("core.unified_proposal_services._require_permission") as require_permission:
            finalize_electorate_proposal(proposal=proposal, actor=self.administrator)

        self.assertEqual(require_permission.call_args.args[1], MEMBER_ADMISSION_RESOLUTION_PERMISSION)
        self.assertNotEqual(
            proposal_adapter_for(proposal.proposal_type).resolution_permission,
            proposal_adapter_for(proposal.proposal_type).execution_permission,
        )

    def test_execution_permission_alone_cannot_finalize_deadline(self):
        from core.member_admission_proposal_adapter import MEMBER_ADMISSION_EXECUTION_PERMISSION

        self.publish_policy({"role_code": "administrator"}, approve=2, reject=2, minimum=2)
        application = self.submit_application("proposal-execution-only-applicant")
        proposal = application.admission_proposal
        proposal.voting_deadline = timezone.now() - timezone.timedelta(seconds=1)
        proposal.save(update_fields=["voting_deadline"])

        def permission_check(_member, permission_code, **_kwargs):
            return permission_code == MEMBER_ADMISSION_EXECUTION_PERMISSION

        with mock.patch.object(
            AuthorizationService,
            "member_has_permission",
            side_effect=permission_check,
        ), self.assertRaisesRegex(DomainError, "无权完成"):
            finalize_electorate_proposal(proposal=proposal, actor=self.administrator)

        proposal.refresh_from_db()
        self.assertEqual(proposal.status, ApprovalProposal.Status.VOTING)

    def test_vote_after_deadline_does_not_bypass_finalization_permission(self):
        self.publish_policy({"role_code": "administrator"})
        application = self.submit_application("proposal-deadline-vote-applicant")
        proposal = application.admission_proposal
        proposal.voting_deadline = timezone.now() - timezone.timedelta(seconds=1)
        proposal.save(update_fields=["voting_deadline"])

        with self.assertRaisesRegex(DomainError, "有权人员完成结果判定"):
            cast_electorate_ballot(
                proposal=proposal,
                voter=self.administrator,
                choice=ProposalBallot.Choice.APPROVE,
            )

        proposal.refresh_from_db()
        self.assertEqual(proposal.status, ApprovalProposal.Status.VOTING)
        self.assertFalse(ProposalBallot.objects.filter(proposal=proposal).exists())

    def test_inactive_applicant_fails_execution_without_partial_role(self):
        self.publish_policy({"role_code": "administrator"})
        application = self.submit_application("proposal-inactive-applicant")
        proposal = application.admission_proposal
        cast_electorate_ballot(
            proposal=proposal, voter=self.administrator, choice=ProposalBallot.Choice.APPROVE,
        )
        user = get_user_model().objects.create_user(
            username="proposal-inactive-user", password="test-password", is_active=False,
        )
        application.linked_member.user = user
        application.linked_member.save(update_fields=["user"])

        record = execute_electorate_proposal(proposal=proposal, actor=self.administrator)

        application.refresh_from_db()
        self.assertEqual(record.status, ProposalExecutionRecord.Status.FAILED)
        self.assertEqual(application.status, application.Status.SUBMITTED)
        self.assertFalse(member_has_role(application.linked_member, ROLE_COVENANTER))

    def test_existing_covenanter_fails_execution_without_duplicate_assignment(self):
        self.publish_policy({"role_code": "administrator"})
        application = self.submit_application("proposal-existing-covenanter")
        proposal = application.admission_proposal
        cast_electorate_ballot(
            proposal=proposal, voter=self.administrator, choice=ProposalBallot.Choice.APPROVE,
        )
        create_role_assignment(member=application.linked_member, role=ensure_catalog_role(ROLE_COVENANTER))

        record = execute_electorate_proposal(proposal=proposal, actor=self.administrator)

        self.assertEqual(record.status, ProposalExecutionRecord.Status.FAILED)
        self.assertEqual(
            application.linked_member.role_assignments.filter(role__name=ROLE_COVENANTER).count(), 1,
        )

    def test_exited_applicant_fails_execution(self):
        self.publish_policy({"role_code": "administrator"})
        application = self.submit_application("proposal-exited-applicant")
        proposal = application.admission_proposal
        cast_electorate_ballot(
            proposal=proposal, voter=self.administrator, choice=ProposalBallot.Choice.APPROVE,
        )
        application.linked_member.status = Member.Status.EXITED
        application.linked_member.save(update_fields=["status"])

        record = execute_electorate_proposal(proposal=proposal, actor=self.administrator)

        self.assertEqual(record.status, ProposalExecutionRecord.Status.FAILED)
        self.assertFalse(member_has_role(application.linked_member, ROLE_COVENANTER))

    def test_conflicting_future_covenanter_term_fails_without_second_assignment(self):
        self.publish_policy({"role_code": "administrator"})
        application = self.submit_application("proposal-conflicting-term")
        proposal = application.admission_proposal
        cast_electorate_ballot(
            proposal=proposal, voter=self.administrator, choice=ProposalBallot.Choice.APPROVE,
        )
        future_start = timezone.now() + timezone.timedelta(days=30)
        create_role_assignment(
            member=application.linked_member,
            role=ensure_catalog_role(ROLE_COVENANTER),
            start_at=future_start,
            end_at=future_start + timezone.timedelta(days=365),
        )

        record = execute_electorate_proposal(proposal=proposal, actor=self.administrator)

        self.assertEqual(record.status, ProposalExecutionRecord.Status.FAILED)
        self.assertEqual(
            application.linked_member.role_assignments.filter(role__name=ROLE_COVENANTER).count(), 1,
        )

    @override_settings(
        BIG_APPLE_AUTHORIZATION_BACKEND="openfga",
        SITE_ROLE="simulation",
        OPENFGA_SIM_STORE_ID="",
        OPENFGA_SIM_AUTHORIZATION_MODEL_ID="",
    )
    def test_openfga_missing_fails_application_initiation_closed(self):
        with self.assertRaisesRegex(DomainError, "授权服务"):
            self.submit_application("proposal-no-openfga-initiation")
        self.assertFalse(ApprovalProposal.objects.exists())

    def test_openfga_missing_fails_vote_and_execution_closed(self):
        self.publish_policy({"role_code": "administrator"})
        application = self.submit_application("proposal-no-openfga-actions")
        proposal = application.admission_proposal
        unavailable = override_settings(
            BIG_APPLE_AUTHORIZATION_BACKEND="openfga",
            SITE_ROLE="simulation",
            OPENFGA_SIM_STORE_ID="",
            OPENFGA_SIM_AUTHORIZATION_MODEL_ID="",
        )
        with unavailable:
            with self.assertRaisesRegex(DomainError, "授权服务"):
                cast_electorate_ballot(
                    proposal=proposal,
                    voter=self.administrator,
                    choice=ProposalBallot.Choice.APPROVE,
                )
            with self.assertRaisesRegex(DomainError, "无权"):
                execute_electorate_proposal(proposal=proposal, actor=self.administrator)
        self.assertFalse(ProposalBallot.objects.filter(proposal=proposal).exists())

    def test_openfga_request_failure_and_incomplete_tuples_fail_vote_closed(self):
        self.publish_policy({"role_code": "administrator"})
        application = self.submit_application("proposal-openfga-failure")
        proposal = application.admission_proposal
        configured = override_settings(
            BIG_APPLE_AUTHORIZATION_BACKEND="openfga",
            SITE_ROLE="simulation",
            OPENFGA_SIM_STORE_ID="configured-store",
            OPENFGA_SIM_AUTHORIZATION_MODEL_ID="current-model",
        )
        with configured, mock.patch("core.authorization_services.OpenFGAClient") as client_class:
            client_class.return_value.check.side_effect = OpenFGARequestError("模型请求失败")
            with self.assertRaisesRegex(DomainError, "授权服务"):
                cast_electorate_ballot(
                    proposal=proposal,
                    voter=self.administrator,
                    choice=ProposalBallot.Choice.APPROVE,
                )
            client_class.return_value.check.side_effect = None
            client_class.return_value.check.return_value = False
            with self.assertRaisesRegex(DomainError, "不满足"):
                cast_electorate_ballot(
                    proposal=proposal,
                    voter=self.administrator,
                    choice=ProposalBallot.Choice.APPROVE,
                )
        self.assertFalse(ProposalBallot.objects.filter(proposal=proposal).exists())

    def test_proposal_page_survives_authorization_backend_failure_during_tally(self):
        self.publish_policy({"role_code": "administrator"}, approve=2, reject=2, minimum=2)
        application = self.submit_application("proposal-page-openfga-failure")
        login_as_member(self.client, self.administrator)
        configured = override_settings(
            BIG_APPLE_AUTHORIZATION_BACKEND="openfga",
            SITE_ROLE="simulation",
            OPENFGA_SIM_STORE_ID="configured-store",
            OPENFGA_SIM_AUTHORIZATION_MODEL_ID="current-model",
        )
        with configured, mock.patch("core.authorization_services.OpenFGAClient") as client_class:
            client_class.return_value.check.side_effect = OpenFGARequestError("模型请求失败")
            response = self.client.get("/workspace/proposals/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, application.admission_proposal.title)
        self.assertContains(response, "当前无法读取有效票数")

    def test_execute_count_only_includes_rendered_electorate_actions(self):
        self.publish_policy({"role_code": "administrator"}, approve=2, reject=2, minimum=2)
        old_application = self.submit_application("proposal-old-approved-outside-limit")
        old_proposal = old_application.admission_proposal
        old_proposal.status = ApprovalProposal.Status.APPROVED
        old_proposal.save(update_fields=["status"])
        for index in range(20):
            ApprovalProposal.objects.create(
                proposal_id=f"proposal-newer-visible-{index}",
                proposal_type=ApprovalProposal.ProposalType.MEMBER_APPLICATION,
                title=f"较新的可见提案 {index}",
                status=ApprovalProposal.Status.VOTING,
                strategy_type=ApprovalProposal.StrategyType.ELECTORATE,
                dedupe_key=f"newer-visible-{index}",
                target_type="member_application",
                target_id=f"missing-application-{index}",
                submitted_by=self.administrator,
                submitted_at=timezone.now() + timezone.timedelta(seconds=index + 1),
            )
        login_as_member(self.client, self.administrator)

        response = self.client.get("/workspace/proposals/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["execute_count"], 0)
        self.assertNotContains(response, old_proposal.title)

    @override_settings(
        BIG_APPLE_AUTHORIZATION_BACKEND="openfga",
        SITE_ROLE="simulation",
        OPENFGA_SIM_STORE_ID="configured-store",
        OPENFGA_SIM_AUTHORIZATION_MODEL_ID="obsolete-model",
    )
    def test_openfga_obsolete_model_failure_closes_initiation(self):
        with mock.patch("core.authorization_services.OpenFGAClient") as client_class:
            client_class.return_value.check.side_effect = OpenFGARequestError("relation not found in model")
            with self.assertRaisesRegex(DomainError, "授权服务"):
                self.submit_application("proposal-obsolete-model")
        self.assertFalse(ApprovalProposal.objects.exists())


class UnifiedProposalBallotConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self) -> None:
        administrator = create_administrator_member("proposal-concurrent-administrator")
        template = create_electorate_rule_template(
            proposal_type=ApprovalProposal.ProposalType.MEMBER_APPLICATION,
            rule_code="member-admission-concurrency",
            name="守约者准入并发测试",
            created_by=administrator,
        )
        publish_electorate_rule_version(
            template=template,
            selector_config={"role_code": "administrator"},
            approve_threshold=3,
            reject_threshold=3,
            minimum_participation=3,
            voting_duration_hours=24,
            unresolved_outcome=ElectorateRuleVersion.UnresolvedOutcome.EXPIRED,
            published_by=administrator,
        )
        application = submit_member_application(
            applicant_name="并发票据申请人",
            contact="concurrent@example.test",
            motivation="测试并发改票。",
            role_gap="ai_engineer",
            availability_slots=["weekend"],
            requested_member_no="proposal-concurrent-applicant",
        )
        self.proposal_id = application.admission_proposal_id
        self.voter_id = administrator.pk
        self.rule_version_id = application.admission_proposal.electorate_rule_version_id
        self.application_id = application.application_id

    @skipUnless(connection.features.has_select_for_update, "SQLite 不支持行级 select_for_update；MySQL 回归执行此并发断言。")
    def test_concurrent_ballots_are_serialized_as_distinct_revisions(self):
        barrier = Barrier(2)

        def submit(choice: str) -> None:
            close_old_connections()
            barrier.wait(timeout=5)
            cast_electorate_ballot(
                proposal=ApprovalProposal.objects.get(pk=self.proposal_id),
                voter=Member.objects.get(pk=self.voter_id),
                choice=choice,
            )
            close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(submit, ProposalBallot.Choice.APPROVE),
                pool.submit(submit, ProposalBallot.Choice.REJECT),
            ]
            for future in futures:
                future.result(timeout=15)

        revisions = list(
            ProposalBallot.objects.filter(proposal_id=self.proposal_id)
            .order_by("revision")
            .values_list("revision", flat=True)
        )
        self.assertEqual(revisions, [1, 2])

    @skipUnless(connection.features.has_select_for_update, "SQLite 不支持真实唯一约束竞争；MySQL 回归执行此并发断言。")
    def test_concurrent_same_dedupe_creation_reuses_winner(self):
        barrier = Barrier(2)
        dedupe_key = "member-admission:concurrent-create"

        def create() -> str:
            close_old_connections()
            barrier.wait(timeout=5)
            proposal = create_electorate_proposal(
                proposal_type=ApprovalProposal.ProposalType.MEMBER_APPLICATION,
                title="并发幂等创建",
                submitted_by=Member.objects.get(pk=self.voter_id),
                dedupe_key=dedupe_key,
                target_type="member_application",
                target_id=self.application_id,
                rule_version=ElectorateRuleVersion.objects.get(pk=self.rule_version_id),
            )
            proposal_id = proposal.proposal_id
            close_old_connections()
            return proposal_id

        with ThreadPoolExecutor(max_workers=2) as pool:
            proposal_ids = [future.result(timeout=15) for future in (pool.submit(create), pool.submit(create))]

        self.assertEqual(len(set(proposal_ids)), 1)
        self.assertEqual(
            ApprovalProposal.objects.filter(
                proposal_type=ApprovalProposal.ProposalType.MEMBER_APPLICATION,
                dedupe_key=dedupe_key,
            ).count(),
            1,
        )
