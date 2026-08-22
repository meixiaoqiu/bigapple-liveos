from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import resolve
from django.utils import timezone

from core.governance_setup import DELIBERATOR_EXAM_MANAGE_PERMISSION
from core.member_roles import ROLE_COVENANTER
from core.models import (
    CapacityAssessment,
    EventFeedback,
    Event,
    LedgerEntry,
    Member,
    MemberApplication,
    MerchantProfile,
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
        self.assertContains(response, "准备今日午餐")
        self.assertContains(response, "任务中心")
        self.assertNotContains(response, "当前积分")
        self.assertNotContains(response, "可用积分")
        self.assertNotContains(response, "历史贡献积分")
        self.assertNotContains(response, "近期积分流水")
        self.assertNotContains(response, "资源预警")
        self.assertNotContains(response, "相关事件")
        self.assertContains(response, "复核 · feedback-0001")
        self.assertContains(response, "/workspace/tasks/task-0001/")
        self.assertNotContains(response, "提交申诉")
        self.assertContains(response, "清理公共厨房")
        self.assertNotContains(response, "申诉状态")
        self.assertNotContains(response, "个人任务历史")

    def test_workspace_page_uses_centered_480px_portrait_shell(self) -> None:
        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(
            'class="mx-auto min-h-screen w-full max-w-[480px] bg-white" data-workspace-shell="app"',
            content,
        )
        self.assertIn(
            'class="w-full" data-workspace-shell="header"',
            content,
        )
        self.assertIn(
            'class="grid w-full gap-6 p-4" data-workspace-shell="main"',
            content,
        )
        self.assertIn('<body class="min-h-screen bg-base-200 text-base-content">', content)
        self.assertNotIn("md:grid-cols-3", content)
        self.assertNotIn("xl:grid-cols-3", content)
        self.assertNotIn("lg:grid-cols-4", content)
        self.assertNotIn("md:stats-horizontal", content)
        self.assertIn("任务中心", content)
        self.assertIn("我的事务", content)
        self.assertNotIn("成员核心状态", content)
        self.assertNotIn("近期积分流水", content)

    def test_workspace_page_renders_welcome_header_without_primary_hero(self) -> None:
        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("你好，", content)
        self.assertIn("欢迎回到工作台", content)
        self.assertIn('data-workspace-section="welcome"', content)
        # 旧黄色英雄卡的整块主色背景与重阴影不再出现在顶部欢迎区
        self.assertNotIn("bg-primary text-primary-content", content)

    def test_workspace_page_renders_member_status_without_financial_summary(self) -> None:
        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('aria-labelledby="workspace-status-summary-title"', content)
        self.assertIn("状态摘要", content)
        # 状态摘要只保留成员状态与身份辅助，不展示财务指标。
        self.assertIn(self.member.get_status_display(), content)
        self.assertNotIn("当前积分", content)
        self.assertNotIn("积分下限 -300", content)
        # 身份元数据与 world / 模拟日继续可见
        self.assertIn('data-workspace-section="identity-meta"', content)
        self.assertIn("mem-0001", content)
        self.assertIn("模拟第 7 天", content)

    def test_workspace_page_removes_financial_metrics_and_ledger(self) -> None:
        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Workspace 首页不再承担成员财务摘要或积分流水展示。
        self.assertEqual(content.count("成员状态"), 1)
        self.assertNotIn("当前积分", content)
        self.assertNotIn("可用积分", content)
        self.assertNotIn("历史贡献", content)
        self.assertNotIn("近期积分流水", content)
        self.assertNotIn('aria-label="成员核心状态"', content)
        self.assertNotIn("credit_balance", response.context)
        self.assertNotIn("available_credit_balance", response.context)
        self.assertNotIn("lifetime_contribution", response.context)
        self.assertNotIn("recent_ledger_entries", response.context)

    def test_workspace_page_does_not_inject_design_sample_interactions(self) -> None:
        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # 不提前实现设计稿示例通知或底部导航；快捷操作只使用现有真实入口
        self.assertNotIn("通知", content)
        self.assertNotIn("bottom-nav", content)
        self.assertNotIn("Material Symbols", content)
        # 顶部改造后核心工作模块仍在，已确认删除的财务摘要不再出现。
        self.assertIn("我的事务", content)
        self.assertNotIn("近期积分流水", content)

    def test_workspace_matter_tabs_order_counts_and_aria(self) -> None:
        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        tablist = content.split('role="tablist"', 1)[1].split("</div>", 1)[0]
        # 三个标签按“需要我处理”“等待他人”“最近结束”顺序排列
        self.assertIn('id="matter-tab-action_required"', tablist)
        self.assertIn('id="matter-tab-waiting"', tablist)
        self.assertIn('id="matter-tab-recently_ended"', tablist)
        action_pos = tablist.find('id="matter-tab-action_required"')
        waiting_pos = tablist.find('id="matter-tab-waiting"')
        ended_pos = tablist.find('id="matter-tab-recently_ended"')
        self.assertLess(action_pos, waiting_pos)
        self.assertLess(waiting_pos, ended_pos)
        # 每个标签有稳定 ARIA 关联、选中状态与数量
        self.assertIn('aria-controls="matter-panel-action_required"', tablist)
        self.assertIn('aria-controls="matter-panel-waiting"', tablist)
        self.assertIn('aria-controls="matter-panel-recently_ended"', tablist)
        self.assertIn('aria-selected="true"', tablist)
        self.assertIn('data-workspace-tab="action_required"', tablist)
        self.assertIn('data-workspace-tab="waiting"', tablist)
        self.assertIn('data-workspace-tab="recently_ended"', tablist)
        # 数量反映投影列表长度（本 fixture：action 1 项任务，waiting 1 项反馈，recently 1 项任务）
        self.assertIn('data-workspace-count="1"', tablist)

    def test_workspace_matter_panels_render_without_hidden_and_facts_intact(self) -> None:
        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # 三个面板初始不带 hidden，无脚本时全部可读
        self.assertIn('id="matter-panel-action_required"', content)
        self.assertIn('id="matter-panel-waiting"', content)
        self.assertIn('id="matter-panel-recently_ended"', content)
        self.assertIn('role="tabpanel"', content)
        self.assertIn('aria-labelledby="matter-tab-action_required"', content)
        self.assertIn('aria-labelledby="matter-tab-waiting"', content)
        self.assertIn('aria-labelledby="matter-tab-recently_ended"', content)
        # 面板初始无 hidden 属性（渐进增强脚本负责初始化后隐藏）
        self.assertNotIn('id="matter-panel-action_required" hidden', content)
        self.assertNotIn('id="matter-panel-waiting" hidden', content)
        self.assertNotIn('id="matter-panel-recently_ended" hidden', content)
        # 事务事实完整保留：稳定 ID、类型、标题、责任、处理方、下一步、更新时间、目标 URL
        self.assertIn('data-matter-id="task:task-0001"', content)
        self.assertIn("准备今日午餐", content)
        self.assertIn('data-matter-id="event-feedback:feedback-0001"', content)
        self.assertIn("/workspace/tasks/task-0001/", content)
        self.assertIn("/event-feedbacks/feedback-0001/", content)
        self.assertIn("责任：", content)
        self.assertIn("当前处理：", content)
        self.assertIn("下一步：", content)
        self.assertIn("更新：", content)
        # 行动分组使用“进入处理”，等待与结束分组使用“查看详情”
        self.assertIn("进入处理", content)
        self.assertIn("查看详情", content)

    def _panel_body(self, content: str, group_id: str, next_group_id: str | None) -> str:
        start = content.find(f'id="matter-panel-{group_id}"')
        self.assertGreater(start, -1, f"missing panel {group_id}")
        if next_group_id is not None:
            end = content.find(f'id="matter-panel-{next_group_id}"')
        else:
            end = content.find("迁移期说明", start)
        self.assertGreater(end, -1)
        return content[start:end]

    def test_workspace_matter_panels_group_items_correctly(self) -> None:
        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        action = self._panel_body(content, "action_required", "waiting")
        waiting = self._panel_body(content, "waiting", "recently_ended")
        ended = self._panel_body(content, "recently_ended", None)

        # task-0001（CLAIMED）在“需要我处理”
        self.assertIn('data-matter-id="task:task-0001"', action)
        # feedback-0001（VERIFYING，提交人视角）在“等待他人”
        self.assertIn('data-matter-id="event-feedback:feedback-0001"', waiting)
        # task-0003（ACCEPTED）在“最近结束”
        self.assertIn('data-matter-id="task:task-0003"', ended)
        self.assertIn("清理公共厨房", ended)
        # 每个事项只属于一个面板
        self.assertNotIn('data-matter-id="task:task-0003"', action)
        self.assertNotIn('data-matter-id="task:task-0003"', waiting)
        self.assertNotIn('data-matter-id="task:task-0001"', ended)
        self.assertNotIn('data-matter-id="event-feedback:feedback-0001"', action)

    def test_workspace_matter_panel_omits_detail_button_without_target_url(self) -> None:
        with patch("workspace.work_item_context.build_member_matters") as build_matters:
            build_matters.return_value = {
                "action_required": [
                    {
                        "id": "task:task-no-url",
                        "type_label": "任务",
                        "is_overdue": False,
                        "status_label": "已领取",
                        "title": "无详情链接的任务",
                        "responsible": "mem-0001",
                        "current_handler": "mem-0001",
                        "action_label": "提交劳动",
                        "updated_at": timezone.now(),
                        "target_url": "",
                    }
                ],
                "waiting": [],
                "recently_ended": [],
                "total_active": 1,
            }
            response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        panel = self._panel_body(content, "action_required", "waiting")
        # 无 target_url 时不生成详情按钮
        self.assertNotIn("进入处理", panel)
        self.assertNotIn("查看详情", panel)
        self.assertNotIn("btn btn-sm btn-outline", panel)
        # 事务事实仍保留
        self.assertIn("无详情链接的任务", panel)

    def test_workspace_matter_tablist_initially_hidden(self) -> None:
        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # 标签控制条初始带 hidden（脚本成功后移除）；面板初始不带 hidden
        self.assertIn('data-workspace-tablist hidden', content)
        # 脚本在初始化成功后显式移除控制条的 hidden
        self.assertIn("tablist.hidden = false", content)
        self.assertNotIn('id="matter-panel-action_required" hidden', content)

    def test_workspace_matter_tabs_progressive_enhancement_script(self) -> None:
        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # 渐进增强脚本存在并实现方向键、Home、End、aria-selected、tabindex、hidden 同步
        self.assertIn('data-workspace-tablist', content)
        self.assertIn("ArrowRight", content)
        self.assertIn("ArrowLeft", content)
        self.assertIn('event.key === "Home"', content)
        self.assertIn('event.key === "End"', content)
        self.assertIn('setAttribute("aria-selected"', content)
        self.assertIn('setAttribute("tabindex"', content)
        self.assertIn("panel.hidden", content)
        # 不引入外部依赖
        self.assertNotIn("https://unpkg.com", content)
        self.assertNotIn("https://cdn.jsdelivr.net", content)

    def test_workspace_matter_empty_group_and_migration_note(self) -> None:
        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # 迁移期说明保留在事务区段内，语义不变
        self.assertIn("迁移期说明：未确认的原有 Workspace 模块继续保留", content)
        self.assertIn("已确认迁移的任务功能请进入任务中心", content)
        # 已确认删除的财务摘要模块不再受迁移期保留说明约束。
        self.assertNotIn("成员核心状态", content)
        self.assertNotIn("近期积分流水", content)

    @patch("workspace.work_item_context.build_member_matters")
    def test_workspace_matter_empty_group_renders_lightweight_empty_state(self, build_matters) -> None:
        build_matters.return_value = {
            "action_required": [],
            "waiting": [],
            "recently_ended": [],
            "total_active": 0,
        }
        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # 空分组使用轻量单行空状态，不再有大体积空卡片容器
        self.assertIn("当前没有需要你立即处理的事务。", content)
        self.assertIn("当前没有等待其他处理方的事务。", content)
        self.assertIn("近期没有已结束的相关事务。", content)
        self.assertIn('data-workspace-count="0"', content)
        self.assertNotIn("card-actions", content)

    def test_workspace_navigation_groups_personal_links_without_empty_duty_groups(self) -> None:
        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        navigation = content.split('data-workspace-section="quick-actions"', 1)[1].split("</nav>", 1)[0]
        self.assertIn("快捷操作", navigation)
        self.assertIn("个人功能", navigation)
        self.assertNotIn("治理职责", navigation)
        self.assertNotIn("运营管理", navigation)
        self.assertIn('href="/workspace/tasks/"', navigation)
        self.assertIn('href="/workspace/finance/claims/"', navigation)
        self.assertIn('href="/workspace/deliberator-exam/"', navigation)
        self.assertIn('href="/workspace/credits/transfer/"', navigation)
        self.assertIn('href="/workspace/credits/redemption/"', navigation)
        self.assertIn('href="/workspace/profile/"', navigation)
        self.assertIn('class="grid grid-cols-3 gap-3"', navigation)
        self.assertNotIn("btn btn-sm", navigation)
        self.assertNotIn("btn-accent", navigation)

        personal_labels = [
            "任务中心",
            "财务 / 报销",
            "申请执衡者",
            "积分转账",
            "兑换订单",
            "公开资料",
        ]
        positions = [navigation.find(label) for label in personal_labels]
        self.assertTrue(all(position >= 0 for position in positions))
        self.assertEqual(positions, sorted(positions))

    def test_workspace_quick_actions_use_local_decorative_icons(self) -> None:
        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        navigation = content.split('data-workspace-section="quick-actions"', 1)[1].split("</nav>", 1)[0]
        self.assertIn('data-lucide="clipboard-list" aria-hidden="true"', navigation)
        self.assertIn('data-lucide="receipt-text" aria-hidden="true"', navigation)
        self.assertIn('data-lucide="gavel" aria-hidden="true"', navigation)
        self.assertIn('src="/static/js/dist/lucide.min.js"', content)
        self.assertIn("window.lucide?.createIcons();", content)
        self.assertNotIn("https://unpkg.com", content)
        self.assertNotIn("https://cdn.jsdelivr.net", content)

    def test_workspace_navigation_sits_after_welcome_and_status_summary(self) -> None:
        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        welcome_pos = content.find('data-workspace-section="welcome"')
        summary_pos = content.find('aria-labelledby="workspace-status-summary-title"')
        nav_pos = content.find('data-workspace-section="quick-actions"')
        self.assertGreater(welcome_pos, -1)
        self.assertGreater(summary_pos, -1)
        self.assertGreater(nav_pos, -1)
        self.assertLess(welcome_pos, summary_pos)
        self.assertLess(summary_pos, nav_pos)
        # 对普通守约者可见的“个人功能”分组位于欢迎区与状态摘要之后
        personal_pos = content.find('id="workspace-nav-personal"')
        self.assertGreater(personal_pos, -1)
        self.assertGreater(personal_pos, nav_pos)

    @patch("workspace.context.member_can_administer", return_value=True)
    @patch("workspace.work_item_context.member_can_administer", return_value=True)
    def test_workspace_navigation_groups_governance_and_operations_links(
        self,
        _work_item_permission,
        _context_permission,
    ) -> None:
        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        navigation = content.split('data-workspace-section="quick-actions"', 1)[1].split("</nav>", 1)[0]
        self.assertIn("个人功能", navigation)
        self.assertIn("治理职责", navigation)
        self.assertIn("运营管理", navigation)
        self.assertIn('href="/workspace/applications/"', navigation)
        self.assertIn('href="/workspace/recruitment/"', navigation)
        self.assertIn('href="/workspace/finance/reviewer-appointments/"', navigation)
        self.assertIn('href="/workspace/proposals/"', navigation)
        self.assertIn('href="/workspace/tasks/new/"', navigation)
        self.assertIn('href="/workspace/tasks/review/"', navigation)
        self.assertIn('href="/workspace/credits/redemption/review/"', navigation)
        self.assertIn('href="/workspace/credits/budgets/"', navigation)
        self.assertIn('href="/workspace/credits/merchant-settlements/"', navigation)
        self.assertIn('href="/workspace/inventory/"', navigation)
        self.assertIn('href="/workspace/procurement/"', navigation)
        self.assertIn('data-lucide="user-check" aria-hidden="true"', navigation)
        self.assertIn('data-lucide="shopping-cart" aria-hidden="true"', navigation)
        self.assertNotIn("btn-accent", navigation)

    @patch("workspace.context.is_finance_reviewer", return_value=True)
    def test_workspace_quick_actions_for_finance_only_member(
        self,
        _finance_permission,
    ) -> None:
        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        navigation = content.split('data-workspace-section="quick-actions"', 1)[1].split("</nav>", 1)[0]
        self.assertIn("治理职责", navigation)
        self.assertIn('href="/workspace/proposals/"', navigation)
        self.assertNotIn('href="/workspace/applications/"', navigation)
        self.assertNotIn('href="/workspace/recruitment/"', navigation)
        self.assertNotIn('href="/workspace/finance/reviewer-appointments/"', navigation)
        self.assertIn("运营管理", navigation)
        self.assertIn('href="/workspace/procurement/"', navigation)
        self.assertNotIn('href="/workspace/tasks/new/"', navigation)
        self.assertNotIn('href="/workspace/tasks/review/"', navigation)
        self.assertNotIn('href="/workspace/credits/merchant-settlements/"', navigation)

    def test_workspace_quick_actions_for_merchant_operator_only(self) -> None:
        MerchantProfile.objects.create(
            merchant_id="merchant-workspace-only",
            display_name="仅结算商户",
            operator_member=self.member,
            merchant_type=MerchantProfile.Type.CASH_SETTLEMENT,
            settlement_rate=Decimal("0.5000"),
        )

        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        navigation = content.split('data-workspace-section="quick-actions"', 1)[1].split("</nav>", 1)[0]
        self.assertNotIn("治理职责", navigation)
        self.assertIn("运营管理", navigation)
        self.assertIn('href="/workspace/credits/merchant-settlements/"', navigation)
        self.assertNotIn('href="/workspace/tasks/new/"', navigation)
        self.assertNotIn('href="/workspace/tasks/review/"', navigation)
        self.assertNotIn('href="/workspace/credits/budgets/"', navigation)
        self.assertNotIn('href="/workspace/inventory/"', navigation)
        self.assertNotIn('href="/workspace/procurement/"', navigation)

    @patch("workspace.context.AuthorizationService.member_has_permission")
    def test_workspace_quick_actions_for_exam_manager_only(
        self,
        member_has_permission,
    ) -> None:
        member_has_permission.side_effect = (
            lambda _member, permission_code, **_kwargs:
            permission_code == DELIBERATOR_EXAM_MANAGE_PERMISSION
        )

        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        navigation = content.split('data-workspace-section="quick-actions"', 1)[1].split("</nav>", 1)[0]
        self.assertIn("考试维护", navigation)
        self.assertIn('href="/workspace/deliberator-exam/configuration/"', navigation)
        self.assertNotIn("治理职责", navigation)
        self.assertNotIn("运营管理", navigation)
        self.assertNotIn('href="/workspace/proposals/"', navigation)
        self.assertNotIn('href="/workspace/procurement/"', navigation)

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

    def test_workspace_home_uses_compact_header_with_brand_and_native_menu(self) -> None:
        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # 专用紧凑页头存在，且不在横向铺开全部导航
        self.assertIn('data-workspace-compact-header', content)
        self.assertIn('data-workspace-nav-menu', content)
        # 品牌文字与首页目标来自 runtime_nav 上下文
        self.assertIn("大苹果社区", content)
        self.assertNotIn("大苹果社区动态", content)
        self.assertIn('href="/"', content)
        # 原生折叠结构，默认收起（无 open 属性）
        self.assertIn("<details", content)
        self.assertIn("<summary", content)
        self.assertNotIn("<details open", content)
        # 菜单触发器有可访问名称与文字 fallback
        self.assertIn('aria-label="页面导航"', content)
        self.assertIn("菜单", content)
        # 不显示共享页头的横向 navbar 结构
        self.assertNotIn('navbar bg-base-100 shadow-sm', content)

    def test_workspace_home_menu_preserves_runtime_nav_order_and_methods(self) -> None:
        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        menu = content.split('aria-label="页面导航菜单"', 1)[1].split("</nav>", 1)[0]
        labels = ["首页", "事件流", "财务", "资源库存", "我的主页", "工作台", "退出"]
        positions = [menu.find(label) for label in labels]
        self.assertTrue(all(pos >= 0 for pos in positions), f"missing nav items: {labels}")
        self.assertEqual(positions, sorted(positions))
        # 各入口指向现有 URL 与方法
        self.assertIn('href="/"', menu)
        self.assertIn('href="/events/"', menu)
        self.assertIn('href="/finance/"', menu)
        self.assertIn('href="/resources/"', menu)
        self.assertIn('href="/u/mem-0001/"', menu)
        self.assertIn('href="/workspace/"', menu)
        # 退出为带 CSRF 的 POST 表单，不是 GET 链接
        self.assertIn('method="post" action="/logout/"', menu)
        self.assertIn("csrfmiddlewaretoken", menu)
        self.assertNotIn('href="/logout/"', menu)

    def test_workspace_home_compact_header_adds_no_unwired_features(self) -> None:
        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # 不新增通知铃铛、未读数量、头像菜单或底部导航
        self.assertNotIn("通知", content)
        self.assertNotIn("未读", content)
        self.assertNotIn("bottom-nav", content)
        self.assertNotIn('aria-label="头像"', content)
        # 欢迎区、成员状态摘要、快捷操作和我的事务继续保留。
        self.assertIn('data-workspace-section="welcome"', content)
        self.assertIn('aria-labelledby="workspace-status-summary-title"', content)
        self.assertIn('data-workspace-section="quick-actions"', content)
        self.assertIn('data-workspace-section="matters"', content)
        self.assertNotIn("成员核心状态", content)
        self.assertNotIn("近期积分流水", content)

    def test_workspace_subpages_still_use_shared_runtime_header(self) -> None:
        response = self.client.get("/workspace/tasks/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # 任务中心等子页面继续使用共享页头，不出现专用紧凑页头
        self.assertIn('navbar bg-base-100 shadow-sm', content)
        self.assertNotIn('data-workspace-compact-header', content)
        self.assertNotIn('data-workspace-nav-menu', content)

    def test_applicant_workspace_still_uses_shared_runtime_header(self) -> None:
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
        self.assertTemplateUsed(response, "workspace/applicant.html")
        content = response.content.decode()
        # 报名工作台继续使用共享页头，不出现专用紧凑页头
        self.assertIn('navbar bg-base-100 shadow-sm', content)
        self.assertNotIn('data-workspace-compact-header', content)
        self.assertNotIn('data-workspace-nav-menu', content)

    def test_other_runtime_pages_still_use_shared_runtime_header(self) -> None:
        response = self.client.get("/finance/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # 公开运行时页面（财务）继续使用共享页头，不出现专用紧凑页头
        self.assertIn('navbar bg-base-100 shadow-sm', content)
        self.assertNotIn('data-workspace-compact-header', content)
        self.assertNotIn('data-workspace-nav-menu', content)

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
        self.assertContains(response, "由统一提案流程完成表决、判定与执行")
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
