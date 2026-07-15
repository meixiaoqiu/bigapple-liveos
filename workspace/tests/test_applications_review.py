from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.application_services import submit_member_application
from core.member_roles import ROLE_FORMAL_MEMBER
from core.models import Member, MemberApplication, Proposal, ProposalExecution, ProposalVote
from core.proposals.lifecycle import create_proposal
from core.proposals.voting import cast_proposal_vote
from core.tests.helpers import (
    create_governance_admin_member,
    create_member,
    ensure_login_user_for_member,
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
    """成员报名审核模块：准入提案自动创建、投票/执行闭环、入口权限。"""

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

    # --- 报名自动创建准入提案 -------------------------------------------------------

    def test_submit_application_auto_creates_member_admission_proposal(self) -> None:
        application = _submit_application(member_no="auto-proposal-test")
        self.assertIsNotNone(application.admission_proposal_id)
        proposal = application.admission_proposal
        self.assertEqual(proposal.proposal_type, Proposal.ProposalType.MEMBER_ADMISSION)
        self.assertEqual(proposal.status, Proposal.Status.VOTING)
        self.assertEqual(application.status, MemberApplication.Status.ADMISSION_VOTING)

    # --- 审核 POST 端点已移除 -------------------------------------------------------

    def test_review_post_endpoint_returns_404(self) -> None:
        application = _submit_application(member_no="no-review-post")
        response = self.client.post(
            f"/workspace/applications/{application.application_id}/review/",
            {"status": MemberApplication.Status.REJECTED, "reason": "不应存在此端点。"},
        )
        self.assertEqual(response.status_code, 404)

    def test_create_admission_proposal_post_endpoint_returns_404(self) -> None:
        application = _submit_application(member_no="no-create-proposal-post")
        response = self.client.post(
            f"/workspace/applications/{application.application_id}/create-admission-proposal/",
            {"reason": "不应存在此端点。"},
        )
        self.assertEqual(response.status_code, 404)

    # --- 准入提案 / 投票 / 执行 ----------------------------------------------------

    def test_single_governance_yes_vote_passes_proposal(self) -> None:
        application = _submit_application(member_no="review-applicant-single-voter")
        proposal = application.admission_proposal
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal.status, Proposal.Status.VOTING)

        self.client.post(
            f"/workspace/proposals/{proposal.pk}/vote/",
            {"choice": "yes", "reason": "同意。"},
        )
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, Proposal.Status.PASSED)

    def test_two_governance_majority_requires_both_yes_votes(self) -> None:
        second_governance = create_governance_admin_member("gov-review-0002")
        ensure_login_user_for_member(second_governance)
        application = _submit_application(member_no="review-applicant-two-voters")
        proposal = application.admission_proposal

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
        proposal = application.admission_proposal
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
        proposal = application.admission_proposal
        response = self.client.get(f"/workspace/applications/{application.application_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, proposal.proposal_no)
        self.assertContains(response, "提交投票")
        self.assertContains(response, "成员准入提案")
        # The old review form must NOT be present.
        self.assertNotContains(response, "审核操作")
        self.assertNotContains(response, "审核状态")

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

    # --- 意向角色中文显示 ----------------------------------------------------------

    def test_applicant_workspace_shows_chinese_role_gap(self) -> None:
        application = _submit_application(
            member_no="role-gap-test",
            role_gap="community_contributor",
        )
        login_as_member(self.client, application.linked_member)
        response = self.client.get("/workspace/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "社区贡献者")
        self.assertNotContains(response, "community_contributor")

    # --- 报名列表按准入流程筛选 ----------------------------------------------------

    def test_review_list_filters_by_admission_status(self) -> None:
        application = _submit_application(member_no="filter-voting-test")
        # Auto-created proposal should be in VOTING.
        response = self.client.get("/workspace/applications/?status=voting")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, application.applicant_name)

        response = self.client.get("/workspace/applications/?status=admitted")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, application.applicant_name)

    def test_review_list_defaults_to_voting(self) -> None:
        _submit_application(member_no="filter-default-test")
        response = self.client.get("/workspace/applications/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "投票中")

    # --- 成员准入投票规则：只允许 yes/no，no 必须填写理由 ---------------------

    def test_detail_page_no_abstain_radio(self) -> None:
        """成员准入详情页不显示弃权投票选项。"""
        application = _submit_application(member_no="no-abstain-radio")
        response = self.client.get(f"/workspace/applications/{application.application_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "赞成")
        self.assertContains(response, "反对")
        self.assertNotContains(response, 'value="abstain"')

    def test_post_abstain_rejected(self) -> None:
        """POST abstain 应被拒绝，不创建 ProposalVote。"""
        application = _submit_application(member_no="abstain-rejected")
        proposal = application.admission_proposal
        votes_before = ProposalVote.objects.filter(proposal=proposal).count()
        response = self.client.post(
            f"/workspace/proposals/{proposal.pk}/vote/",
            {"choice": "abstain"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "投票选项无效")
        self.assertEqual(ProposalVote.objects.filter(proposal=proposal).count(), votes_before)

    def test_yes_without_reason_succeeds(self) -> None:
        """投 yes 可以不填理由。"""
        application = _submit_application(member_no="yes-no-reason")
        proposal = application.admission_proposal
        response = self.client.post(
            f"/workspace/proposals/{proposal.pk}/vote/",
            {"choice": "yes", "reason": ""},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        vote = ProposalVote.objects.filter(proposal=proposal, voter_member=self.governance).first()
        self.assertIsNotNone(vote)
        self.assertEqual(vote.choice, ProposalVote.Choice.YES)

    def test_no_without_reason_rejected(self) -> None:
        """投 no 不填理由应被拒绝，不创建/更新投票。"""
        application = _submit_application(member_no="no-no-reason")
        proposal = application.admission_proposal
        votes_before = ProposalVote.objects.filter(proposal=proposal).count()
        response = self.client.post(
            f"/workspace/proposals/{proposal.pk}/vote/",
            {"choice": "no", "reason": ""},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "反对准入必须填写理由")
        self.assertEqual(ProposalVote.objects.filter(proposal=proposal).count(), votes_before)

    def test_no_with_reason_succeeds(self) -> None:
        """投 no 并填写理由可以成功，reason 被保存。"""
        application = _submit_application(member_no="no-with-reason")
        proposal = application.admission_proposal
        response = self.client.post(
            f"/workspace/proposals/{proposal.pk}/vote/",
            {"choice": "no", "reason": "能力不足"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        vote = ProposalVote.objects.filter(proposal=proposal, voter_member=self.governance).first()
        self.assertIsNotNone(vote)
        self.assertEqual(vote.choice, ProposalVote.Choice.NO)
        self.assertEqual(vote.reason, "能力不足")
