from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import resolve
from django.utils import timezone

from core.member_roles import ROLE_COVENANTER
from core.models import (
    CapacityAssessment,
    EventFeedback,
    Event,
    LedgerEntry,
    Member,
    MemberApplication,
    RoleAssignment,
    Resource,
    Task,
)
from core.openfga_client import OpenFGARequestError
from core.tests.helpers import create_member, login_as_member


class WorkspacePageTests(TestCase):
    """覆盖成员工作台最小页面的关键内容渲染。"""

    def setUp(self) -> None:
        now = timezone.now()
        self.member = create_member(
            member_no="mem-0001",
            role_name=ROLE_COVENANTER,
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
            standard_minutes=210,
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
            standard_minutes=150,
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
            standard_minutes=120,
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
        EventFeedback.objects.create(
            feedback_id="feedback-0001", related_event=event,
            feedback_type=EventFeedback.FeedbackType.REVIEW,
            status=EventFeedback.Status.VERIFYING,
            submitted_by=self.member,
            statement="成员申请复核任务验收标准。",
            requested_outcome="请核实。",
            evidence_refs=[event.event_id],
            submitted_at=now,
        )
        CapacityAssessment.objects.create(
            assessment_id="capacity-0001",
            simulation_day=7,
            current_covenanters=100,
            current_contributors=900,
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
        self.assertContains(response, "任务中心")
        self.assertContains(response, "历史贡献积分")
        self.assertNotContains(response, "资源预警")
        self.assertNotContains(response, "相关事件")
        self.assertContains(response, "复核 · feedback-0001")
        self.assertContains(response, "/workspace/tasks/task-0001/")
        self.assertNotContains(response, "提交申诉")
        self.assertContains(response, "清理公共厨房")
        self.assertNotContains(response, "申诉状态")
        self.assertNotContains(response, "个人任务历史")

    def test_member_can_open_own_task_detail(self) -> None:
        response = self.client.get("/workspace/tasks/task-0003/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "清理公共厨房")
        self.assertContains(response, "任务信息")

    def test_task_center_groups_visible_tasks(self) -> None:
        response = self.client.get("/workspace/tasks/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "任务中心")
        self.assertContains(response, "当前任务")
        self.assertContains(response, "准备今日午餐")
        self.assertContains(response, "可领取任务")
        self.assertContains(response, "整理临时仓库货架")
        self.assertContains(response, "最近结束")
        self.assertContains(response, "清理公共厨房")

    def test_member_can_open_open_task_detail_without_private_records(self) -> None:
        response = self.client.get("/workspace/tasks/task-0002/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "整理临时仓库货架")
        self.assertContains(response, "确认领取")
        self.assertNotContains(response, "劳动与验收记录")

    def test_member_cannot_open_another_members_task_detail(self) -> None:
        other = create_member("other-task-owner", role_name=ROLE_COVENANTER)
        Task.objects.filter(task_id="task-0003").update(assignee_member=other)
        response = self.client.get("/workspace/tasks/task-0003/")
        self.assertEqual(response.status_code, 404)

    def test_fixed_task_routes_are_not_captured_as_task_details(self) -> None:
        self.assertEqual(resolve("/workspace/tasks/").url_name, "workspace-tasks")
        self.assertEqual(resolve("/workspace/tasks/new/").url_name, "workspace-tasks-manage")
        self.assertEqual(resolve("/workspace/tasks/review/").url_name, "workspace-tasks-review")
        self.assertEqual(
            resolve("/workspace/tasks/task-0003/").url_name,
            "workspace-task-detail",
        )

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
        self.assertContains(response, "/workspace/tasks/")
        self.assertContains(response, "/workspace/tasks/task-0001/")
        self.assertNotContains(response, "/workspace/disputes/")
        self.assertNotContains(response, "/world/")

    def test_workspace_post_redirect_keeps_current_world_prefix(self) -> None:
        response = self.client.post("/workspace/tasks/task-0002/claim/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/workspace/tasks/task-0002/")
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
        self.assertContains(response, "提交劳动")
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
        self.assertContains(response, "劳动与验收记录")
        self.assertNotContains(response, "下一步动作")

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

    def test_workspace_does_not_expose_event_feedback_creation(self) -> None:
        response = self.client.post(
            "/workspace/disputes/",
            {},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(EventFeedback.objects.count(), 1)

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
        self.assertContains(response, "申请守约者")
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
    """Full workspace access gated by ROLE_COVENANTER, not Member.status."""

    def _active_member(self, member_no: str, status: str = Member.Status.ACTIVE, role_name: str | None = None):
        kwargs = {"member_no": member_no, "status": status}
        if role_name:
            kwargs["role_name"] = role_name
        return create_member(**kwargs)

    def _covenanter(self, member_no: str, status: str = Member.Status.ACTIVE):
        skip = status in {Member.Status.SUSPENDED, Member.Status.EXITED}
        return create_member(member_no=member_no, role_name=ROLE_COVENANTER, status=status,
                             skip_role_validation=skip)

    # ── status alone does NOT grant full workspace ──

    def test_active_status_without_covenanter_role_no_full_workspace(self) -> None:
        member = self._active_member("mem-act-norole")
        login_as_member(self.client, member)
        response = self.client.get("/workspace/")
        self.assertEqual(response.status_code, 200)
        # must be minimal / applicant workspace, not full workspace
        self.assertNotContains(response, "可领取任务")
        self.assertNotContains(response, "提交劳动")

    def test_admitted_status_without_covenanter_role_no_full_workspace(self) -> None:
        member = self._active_member("mem-adm-norole", status=Member.Status.ADMITTED)
        login_as_member(self.client, member)
        response = self.client.get("/workspace/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "可领取任务")

    # ── ROLE_COVENANTER grants full workspace ──

    def test_covenanter_role_non_disabled_status_has_full_workspace(self) -> None:
        member = self._covenanter("mem-covenanter-active")
        login_as_member(self.client, member)
        response = self.client.get("/workspace/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "成员工作台")
        self.assertContains(response, "mem-covenanter-active")
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_covenanter_role_pending_review_status_has_full_workspace(self) -> None:
        member = create_member(member_no="mem-covenanter-pend", role_name=ROLE_COVENANTER, status=Member.Status.PENDING_REVIEW)
        login_as_member(self.client, member)
        response = self.client.get("/workspace/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "成员工作台")

    # ── SUSPENDED / EXITED veto ──

    @override_settings(
        BIG_APPLE_AUTHORIZATION_BACKEND="openfga",
        OPENFGA_SIM_STORE_ID="store-id",
        OPENFGA_SIM_AUTHORIZATION_MODEL_ID="model-id",
    )
    def test_openfga_outage_does_not_crash_workspace(self) -> None:
        member = self._covenanter("mem-openfga-down")
        login_as_member(self.client, member)

        with patch("core.authorization_services.OpenFGAClient") as client_class:
            client_class.return_value.check.side_effect = OpenFGARequestError("OpenFGA check failed")
            response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "workspace/applicant.html")
        self.assertContains(response, "权限服务暂时不可用")
        self.assertNotContains(response, "审核完成前，此账号只能查看自己的报名状态")
        self.assertIn("no-store", response.headers["Cache-Control"])

    @override_settings(
        BIG_APPLE_AUTHORIZATION_BACKEND="openfga",
        OPENFGA_SIM_STORE_ID="store-id",
        OPENFGA_SIM_AUTHORIZATION_MODEL_ID="model-id",
    )
    def test_openfga_outage_action_forbidden_message_mentions_authorization_service(self) -> None:
        member = self._covenanter("mem-openfga-action-down")
        login_as_member(self.client, member)

        with patch("core.authorization_services.OpenFGAClient") as client_class:
            client_class.return_value.check.side_effect = OpenFGARequestError("OpenFGA check failed")
            response = self.client.post("/workspace/tasks/task-0002/claim/")

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "权限服务暂时不可用", status_code=403)

    def test_covenanter_role_suspended_denied_full_workspace(self) -> None:
        member = self._covenanter("mem-covenanter-susp", status=Member.Status.SUSPENDED)
        login_as_member(self.client, member)
        response = self.client.get("/workspace/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "可领取任务")

    def test_covenanter_role_exited_denied_full_workspace(self) -> None:
        member = self._covenanter("mem-covenanter-exit", status=Member.Status.EXITED)
        login_as_member(self.client, member)
        response = self.client.get("/workspace/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "可领取任务")

    # ── status change from active → suspended revokes access ──

    def test_active_to_suspended_revokes_full_workspace(self) -> None:
        member = self._covenanter("mem-active2susp")
        login_as_member(self.client, member)
        self.assertEqual(self.client.get("/workspace/").status_code, 200)
        member.status = Member.Status.SUSPENDED
        member.save(update_fields=["status"])
        response = self.client.get("/workspace/")
        self.assertNotContains(response, "可领取任务")
