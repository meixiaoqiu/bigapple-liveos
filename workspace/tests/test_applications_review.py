from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.application_services import (
    create_member_application_admission_proposal,
    submit_member_application,
)
from core.member_roles import ROLE_FORMAL_MEMBER
from core.models import Member, MemberApplication, Proposal, ProposalExecution
from core.proposals.lifecycle import create_proposal
from core.proposals.voting import cast_proposal_vote
from core.tests.helpers import (
    create_governance_admin_member,
    create_member,
    login_as_member,
)


def _submit_application(member_no: str = "review-applicant", **overrides) -> MemberApplication:
    defaults = {
        "applicant_name": "审核测试报名者",
        "contact": "review-applicant@example.test",
        "motivation": "希望加入社区贡献力量。",
        "role_gap": "developer_ai_engineer",
        "availability_slots": ["weekend"],
        "requested_member_no": member_no,
    }
    defaults.update(overrides)
    return submit_member_application(**defaults)


class WorkspaceApplicationsReviewTests(TestCase):
    """成员报名审核模块：治理视图入口、审核动作、准入提案 / 投票 / 执行闭环。"""

    def setUp(self) -> None:
        self.governance = create_governance_admin_member("gov-review-0001")
        login_as_member(self.client, self.governance)

    # --- 入口与权限 ----------------------------------------------------------------

    def test_governance_member_sees_review_entry_and_list(self) -> None:
        _submit_application()
        workspace = self.client.get("/workspace/")
        self.assertEqual(workspace.status_code, 200)
        self.assertContains(workspace, "成员报名审核")

        review = self.client.get("/workspace/applications/")
        self.assertEqual(review.status_code, 200)
        self.assertContains(review, "审核测试报名者")

    def test_regular_form_member_cannot_see_entry_and_gets_403(self) -> None:
        member = create_member("mem-regular-0001", role_name=ROLE_FORMAL_MEMBER, status=Member.Status.ADMITTED)
        login_as_member(self.client, member)

        workspace = self.client.get("/workspace/")
        self.assertEqual(workspace.status_code, 200)
        self.assertNotContains(workspace, "成员报名审核")

        review = self.client.get("/workspace/applications/")
        self.assertEqual(review.status_code, 403)

    def test_pending_review_applicant_cannot_see_entry_and_gets_403(self) -> None:
        application = _submit_application(member_no="review-applicant-pending")
        login_as_member(self.client, application.linked_member)

        workspace = self.client.get("/workspace/")
        self.assertEqual(workspace.status_code, 200)
        self.assertNotContains(workspace, "成员报名审核")

        review = self.client.get("/workspace/applications/")
        self.assertEqual(review.status_code, 403)

    def test_superuser_without_member_binding_gets_403(self) -> None:
        user_model = get_user_model()
        superuser = user_model.objects.create_user(
            username="root-without-member",
            password="test-password-123",
            is_superuser=True,
            is_staff=True,
        )
        self.client.force_login(superuser)

        review = self.client.get("/workspace/applications/")
        self.assertEqual(review.status_code, 403)

    # --- 审核动作 ------------------------------------------------------------------

    def test_reject_with_reason_marks_member_application_rejected(self) -> None:
        application = _submit_application(member_no="review-applicant-reject")
        response = self.client.post(
            f"/workspace/applications/{application.application_id}/review/",
            {"status": MemberApplication.Status.REJECTED, "reason": "能力缺口较大。"},
        )
        self.assertEqual(response.status_code, 302)

        application.refresh_from_db()
        self.assertEqual(application.status, MemberApplication.Status.REJECTED)
        self.assertEqual(application.metadata["review_note"], "能力缺口较大。")
        member = application.linked_member
        member.refresh_from_db()
        self.assertEqual(member.status, Member.Status.APPLICATION_REJECTED)

    def test_reject_without_reason_is_rejected(self) -> None:
        application = _submit_application(member_no="review-applicant-no-reason")
        response = self.client.post(
            f"/workspace/applications/{application.application_id}/review/",
            {"status": MemberApplication.Status.REJECTED, "reason": ""},
        )
        self.assertEqual(response.status_code, 302)

        application.refresh_from_db()
        self.assertNotEqual(application.status, MemberApplication.Status.REJECTED)

    def test_review_form_cannot_directly_admit_member(self) -> None:
        application = _submit_application(member_no="review-applicant-direct-admit")
        response = self.client.post(
            f"/workspace/applications/{application.application_id}/review/",
            {"status": MemberApplication.Status.ADMITTED, "reason": "尝试直接接纳。"},
        )
        self.assertEqual(response.status_code, 302)

        application.refresh_from_db()
        self.assertNotEqual(application.status, MemberApplication.Status.ADMITTED)

    def test_mark_under_review_updates_status(self) -> None:
        application = _submit_application(member_no="review-applicant-under-review")
        self.client.post(
            f"/workspace/applications/{application.application_id}/review/",
            {"status": MemberApplication.Status.UNDER_REVIEW, "reason": "开始审核。"},
        )
        application.refresh_from_db()
        self.assertEqual(application.status, MemberApplication.Status.UNDER_REVIEW)

    # --- 准入提案 / 投票 / 执行 ----------------------------------------------------

    def test_create_admission_proposal_links_member_admission_proposal(self) -> None:
        application = _submit_application(member_no="review-applicant-proposal")
        response = self.client.post(
            f"/workspace/applications/{application.application_id}/create-admission-proposal/",
            {"reason": "符合开发缺口。"},
        )
        self.assertEqual(response.status_code, 302)

        application.refresh_from_db()
        self.assertIsNotNone(application.admission_proposal_id)
        self.assertEqual(application.admission_proposal.proposal_type, Proposal.ProposalType.MEMBER_ADMISSION)

    def test_single_governance_yes_vote_passes_proposal(self) -> None:
        application = _submit_application(member_no="review-applicant-single-voter")
        proposal = create_member_application_admission_proposal(
            application=application,
            proposer_member=self.governance,
            reason="单人治理场景。",
        )

        self.client.post(
            f"/workspace/proposals/{proposal.pk}/vote/",
            {"choice": "yes", "reason": "同意。"},
        )
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.Status.PASSED)

    def test_two_governance_majority_requires_both_yes_votes(self) -> None:
        # Both governance members must exist before the proposal is created, so
        # the eligible-voter snapshot freezes both into the electorate.
        second_governance = create_governance_admin_member("gov-review-0002")
        application = _submit_application(member_no="review-applicant-two-voters")
        proposal = create_member_application_admission_proposal(
            application=application,
            proposer_member=self.governance,
            reason="两人治理场景。",
        )

        # Only one yes vote: not enough (required_yes == 2 for 2 eligible voters).
        cast_proposal_vote(
            proposal=proposal,
            voter_member=self.governance,
            choice="yes",
        )
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.Status.VOTING)

        # Second yes vote pushes it over the strict-exceed threshold.
        cast_proposal_vote(
            proposal=proposal,
            voter_member=second_governance,
            choice="yes",
        )
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.Status.PASSED)

    def test_execute_passed_admission_proposal_admits_member(self) -> None:
        application = _submit_application(member_no="review-applicant-execute")
        proposal = create_member_application_admission_proposal(
            application=application,
            proposer_member=self.governance,
            reason="通过后执行接纳。",
        )
        self.client.post(
            f"/workspace/proposals/{proposal.pk}/vote/",
            {"choice": "yes", "reason": "同意接纳。"},
        )
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.Status.PASSED)

        response = self.client.post(f"/workspace/proposals/{proposal.pk}/execute/", {})
        self.assertEqual(response.status_code, 302)

        application.refresh_from_db()
        proposal.refresh_from_db()
        member = application.linked_member
        member.refresh_from_db()
        self.assertEqual(application.status, MemberApplication.Status.ADMITTED)
        self.assertEqual(member.status, Member.Status.ADMITTED)
        self.assertEqual(proposal.status, Proposal.Status.EXECUTED)
        self.assertIn(ROLE_FORMAL_MEMBER, member.active_role_names())
        self.assertTrue(
            ProposalExecution.objects.filter(
                proposal=proposal,
                action_type=ProposalExecution.ActionType.ADMIT_MEMBER_APPLICATION,
                status=ProposalExecution.Status.SUCCEEDED,
            ).exists()
        )

    def test_detail_page_shows_admission_proposal_and_vote_form(self) -> None:
        application = _submit_application(member_no="review-applicant-detail")
        proposal = create_member_application_admission_proposal(
            application=application,
            proposer_member=self.governance,
            reason="详情页展示。",
        )
        response = self.client.get(f"/workspace/applications/{application.application_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, proposal.proposal_no)
        self.assertContains(response, "提交投票")
        self.assertContains(response, "成员准入提案")

    # --- 提案门禁：非准入提案 / 未关联报名不得通过工作台 vote/execute -------------------

    def _policy_proposal(self) -> Proposal:
        return create_proposal(
            title="policy proposal for gate test",
            body="should not be reachable via workspace vote/execute.",
            proposal_type=Proposal.ProposalType.POLICY,
            proposer_member=self.governance,
            voter_scope_type=Proposal.VoterScopeType.ALL_MEMBERS,
        )

    def test_vote_on_non_admission_proposal_returns_404(self) -> None:
        proposal = self._policy_proposal()
        response = self.client.post(
            f"/workspace/proposals/{proposal.pk}/vote/",
            {"choice": "yes", "reason": "should 404."},
        )
        self.assertEqual(response.status_code, 404)

    def test_execute_on_non_admission_proposal_returns_404(self) -> None:
        proposal = self._policy_proposal()
        response = self.client.post(f"/workspace/proposals/{proposal.pk}/execute/", {})
        self.assertEqual(response.status_code, 404)

    def test_vote_on_orphan_member_admission_proposal_returns_404(self) -> None:
        # Create a member_admission proposal that is not linked to any MemberApplication.
        proposal = create_proposal(
            title="orphan admission proposal",
            body="type=member_admission but no MemberApplication.admission_proposal points here.",
            proposal_type=Proposal.ProposalType.MEMBER_ADMISSION,
            proposer_member=self.governance,
            voter_scope_type=Proposal.VoterScopeType.ALL_MEMBERS,
        )
        response = self.client.post(
            f"/workspace/proposals/{proposal.pk}/vote/",
            {"choice": "yes", "reason": "should 404 — no linked application."},
        )
        self.assertEqual(response.status_code, 404)

    def test_execute_on_orphan_member_admission_proposal_returns_404(self) -> None:
        proposal = create_proposal(
            title="orphan admission proposal",
            body="type=member_admission but no MemberApplication.admission_proposal points here.",
            proposal_type=Proposal.ProposalType.MEMBER_ADMISSION,
            proposer_member=self.governance,
            voter_scope_type=Proposal.VoterScopeType.ALL_MEMBERS,
        )
        response = self.client.post(f"/workspace/proposals/{proposal.pk}/execute/", {})
        self.assertEqual(response.status_code, 404)
