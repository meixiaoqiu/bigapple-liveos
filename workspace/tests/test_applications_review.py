from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.application_services import (
    submit_member_application,
    create_approval_proposal_for_application,
)
from core.member_roles import ROLE_COVENANTER
from core.models import (
    ApprovalProposal,
    ApprovalDecision,
    Member,
    MemberApplication,
    ElectorateRuleVersion,
    ProposalBallot,
)
from core.proposal_services import (
    approve_proposal,
    create_approval_proposal,
    execute_proposal,
    reject_proposal,
)
from core.exceptions import DomainError
from core.proposal_migration import ProposalFlowUnavailable
from core.tests.helpers import (
    create_administrator_member,
    create_member,
    login_as_member,
)


def _submit_application(**overrides) -> MemberApplication:
    defaults = {
        "applicant_name": "审核测试报名者",
        "contact": "review-applicant@example.test",
        "motivation": "希望加入社区贡献力量。",
        "role_gap": "ai_engineer",
        "availability_slots": ["weekend"],
        "requested_member_no": f"review-app-{id(overrides)}",
    }
    defaults.update(overrides)
    return submit_member_application(**defaults)


class WorkspaceApplicationsReviewTests(TestCase):
    """成员报名审核模块：ApprovalProposal 准入审批。"""

    def setUp(self) -> None:
        self.governance = create_administrator_member("administrator-review-0001")
        login_as_member(self.client, self.governance)

    # --- 入口与权限 ------------------------------------------------

    def test_administrator_member_sees_review_entry_and_list(self) -> None:
        _submit_application()
        workspace = self.client.get("/workspace/")
        self.assertEqual(workspace.status_code, 200)
        self.assertContains(workspace, "成员报名审核")

        review = self.client.get("/workspace/applications/")
        self.assertEqual(review.status_code, 200)
        self.assertContains(review, "审核测试报名者")

    def test_empty_review_list_explains_unified_proposal_state(self) -> None:
        review = self.client.get("/workspace/applications/")

        self.assertEqual(review.status_code, 200)
        self.assertContains(review, "报名准入由统一提案系统处理")
        self.assertContains(review, "冻结的选民政策")

    def test_regular_form_member_cannot_see_entry_and_gets_403(self) -> None:
        member = create_member("mem-regular-0001", role_name=ROLE_COVENANTER, status=Member.Status.ADMITTED)
        login_as_member(self.client, member)
        review = self.client.get("/workspace/applications/")
        self.assertEqual(review.status_code, 403)

    def test_pending_review_applicant_cannot_see_entry_and_gets_403(self) -> None:
        application = _submit_application()
        login_as_member(self.client, application.linked_member)
        review = self.client.get("/workspace/applications/")
        self.assertEqual(review.status_code, 403)

    def test_superuser_without_member_binding_gets_403(self) -> None:
        user_model = get_user_model()
        superuser = user_model.objects.create_user(
            username="root-without-member", password="test-password-123",
            is_superuser=True, is_staff=True,
        )
        self.client.force_login(superuser)
        review = self.client.get("/workspace/applications/")
        self.assertEqual(review.status_code, 403)

    # --- 旧 Proposal vote/execute URL 已移除 -----------------------

    def test_old_proposal_vote_url_returns_404(self) -> None:
        response = self.client.post("/workspace/proposals/1/vote/", {"choice": "yes"})
        self.assertEqual(response.status_code, 404)

    def test_old_proposal_execute_url_returns_404(self) -> None:
        response = self.client.post("/workspace/proposals/1/execute/", {})
        self.assertEqual(response.status_code, 404)

    # --- 成员准入在统一提案迁移期间失败关闭 -----------------------

    def _raw_member_application_proposal(
        self, application: MemberApplication, *, status: str,
    ) -> ApprovalProposal:
        return ApprovalProposal.objects.create(
            proposal_id=f"member-application-proposal-{status}",
            proposal_type=ApprovalProposal.ProposalType.MEMBER_APPLICATION,
            dedupe_key=f"member-application:{application.application_id}:{status}",
            title="成员准入测试提案",
            submitted_by=self.governance,
            target_type="member_application",
            target_id=application.application_id,
            status=status,
        )

    def test_member_application_proposal_is_created_once_and_cannot_be_rebound_to_another_submitter(self) -> None:
        application = _submit_application()

        with self.assertRaises(DomainError):
            create_approval_proposal_for_application(
                application=application, submitted_by=self.governance,
            )

        self.assertEqual(
            ApprovalProposal.objects.filter(proposal_type=ApprovalProposal.ProposalType.MEMBER_APPLICATION).count(),
            1,
        )
        self.assertEqual(application.admission_proposal_id, application.admission_proposal.pk)

    def test_generic_proposal_service_cannot_create_member_application_proposal(self) -> None:
        application = _submit_application()

        with self.assertRaises(ProposalFlowUnavailable):
            create_approval_proposal(
                proposal_type=ApprovalProposal.ProposalType.MEMBER_APPLICATION,
                dedupe_key=f"member-application:{application.application_id}:generic",
                title="不得创建的成员准入提案",
                submitted_by=self.governance,
                target_type="member_application",
                target_id=application.application_id,
            )

        self.assertEqual(
            ApprovalProposal.objects.filter(proposal_type=ApprovalProposal.ProposalType.MEMBER_APPLICATION).count(),
            1,
        )

    def test_existing_member_application_proposal_cannot_be_approved(self) -> None:
        application = _submit_application()
        proposal = self._raw_member_application_proposal(
            application, status=ApprovalProposal.Status.SUBMITTED,
        )

        with self.assertRaises(ProposalFlowUnavailable):
            approve_proposal(
                proposal=proposal, approved_by=self.governance, role="governance",
            )

        proposal.refresh_from_db()
        application.refresh_from_db()
        self.assertEqual(proposal.status, ApprovalProposal.Status.SUBMITTED)
        self.assertEqual(application.status, MemberApplication.Status.SUBMITTED)
        self.assertFalse(ApprovalDecision.objects.filter(proposal=proposal).exists())

    def test_existing_member_application_proposal_cannot_be_rejected(self) -> None:
        application = _submit_application()
        proposal = self._raw_member_application_proposal(
            application, status=ApprovalProposal.Status.SUBMITTED,
        )

        with self.assertRaises(ProposalFlowUnavailable):
            reject_proposal(
                proposal=proposal, rejected_by=self.governance, role="governance",
            )

        proposal.refresh_from_db()
        application.refresh_from_db()
        self.assertEqual(proposal.status, ApprovalProposal.Status.SUBMITTED)
        self.assertEqual(application.status, MemberApplication.Status.SUBMITTED)
        self.assertIsNone(application.decided_by)
        self.assertFalse(ApprovalDecision.objects.filter(proposal=proposal).exists())

    def test_existing_member_application_proposal_cannot_be_executed(self) -> None:
        application = _submit_application()
        proposal = self._raw_member_application_proposal(
            application, status=ApprovalProposal.Status.APPROVED,
        )

        with self.assertRaises(ProposalFlowUnavailable):
            execute_proposal(proposal=proposal, actor=self.governance)

        proposal.refresh_from_db()
        application.refresh_from_db()
        application.linked_member.refresh_from_db()
        self.assertEqual(proposal.status, ApprovalProposal.Status.APPROVED)
        self.assertEqual(application.status, MemberApplication.Status.SUBMITTED)
        self.assertNotEqual(application.linked_member.status, Member.Status.ADMITTED)
        self.assertNotIn(ROLE_COVENANTER, application.linked_member.active_role_names())

    # --- 审核详情页 -----------------------------------------------

    def test_detail_page_shows_application_info(self) -> None:
        application = _submit_application()
        response = self.client.get(f"/workspace/applications/{application.application_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "准入决策")
        self.assertContains(response, "等待政策配置")
        self.assertContains(response, "进入统一提案页")

    # --- 角色显示 -------------------------------------------------

    def test_applicant_workspace_shows_chinese_role_gap(self) -> None:
        application = _submit_application(role_gap="content_recorder")
        login_as_member(self.client, application.linked_member)
        response = self.client.get("/workspace/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "内容记录方向")

    # --- 列表筛选 -------------------------------------------------

    def test_review_list_filters_by_status(self) -> None:
        application = _submit_application()
        response = self.client.get("/workspace/applications/?status=voting")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, application.applicant_name)

    def test_administrator_can_publish_policy_and_activate_waiting_application(self) -> None:
        application = _submit_application(requested_member_no="policy-ui-applicant")

        response = self.client.post(
            "/workspace/proposals/member-admission-policy/",
            {
                "role_codes": ["administrator"],
                "approve_threshold": "1",
                "reject_threshold": "1",
                "minimum_participation": "1",
                "voting_duration_hours": "168",
                "unresolved_outcome": ElectorateRuleVersion.UnresolvedOutcome.EXPIRED,
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "准入政策第 1 版已发布")
        application.admission_proposal.refresh_from_db()
        self.assertEqual(application.admission_proposal.status, ApprovalProposal.Status.VOTING)

    def test_non_administrator_cannot_open_policy_page(self) -> None:
        member = create_member("policy-regular", role_name=ROLE_COVENANTER, status=Member.Status.ADMITTED)
        login_as_member(self.client, member)

        response = self.client.get("/workspace/proposals/member-admission-policy/")

        self.assertEqual(response.status_code, 403)

    def test_snapshot_voter_can_vote_from_unified_proposal_page(self) -> None:
        application = _submit_application(requested_member_no="vote-ui-applicant")
        self.client.post(
            "/workspace/proposals/member-admission-policy/",
            {
                "role_codes": ["administrator"],
                "approve_threshold": "2",
                "reject_threshold": "2",
                "minimum_participation": "1",
                "voting_duration_hours": "168",
                "unresolved_outcome": "expired",
            },
        )
        proposal = ApprovalProposal.objects.get(pk=application.admission_proposal_id)

        page = self.client.get("/workspace/proposals/")
        vote = self.client.post(
            f"/workspace/proposals/{proposal.proposal_id}/vote/",
            {"choice": "approve", "reason": "愿意共同承担准入责任。"},
            follow=True,
        )

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, proposal.title)
        self.assertEqual(vote.status_code, 200)
        ballot = ProposalBallot.objects.get(proposal=proposal, voter=self.governance)
        self.assertEqual(ballot.choice, ProposalBallot.Choice.APPROVE)
