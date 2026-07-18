from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.member_roles import ROLE_CANDIDATE, ROLE_CONTRIBUTOR
from core.models import (
    CapacityAssessment,
    Event,
    Member,
    PlanNode,
    PlanRevision,
    ProjectPlan,
    Resource,
    SimulationFailure,
    SimulationRun,
    SimulationSnapshot,
    SimulationSnapshotItem,
    Task,
)
from core.tests.helpers import create_member, login_as_member
from observer.theme import THEME_SESSION_KEY



class ObserverPageTests(TestCase):
    """覆盖面向公开首页的关键指标渲染。"""

    observer_base = ""

    def observer_url(self, path: str = "") -> str:
        return "/" + path

    def setUp(self) -> None:
        now = timezone.now()
        create_member(
            member_no="mem-0001",
            role_name=ROLE_CONTRIBUTOR,
            status=Member.Status.ADMITTED,
            joined_simulation_day=1,
            credit_floor=-300,
            profile={"satisfaction": 64},
            created_at=now,
        )
        create_member(
            member_no="candidate-0001",
            role_name=ROLE_CANDIDATE,
            status=Member.Status.PENDING_REVIEW,
            credit_floor=-100,
            profile={},
            created_at=now,
        )
        task = Task.objects.create(
            task_id="task-0001",
            title="准备今日午餐",
            task_type=Task.TaskType.COOKING,
            status=Task.Status.ACCEPTED,
            standard_hours=Decimal("3.50"),
            base_points=30,
            role_coefficient=Decimal("1.200"),
            can_be_delayed=False,
            requires_review=True,
            failure_consequence=Task.FailureConsequence.HIGH,
            rule_version="ruleset-v0.1.0",
            created_at=now,
        )
        Resource.objects.create(
            resource_id="res-grain",
            resource_type=Resource.ResourceType.GRAIN,
            unit=Resource.Unit.KG,
            current_stock=Decimal("1250"),
            daily_consumption_estimate=Decimal("180"),
            replenishment_method=Resource.ReplenishmentMethod.PURCHASE,
            loss_rate=Decimal("0.02000"),
            warning_threshold=Decimal("600"),
            shortage_impact={},
            updated_at=now,
            rule_version="ruleset-v0.1.0",
        )
        Event.objects.create(
            event_id="event-task-0001",
            event_type=Event.EventType.TASK,
            simulation_day=1,
            severity=Event.Severity.INFO,
            title="午餐任务验收通过",
            summary="任务 task-0001 已验收通过。",
            involved_member_ids=["mem-0001"],
            related_task=task,
            occurred_at=now,
            generated_by=Event.GeneratedBy.LIVE_OS,
            visibility=Event.Visibility.PUBLIC,
            payload={},
        )
        CapacityAssessment.objects.create(
            assessment_id="capacity-0001",
            simulation_day=7,
            current_formal_members=100,
            current_candidate_members=900,
            maximum_admissible_members=130,
            recommended_new_members=20,
            bottlenecks=["canteen", "hygiene"],
            risk_indicators={"canteen_load": 82, "task_gap": 18},
            reasons=["食堂承载接近风险阈值。"],
            rule_version="ruleset-v0.1.0",
            created_at=now,
        )
        plan = ProjectPlan.objects.create(
            plan_id="plan-bigapple001",
            name="bigapple001据点执行计划",
            status=ProjectPlan.Status.ACTIVE,
            description="覆盖从 0 到 100% 的据点执行计划。",
            target_location="bigapple001据点",
            owner={"actor_id": "member-admin-0001"},
            created_at=now,
            updated_at=now,
        )
        self.revision = PlanRevision.objects.create(
            revision_id="plan-bigapple001-rev-v0_1_0",
            plan=plan,
            revision_code="v0.1.0",
            status=PlanRevision.Status.PUBLISHED,
            title="第一版执行计划",
            change_summary="测试观察台主线计划展示。",
            created_at=now,
            published_at=now,
        )
        self.plan_node = PlanNode.objects.create(
            node_id="node-bigapple001-b1",
            revision=self.revision,
            sequence=10,
            code="B1",
            title="建立临时公共食堂",
            node_type=PlanNode.NodeType.WORK_PACKAGE,
            status=PlanNode.Status.IN_PROGRESS,
            is_required=True,
            is_expandable=False,
            allow_simulation_adjustment=True,
            planned_duration_days=5,
            estimated_cost_low=Decimal("176000.00"),
            estimated_cost_expected=Decimal("220000.00"),
            estimated_cost_high=Decimal("275000.00"),
            required_people_min=10,
            required_people_max=24,
            required_person_days=Decimal("120.00"),
            completion_criteria=["每日可供应 100 人三餐"],
            created_at=now,
            updated_at=now,
        )

    def create_public_simulation_snapshot(self, *, scenario: str = "") -> SimulationSnapshot:
        failure_summary = {
            "failure_type": SimulationFailure.FailureType.RESPONSIBILITY_CLOSURE_MISSING,
            "title": "C3 光伏一期 0.5MW 责任闭环缺失",
            "description": "缺少结构、光伏、电气、施工与验收责任文件。",
        }
        if scenario:
            failure_summary["metadata"] = {"scenario": scenario}
        snapshot = SimulationSnapshot.objects.create(
            snapshot_id="snapshot-public-0001",
            title="simulation0001 / sim-run-public / 责任闭环缺失",
            source_world_id="simulation0001",
            source_world_type="simulation",
            source_database_alias="default",
            source_database_name="test_control",
            source_run_id="sim-run-public",
            plan_revision_id=self.revision.revision_id,
            run_status=SimulationRun.Status.FAILED,
            failure_type=SimulationFailure.FailureType.RESPONSIBILITY_CLOSURE_MISSING,
            failure_title="C3 光伏一期 0.5MW 责任闭环缺失",
            snapshot_schema_version=1,
            status=SimulationSnapshot.Status.ARCHIVED,
            raw_archive_path="var/private/simulation_archives/snapshot-public-0001",
            raw_archive_hash="1234567890abcdef" * 4,
            report_path="var/private/simulation_archives/snapshot-public-0001/report.html",
            raw_table_counts={"core.SimulationRun": 1},
            normalized_summary={
                "counts": {
                    "turns": 2,
                    "events": 1,
                    "node_states": 1,
                    "failures": 1,
                    "proposals": 1,
                    "change_sets": 1,
                    "change_operations": 2,
                },
                "failures": [failure_summary],
                "change_sets": [
                    {
                        "change_set_id": "change-set-public-0001",
                        "title": "补齐光伏一期责任闭环",
                        "summary": "下一轮推演前置并网预筛、结构安全责任文件和电气并网责任文件。",
                    }
                ],
            },
            code_version="test",
            archived_at=timezone.now(),
            metadata={},
        )
        SimulationSnapshotItem.objects.create(
            item_id="snapshot-public-0001:turn-0001",
            snapshot=snapshot,
            item_type=SimulationSnapshotItem.ItemType.TURN,
            source_model="core.SimulationTurn",
            source_pk="turn-public-0001",
            title="第 1 步",
            summary="模拟完成 B1，并继续推进到 C3 前置责任校验。",
            sort_order=1001,
            payload_json={},
        )
        SimulationSnapshotItem.objects.create(
            item_id="snapshot-public-0001:failure-0001",
            snapshot=snapshot,
            item_type=SimulationSnapshotItem.ItemType.FAILURE,
            source_model="core.SimulationFailure",
            source_pk="failure-public-0001",
            title="C3 光伏一期 0.5MW 责任闭环缺失",
            summary="缺少结构、光伏、电气、施工与验收责任文件。",
            sort_order=2001,
            payload_json={},
        )
        return snapshot

    def test_observer_prefix_route_is_removed(self) -> None:
        """旧 /observer/ 路径应 404，首页已移至 /。"""
        self.assertEqual(self.client.get("/observer/").status_code, 404)
        self.assertEqual(self.client.get("/observer/events/").status_code, 404)
        # / 现在是首页
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_old_members_path_returns_404(self) -> None:
        """旧 /members/<no>/ 返回 404，新路径是 /u/<no>/。"""
        self.assertEqual(self.client.get("/members/test-01/").status_code, 404)

    def test_observer_page_renders_core_state(self) -> None:
        response = self.client.get(self.observer_url())

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "/live-admin/")
        self.assertNotContains(response, "/admin/core/member/")
        self.assertNotContains(response, "/admin/core/ruleset/")
        self.assertContains(response, "大苹果社区动态")
        self.assertContains(response, "bigapple001据点")
        self.assertContains(response, "活跃成员")
        self.assertContains(response, "当前容量")
        self.assertContains(response, "任务完成率")
        self.assertContains(response, "资源预警")
        self.assertContains(response, "未关闭申诉")
        self.assertContains(response, "事件时间线")
        self.assertContains(response, "午餐任务验收通过")
        self.assertContains(response, "高负载角色")
        self.assertContains(response, "仿真档案馆")

    def test_public_simulation_archive_lists_reports_without_login(self) -> None:
        snapshot = self.create_public_simulation_snapshot()

        response = self.client.get(self.observer_url("simulations/"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "仿真档案馆")
        self.assertContains(response, "把失败提前发生在仿真里")
        self.assertContains(response, "C3 光伏一期 0.5MW 责任闭环缺失")
        self.assertContains(response, "低成本开荒不等于用成员自评替代专业责任")
        self.assertContains(response, snapshot.snapshot_id)
        self.assertNotContains(response, snapshot.raw_archive_path)

    def test_public_simulation_report_detail_shows_traceable_report_without_raw_path(self) -> None:
        snapshot = self.create_public_simulation_snapshot()

        response = self.client.get(self.observer_url(f"simulations/{snapshot.snapshot_id}/"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "关键发现")
        self.assertContains(response, "修订方向")
        self.assertContains(response, "仍需回答")
        self.assertContains(response, "可追溯时间线")
        self.assertContains(response, "缺少结构、光伏、电气、施工与验收责任文件")
        self.assertContains(response, "下一轮推演前置并网预筛")
        self.assertContains(response, "原始归档哈希")
        self.assertContains(response, "1234567890abcdef")
        self.assertNotContains(response, snapshot.raw_archive_path)

    def test_public_zero_start_report_detail_explains_recruitment_screening_baseline(self) -> None:
        snapshot = self.create_public_simulation_snapshot(scenario="zero_start")

        response = self.client.get(self.observer_url(f"simulations/{snapshot.snapshot_id}/"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "本次推演从一个发起人开始")
        self.assertContains(response, "项目真正的零起点不是 A0 抵达")
        self.assertContains(response, "报名数量不是核心")
        self.assertContains(response, "报名者画像应如何验证")

    def test_observer_page_injects_default_theme_context(self) -> None:
        response = self.client.get(self.observer_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-theme="light"')
        self.assertEqual(response.context["active_theme"], "default_game")
        self.assertEqual(response.context["daisy_theme"], "light")
        self.assertIn("default_game", {theme["key"] for theme in response.context["available_themes"]})
        self.assertNotIn("selected_task", response.context["dashboard_context"])

    def test_switch_theme_stores_session_and_falls_back_to_default_templates(self) -> None:
        response = self.client.post(self.observer_url("themes/switch/"), {"theme": "dark", "next": self.observer_url()})

        self.assertRedirects(response, self.observer_url())
        self.assertEqual(self.client.session[THEME_SESSION_KEY], "dark")

        page_response = self.client.get(self.observer_url())
        self.assertContains(page_response, 'data-theme="dark"')
        self.assertContains(page_response, "事件时间线")
        self.assertContains(page_response, "当前风险总览")

        partial_response = self.client.get(self.observer_url("dashboard/partials/risk/"))
        self.assertEqual(partial_response.status_code, 200)
        self.assertContains(partial_response, "高风险")

    def test_dashboard_theme_partials_render_with_active_theme(self) -> None:
        self.client.post(self.observer_url("themes/switch/"), {"theme": "dark", "next": self.observer_url()})

        expectations = {
            self.observer_url("dashboard/partials/missions/"): "建立临时公共食堂",
            self.observer_url("dashboard/partials/events/"): "午餐任务验收通过",
            self.observer_url("dashboard/partials/map-points/"): "核心区",
            self.observer_url("dashboard/partials/risk/"): "高风险",
            self.observer_url("dashboard/partials/capacity/"): "当前容量",
        }
        for path, expected_text in expectations.items():
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, expected_text)

    def test_public_observer_event_feed_uses_safe_human_operator_summary(self) -> None:
        Event.objects.create(
            event_id="event-human-operator-private-summary",
            event_type=Event.EventType.RESOURCE,
            simulation_day=1,
            severity=Event.Severity.WARNING,
            title="库存人工调整",
            summary="库存因内部 operator note 调整，包含不应公开的治理原因。",
            involved_member_ids=["mem-0001"],
            occurred_at=timezone.now() + timedelta(seconds=1),
            generated_by=Event.GeneratedBy.HUMAN_OPERATOR,
            visibility=Event.Visibility.PUBLIC,
            payload={"reason": "internal operator note"},
        )

        response = self.client.get(self.observer_url("dashboard/partials/events/"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "库存人工调整")
        self.assertNotContains(response, "internal operator note")
        self.assertNotContains(response, "不应公开的治理原因")

    def test_observer_risk_panel_shows_simulation_responsibility_closure_failure(self) -> None:
        pv_node = PlanNode.objects.create(
            node_id="node-bigapple001-c3",
            revision=self.revision,
            sequence=30,
            code="C3",
            title="光伏一期 0.5MW",
            node_type=PlanNode.NodeType.EXPANSION,
            status=PlanNode.Status.PLANNED,
            is_required=True,
            planned_duration_days=21,
            estimated_cost_expected=Decimal("2500000.00"),
            required_people_min=12,
            required_people_max=36,
            required_person_days=Decimal("450.00"),
            completion_criteria=[],
            created_at=timezone.now(),
            updated_at=timezone.now(),
        )
        run = SimulationRun.objects.create(
            run_id="sim-run-responsibility",
            plan_revision=self.revision,
            status=SimulationRun.Status.FAILED,
            current_day=9,
            max_turns=30,
            started_at=timezone.now(),
            ended_at=timezone.now(),
            failure_summary="责任闭环缺失",
            metadata={},
        )
        SimulationFailure.objects.create(
            failure_id="failure-responsibility",
            run=run,
            plan_node=pv_node,
            failure_type=SimulationFailure.FailureType.RESPONSIBILITY_CLOSURE_MISSING,
            severity=SimulationFailure.Severity.CRITICAL,
            title="C3 光伏一期 0.5MW 责任闭环缺失",
            description="C3 光伏一期 0.5MW 进入采购、施工、调试或并网前，缺少关键责任闭环。",
            simulation_day=9,
            detected_at=timezone.now(),
            metadata={
                "missing_responsibility_closures": [
                    {"label": "结构/建筑安全责任文件", "status": "未取得"},
                    {"label": "光伏系统设计责任文件", "status": "未取得"},
                    {"label": "电气接入与并网责任文件", "status": "未取得"},
                    {"label": "施工安全与质量责任主体", "status": "未确认"},
                    {"label": "验收与归档责任安排", "status": "未确认"},
                ],
                "cannot_continue_reasons": ["没有机构或责任人对屋顶/场地承载能力出具书面结论。"],
                "recommended_actions": ["租场地前先做并网预筛。"],
            },
        )

        response = self.client.get(self.observer_url("dashboard/partials/risk/"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "仿真失败核心原因")
        self.assertContains(response, "失败节点：C3 光伏一期 0.5MW")
        self.assertContains(response, "失败类型：责任闭环缺失")
        self.assertContains(response, "结构/建筑安全责任文件")
        self.assertContains(response, "电气接入与并网责任文件")
        self.assertContains(response, "租场地前先做并网预筛")

    # ── top-nav / auth-aware navigation ─────────────────────────────────

    def test_homepage_nav_unauthenticated(self) -> None:
        """未登录首页导航包含注册、登录、Workspace。"""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "/register/")
        self.assertContains(response, "/login/?next=/workspace/")
        self.assertContains(response, "/workspace/")

    def test_homepage_nav_authenticated_with_member(self) -> None:
        """已登录且有 Member 的首页导航包含我的主页、Workspace、退出，不含注册/登录。"""
        member = create_member(
            member_no="nav-member-01",
            status=Member.Status.ADMITTED,
            batch_id="batch-opening",
            joined_simulation_day=1,
            credit_floor=-100,
            profile={"display_name": "导航测试"},
            created_at=timezone.now(),
        )
        login_as_member(self.client, member)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "/u/nav-member-01/")
        self.assertContains(response, "/workspace/")
        self.assertContains(response, 'method="post" action="/logout/"', html=False)
        self.assertNotContains(response, 'href="/logout/"')
        self.assertNotContains(response, "/register/")
        self.assertNotContains(response, "/login/")

    def test_homepage_nav_authenticated_no_member(self) -> None:
        """已登录但无 Member 的首页导航不包含 /u/。"""
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.create_user(username="nav-no-member", password="pass")
        self.client.force_login(user)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "/workspace/")
        self.assertContains(response, 'method="post" action="/logout/"', html=False)
        self.assertNotContains(response, 'href="/logout/"')
        self.assertNotContains(response, "/u/")

