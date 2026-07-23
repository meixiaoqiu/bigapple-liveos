from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.application_services import (
    submit_member_application,
    create_approval_proposal_for_application,
)
from core.member_roles import ROLE_FORMAL_MEMBER
from core.models import (
    ApprovalProposal,
    ApprovalDecision,
    Member,
    MemberApplication,
)
from core.proposal_services import (
    approve_proposal,
    execute_proposal,
    reject_proposal,
)
from core.tests.helpers import (
    create_governance_admin_member,
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
        self.governance = create_governance_admin_member("gov-review-0001")
        login_as_member(self.client, self.governance)

    # --- 入口与权限 ------------------------------------------------

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

    # --- 创建 ApprovalProposal ------------------------------------

    def test_governance_can_create_approval_proposal(self) -> None:
        application = _submit_application()
        ap = create_approval_proposal_for_application(
            application=application, submitted_by=self.governance,
        )
        self.assertEqual(ap.proposal_type, ApprovalProposal.ProposalType.MEMBER_APPLICATION)
        self.assertEqual(ap.status, ApprovalProposal.Status.SUBMITTED)
        self.assertTrue(ap.target_id)

    def test_create_approval_proposal_idempotent(self) -> None:
        application = _submit_application()
        ap1 = create_approval_proposal_for_application(
            application=application, submitted_by=self.governance,
        )
        ap2 = create_approval_proposal_for_application(
            application=application, submitted_by=self.governance,
        )
        self.assertEqual(ap1.pk, ap2.pk)

    # --- approve / reject / execute --------------------------------

    def test_governance_approve_single_tier(self) -> None:
        application = _submit_application()
        ap = create_approval_proposal_for_application(
            application=application, submitted_by=self.governance,
        )
        approve_proposal(proposal=ap, approved_by=self.governance, role="governance")
        ap.refresh_from_db()
        self.assertEqual(ap.status, ApprovalProposal.Status.APPROVED)

    def test_execute_admits_member(self) -> None:
        application = _submit_application()
        ap = create_approval_proposal_for_application(
            application=application, submitted_by=self.governance,
        )
        approve_proposal(proposal=ap, approved_by=self.governance, role="governance")
        execute_proposal(proposal=ap, actor=self.governance)

        application.refresh_from_db()
        member = application.linked_member
        member.refresh_from_db()
        self.assertEqual(application.status, MemberApplication.Status.ADMITTED)
        self.assertEqual(member.status, Member.Status.ADMITTED)
        self.assertIn(ROLE_FORMAL_MEMBER, member.active_role_names())

    def test_reject_sets_application_rejected(self) -> None:
        application = _submit_application()
        ap = create_approval_proposal_for_application(
            application=application, submitted_by=self.governance,
        )
        reject_proposal(proposal=ap, rejected_by=self.governance, role="governance")
        application.refresh_from_db()
        self.assertEqual(application.status, MemberApplication.Status.REJECTED)

    def test_execute_idempotent(self) -> None:
        application = _submit_application()
        ap = create_approval_proposal_for_application(
            application=application, submitted_by=self.governance,
        )
        approve_proposal(proposal=ap, approved_by=self.governance, role="governance")
        execute_proposal(proposal=ap, actor=self.governance)
        # Second execution should be idempotent
        execute_proposal(proposal=ap, actor=self.governance)
        application.refresh_from_db()
        self.assertEqual(application.status, MemberApplication.Status.ADMITTED)

    def test_unapproved_cannot_execute(self) -> None:
        application = _submit_application()
        ap = create_approval_proposal_for_application(
            application=application, submitted_by=self.governance,
        )
        from core.exceptions import DomainError
        with self.assertRaises(DomainError):
            execute_proposal(proposal=ap, actor=self.governance)

    # --- 普通成员权限 ---------------------------------------------

    def test_regular_member_cannot_approve(self) -> None:
        application = _submit_application()
        ap = create_approval_proposal_for_application(
            application=application, submitted_by=self.governance,
        )
        regular = create_member("mem-reg-000x", role_name=ROLE_FORMAL_MEMBER, status=Member.Status.ADMITTED)
        from core.exceptions import DomainError
        with self.assertRaises(DomainError):
            approve_proposal(proposal=ap, approved_by=regular, role="governance")

    # --- 审核详情页 -----------------------------------------------

    def test_detail_page_shows_application_info(self) -> None:
        application = _submit_application()
        ap = create_approval_proposal_for_application(
            application=application, submitted_by=self.governance,
        )
        response = self.client.get(f"/workspace/applications/{application.application_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "成员准入提案")

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
