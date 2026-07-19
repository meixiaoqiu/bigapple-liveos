from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from core.member_roles import ROLE_FORMAL_MEMBER
from core.models import (
    CapacityAssessment,
    Dispute,
    Event,
    LedgerEntry,
    Member,
    MemberApplication,
    RoleAssignment,
    Resource,
    Task,
)
from core.tests.helpers import create_member, login_as_member


class WorkspacePageTests(TestCase):
    """覆盖成员工作台最小页面的关键内容渲染。"""

    def setUp(self) -> None:
        now = timezone.now()
        self.member = create_member(
            member_no="mem-0001",
            role_name=ROLE_FORMAL_MEMBER,
            status=Member.Status.ADMITTED,
            batch_id="batch-opening",
            joined_simulation_day=1,
            credit_floor=-300,
            profile={"satisfaction": 64, "fatigue": 18},
            created_at=now,
        )
        active_task = Task.objects.create(
            task_id="task-0001",
            title="准备今日午餐",
            task_type=Task.TaskType.COOKING,
            status=Task.Status.CLAIMED,
            standard_hours=Decimal("3.50"),
            base_points=30,
            role_coefficient=Decimal("1.200"),
            can_be_delayed=False,
            requires_review=True,
            failure_consequence=Task.FailureConsequence.HIGH,
            assignee_member=self.member,
            rule_version="ruleset-v0.1.0",
            created_at=now,
        )
        Task.objects.create(
            task_id="task-0002",
            title="整理临时仓库货架",
            task_type=Task.TaskType.WAREHOUSE,
            status=Task.Status.OPEN,
            standard_hours=Decimal("2.50"),
            base_points=24,
            role_coefficient=Decimal("1.100"),
            can_be_delayed=True,
            requires_review=True,
            failure_consequence=Task.FailureConsequence.MEDIUM,
            rule_version="ruleset-v0.1.0",
            created_at=now,
        )
        Task.objects.create(
            task_id="task-0003",
            title="清理公共厨房",
            task_type=Task.TaskType.PUBLIC_CLEANING,
            status=Task.Status.ACCEPTED,
            standard_hours=Decimal("2.00"),
            base_points=20,
            role_coefficient=Decimal("1.000"),
            can_be_delayed=False,
            requires_review=True,
            failure_consequence=Task.FailureConsequence.MEDIUM,
            assignee_member=self.member,
            rule_version="ruleset-v0.1.0",
            created_at=now,
            submitted_at=now,
            reviewed_at=now,
            metadata={"labor_note": "已完成厨房台面清理。", "review_reason": "验收通过。"},
        )
        Resource.objects.create(
            resource_id="res-medicine",
            resource_type=Resource.ResourceType.MEDICINE,
            unit=Resource.Unit.COUNT,
            current_stock=Decimal("18"),
            daily_consumption_estimate=Decimal("6"),
            replenishment_method=Resource.ReplenishmentMethod.PURCHASE,
            loss_rate=Decimal("0.01000"),
            warning_threshold=Decimal("30"),
            shortage_impact={"health_risk_delta": 24},
            updated_at=now,
            rule_version="ruleset-v0.1.0",
        )
        event = Event.objects.create(
            event_id="event-0001",
            event_type=Event.EventType.TASK,
            simulation_day=1,
            severity=Event.Severity.INFO,
            title="任务已领取",
            summary="成员已领取任务。",
            involved_member_ids=[self.member.member_no],
            related_task=active_task,
            occurred_at=now,
            generated_by=Event.GeneratedBy.LIVE_OS,
            visibility=Event.Visibility.PUBLIC,
            payload={},
        )
        LedgerEntry.objects.create(
            ledger_entry_id="ledger-0001",
            member=self.member,
            amount=10,
            entry_type=LedgerEntry.EntryType.CONTRIBUTION,
            reason="历史贡献积分",
            related_task=active_task,
            related_event_id=event.event_id,
            rule_version="ruleset-v0.1.0",
            created_at=now,
            created_by={"actor_id": "member-admin-0001", "actor_type": "human_member"},
            status=LedgerEntry.Status.POSTED,
        )
        Dispute.objects.create(
            dispute_id="dispute-0001",
            dispute_type=Dispute.DisputeType.TASK_REVIEW,
            status=Dispute.Status.IN_REVIEW,
            claimant_member=self.member,
            related_task=active_task,
            facts="成员申请复核任务验收标准。",
            evidence_refs=[event.event_id],
            handler={},
            reviewer={},
            resolution="",
            appeal_path="standard-review-appeal",
            submitted_at=now,
        )
        CapacityAssessment.objects.create(
            assessment_id="capacity-0001",
            simulation_day=7,
            current_formal_members=100,
            current_candidate_members=900,
            maximum_admissible_members=130,
            recommended_new_members=20,
            bottlenecks=["canteen"],
            risk_indicators={"task_gap": 18},
            reasons=["食堂承载接近风险阈值。"],
            rule_version="ruleset-v0.1.0",
            created_at=now,
        )
        login_as_member(self.client, self.member)

    def test_workspace_page_renders_member_state(self) -> None:
        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "成员工作台")
        self.assertContains(response, "mem-0001")
        self.assertContains(response, "模拟第 7 天")
        self.assertContains(response, "当前积分")
        self.assertContains(response, "10")
        self.assertContains(response, "准备今日午餐")
        self.assertContains(response, "整理临时仓库货架")
        self.assertContains(response, "历史贡献积分")
        self.assertContains(response, "药品")
        self.assertContains(response, "任务已领取")
        self.assertContains(response, "成员申请复核任务验收标准")
        self.assertContains(response, "提交劳动")
        self.assertContains(response, "提交申诉")
        self.assertContains(response, "个人任务历史")
        self.assertContains(response, "清理公共厨房")
        self.assertContains(response, "申诉状态")
        self.assertContains(response, "standard-review-appeal")

    def test_pending_applicant_sees_minimal_workspace_and_cannot_post_actions(self) -> None:
        now = timezone.now()
        applicant = create_member(member_no="pending-applicant", status=Member.Status.PENDING_REVIEW)
        user = login_as_member(self.client, applicant)
        applicant.user = user
        applicant.save(update_fields=["user"])
        MemberApplication.objects.create(
            application_id="member-application-pending",
            applicant_name="待审核申请者",
            contact="pending@example.test",
            motivation="等待审核。",
            role_gap="ai_engineer",
            availability_slots=["weekend"],
            capability_scores={"文档": 70},
            requested_member_no=applicant.member_no,
            account_user=user,
            linked_member=applicant,
            submitted_at=now,
            frozen_at=now,
            metadata={},
        )

        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "报名工作台")
        self.assertContains(response, "待审核")
        self.assertNotContains(response, "可领取任务")

        response = self.client.post("/workspace/tasks/task-0002/claim/")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Task.objects.get(task_id="task-0002").status, Task.Status.OPEN)

    @override_settings(
        SITE_FIXED_WORLD=True,
        SITE_WORLD_ID="simulation0001",
        SITE_WORLD_TYPE="simulation",
        SITE_WORLD_DATABASE_ALIAS="default",
        SITE_WORLD_DATABASE_NAME="test",
    )
    def test_workspace_page_uses_fixed_simulation_world_root_links(self) -> None:
        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.wsgi_request.world_id, "simulation0001")
        self.assertContains(response, "当前世界：simulation0001")
        self.assertContains(response, "/workspace/tasks/task-0001/submit-labor/")
        self.assertContains(response, "/workspace/tasks/task-0002/claim/")
        self.assertContains(response, "/workspace/disputes/")
        self.assertNotContains(response, "/world/")

    def test_workspace_post_redirect_keeps_current_world_prefix(self) -> None:
        response = self.client.post("/workspace/tasks/task-0002/claim/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/workspace/")
        claimed_task = Task.objects.get(task_id="task-0002")
        self.assertEqual(claimed_task.assignee_member, self.member)
        self.assertEqual(claimed_task.status, Task.Status.CLAIMED)

    def test_member_can_claim_open_task_from_workspace(self) -> None:
        response = self.client.post(
            "/workspace/tasks/task-0002/claim/",
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "已领取任务：整理临时仓库货架")
        claimed_task = Task.objects.get(task_id="task-0002")
        self.assertEqual(claimed_task.assignee_member, self.member)
        self.assertEqual(claimed_task.status, Task.Status.CLAIMED)
        self.assertContains(response, "当前任务")
        self.assertContains(response, "整理临时仓库货架")

    def test_workspace_claim_shows_error_for_non_open_task(self) -> None:
        response = self.client.post(
            "/workspace/tasks/task-0001/claim/",
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "领取失败")
        self.assertEqual(Task.objects.get(task_id="task-0001").assignee_member, self.member)

    def test_member_can_submit_labor_from_workspace(self) -> None:
        response = self.client.post(
            "/workspace/tasks/task-0001/submit-labor/",
            {
                "labor_note": "已完成今日午餐准备，餐台已清理。",
                "evidence_refs": "event-0001\nphoto-lunch-0001",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "已提交劳动记录：准备今日午餐")
        submitted_task = Task.objects.get(task_id="task-0001")
        self.assertEqual(submitted_task.status, Task.Status.PENDING_REVIEW)
        self.assertEqual(submitted_task.metadata["labor_note"], "已完成今日午餐准备，餐台已清理。")
        self.assertEqual(submitted_task.metadata["evidence_refs"], ["event-0001", "photo-lunch-0001"])
        self.assertContains(response, "待验收")
        self.assertContains(response, "等待验收结果")

    def test_workspace_submit_labor_requires_note(self) -> None:
        response = self.client.post(
            "/workspace/tasks/task-0001/submit-labor/",
            {"labor_note": "   ", "evidence_refs": "event-0001"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "提交失败：劳动说明不能为空。")
        task = Task.objects.get(task_id="task-0001")
        self.assertEqual(task.status, Task.Status.CLAIMED)
        self.assertNotIn("labor_note", task.metadata)

    def test_member_can_create_dispute_from_workspace(self) -> None:
        response = self.client.post(
            "/workspace/disputes/",
            {
                "dispute_type": Dispute.DisputeType.TASK_REVIEW,
                "related_task_id": "task-0001",
                "facts": "午餐任务验收标准需要复核。",
                "evidence_refs": "event-0001, photo-dispute-0001",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "已提交申诉：")
        created_dispute = Dispute.objects.exclude(dispute_id="dispute-0001").get()
        self.assertEqual(created_dispute.status, Dispute.Status.SUBMITTED)
        self.assertEqual(created_dispute.claimant_member, self.member)
        self.assertEqual(created_dispute.related_task_id, "task-0001")
        self.assertEqual(created_dispute.facts, "午餐任务验收标准需要复核。")
        self.assertEqual(created_dispute.evidence_refs, ["event-0001", "photo-dispute-0001"])
        self.assertEqual(created_dispute.appeal_path, "workspace-dispute")
        self.assertContains(response, "午餐任务验收标准需要复核")

    def test_workspace_create_dispute_requires_facts(self) -> None:
        dispute_count = Dispute.objects.count()

        response = self.client.post(
            "/workspace/disputes/",
            {
                "dispute_type": Dispute.DisputeType.TASK_REVIEW,
                "related_task_id": "task-0001",
                "facts": "   ",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "提交失败：申诉事实不能为空。")
        self.assertEqual(Dispute.objects.count(), dispute_count)

    def test_member_no_workspace_route_is_not_exposed(self) -> None:
        response = self.client.get("/u/mem-0002/workspace/")

        self.assertEqual(response.status_code, 404)

    def test_workspace_unauthenticated_shows_entry_page(self) -> None:
        """未登录访问 /workspace/ 展示入口门禁页，200，不 403。"""
        self.client.logout()
        response = self.client.get("/workspace/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "社区工作台")
        self.assertContains(response, "注册账号")
        self.assertContains(response, "登录已有账号")
        self.assertContains(response, "/register/")
        self.assertContains(response, "/login/?next=/workspace/")
        self.assertNotContains(response, "/observer/")
        self.assertContains(response, "申请正式成员")
        # 不应该包含旧的 forbidden 文案
        self.assertNotContains(response, "需要登录并绑定成员身份")

    def test_staff_without_member_binding_cannot_open_workspace(self) -> None:
        staff_user = get_user_model().objects.create_user(username="staff-user", password="test-password")
        staff_user.is_staff = True
        staff_user.save(update_fields=["is_staff"])
        self.client.force_login(staff_user)

        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 403)


class WorkspaceAccessRoleTests(TestCase):
    """Full workspace access gated by ROLE_FORMAL_MEMBER, not Member.status."""

    def _active_member(self, member_no: str, status: str = Member.Status.ACTIVE, role_name: str | None = None):
        kwargs = {"member_no": member_no, "status": status}
        if role_name:
            kwargs["role_name"] = role_name
        return create_member(**kwargs)

    def _formal_member(self, member_no: str, status: str = Member.Status.ACTIVE):
        skip = status in {Member.Status.SUSPENDED, Member.Status.EXITED}
        return create_member(member_no=member_no, role_name=ROLE_FORMAL_MEMBER, status=status,
                             skip_role_validation=skip)

    # ── status alone does NOT grant full workspace ──

    def test_active_status_without_formal_role_no_full_workspace(self) -> None:
        member = self._active_member("mem-act-norole")
        login_as_member(self.client, member)
        response = self.client.get("/workspace/")
        self.assertEqual(response.status_code, 200)
        # must be minimal / applicant workspace, not full workspace
        self.assertNotContains(response, "可领取任务")
        self.assertNotContains(response, "提交劳动")

    def test_admitted_status_without_formal_role_no_full_workspace(self) -> None:
        member = self._active_member("mem-adm-norole", status=Member.Status.ADMITTED)
        login_as_member(self.client, member)
        response = self.client.get("/workspace/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "可领取任务")

    # ── ROLE_FORMAL_MEMBER grants full workspace ──

    def test_formal_role_non_disabled_status_has_full_workspace(self) -> None:
        member = self._formal_member("mem-formal-active")
        login_as_member(self.client, member)
        response = self.client.get("/workspace/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "成员工作台")
        self.assertContains(response, "mem-formal-active")

    def test_formal_role_pending_review_status_has_full_workspace(self) -> None:
        member = create_member(member_no="mem-formal-pend", role_name=ROLE_FORMAL_MEMBER, status=Member.Status.PENDING_REVIEW)
        login_as_member(self.client, member)
        response = self.client.get("/workspace/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "成员工作台")

    # ── SUSPENDED / EXITED veto ──

    def test_formal_role_suspended_denied_full_workspace(self) -> None:
        member = self._formal_member("mem-formal-susp", status=Member.Status.SUSPENDED)
        login_as_member(self.client, member)
        response = self.client.get("/workspace/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "可领取任务")

    def test_formal_role_exited_denied_full_workspace(self) -> None:
        member = self._formal_member("mem-formal-exit", status=Member.Status.EXITED)
        login_as_member(self.client, member)
        response = self.client.get("/workspace/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "可领取任务")

    # ── status change from active → suspended revokes access ──

    def test_active_to_suspended_revokes_full_workspace(self) -> None:
        member = self._formal_member("mem-active2susp")
        login_as_member(self.client, member)
        self.assertEqual(self.client.get("/workspace/").status_code, 200)
        member.status = Member.Status.SUSPENDED
        member.save(update_fields=["status"])
        response = self.client.get("/workspace/")
        self.assertNotContains(response, "可领取任务")
