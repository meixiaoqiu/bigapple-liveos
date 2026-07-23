from __future__ import annotations
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase

from observer.dashboard_theme import build_dashboard_theme_context
from observer.theme import (
    THEME_SESSION_KEY,
    get_active_theme_name,
    get_theme_asset_url,
    get_theme_component_path,
    get_theme_config,
    get_theme_partial_path,
)
def request_with_session(path: str = "/"):
    request = RequestFactory().get(path)
    middleware = SessionMiddleware(lambda req: None)
    middleware.process_request(request)
    request.session.save()
    return request


class ThemeSystemTests(TestCase):
    """覆盖主题 fallback、asset 和 dashboard 展示契约。"""

    def test_unknown_theme_falls_back_to_default_game(self) -> None:
        self.assertEqual(get_theme_config("missing-theme")["key"], "default_game")

    def test_theme_asset_uses_staticfiles_fallback_safely(self) -> None:
        request = request_with_session()
        request.session[THEME_SESSION_KEY] = "dark"

        self.assertEqual(get_theme_asset_url(request, "css/tokens.css"), "")
        self.assertEqual(get_theme_asset_url(request, "img/mascot/missing.webp"), "")
        self.assertEqual(get_theme_asset_url(request, "../unsafe.css"), "")

    def test_theme_partial_and_component_fall_back_to_default_game(self) -> None:
        request = request_with_session()
        request.session[THEME_SESSION_KEY] = "dark"

        self.assertEqual(
            get_theme_partial_path(request, "risk_panel.html"),
            "themes/default_game/partials/risk_panel.html",
        )
        self.assertEqual(
            get_theme_component_path(request, "mission_card.html"),
            "themes/default_game/components/empty_state.html",
        )

    def test_dashboard_theme_context_is_complete_without_raw_data(self) -> None:
        request = request_with_session()
        context = build_dashboard_theme_context(request)

        self.assertEqual(context["hero"]["title"], "大苹果社区动态")
        self.assertEqual(context["stats"], [])
        self.assertTrue(context["mainline"]["empty"])
        self.assertEqual(context["events"], [])
        self.assertIn("risk_summary", context)
        self.assertIn("capacity", context)
        self.assertIn("user_progress", context)
        self.assertTrue(context["navigation"])

    def test_dashboard_theme_context_includes_default_extension_fields(self) -> None:
        request = request_with_session()
        context = build_dashboard_theme_context(request)

        self.assertEqual(context["photos"], [])
        self.assertEqual(context["pending_disputes"], [])
        self.assertIn("remaining", context["capacity"])

    def test_unknown_theme_query_parameter_falls_back_without_session_mutation(self) -> None:
        request = request_with_session("/?theme=missing-theme")
        from observer.theme_views import apply_theme_query_override

        apply_theme_query_override(request)

        self.assertEqual(get_active_theme_name(request), "default_game")
        self.assertNotIn(THEME_SESSION_KEY, request.session)


class MainlineContextTests(TestCase):
    """单元测试 build_mainline_context 的筛选逻辑。"""

    def _make_node(self, node_id="n1", code="A", title="节点", node_type="task",
                   status="in_progress", parent=None, is_required=True, **kw):
        from unittest.mock import MagicMock
        node = MagicMock()
        node.node_id = node_id
        node.code = code
        node.title = title
        node.node_type = node_type
        node.status = status
        node.parent = parent
        node.is_required = is_required
        node.description = kw.get("description", "")
        node.planned_duration_days = kw.get("planned_duration_days", 0)
        node.required_people_min = kw.get("required_people_min", 0)
        node.required_people_max = kw.get("required_people_max", 0)
        node.risk_notes = kw.get("risk_notes", "")
        node.completion_criteria = kw.get("completion_criteria", [])
        return node

    def _make_plan(self, plan_id="p1", name="测试计划"):
        from unittest.mock import MagicMock
        plan = MagicMock()
        plan.name = name
        return plan

    def _make_revision(self, title="v0.1", revision_code="v0.1"):
        from unittest.mock import MagicMock
        rev = MagicMock()
        rev.title = title
        rev.revision_code = revision_code
        return rev

    def _raw_data(self, current_nodes=None, next_nodes=None, plan_nodes=None, active_plan=None, active_revision=None):
        if active_plan is None:
            active_plan = self._make_plan()
        if active_revision is None:
            active_revision = self._make_revision()
        return {
            "active_plan": active_plan,
            "active_revision": active_revision,
            "current_plan_nodes": current_nodes or [],
            "next_plan_nodes": next_nodes or [],
            "plan_nodes": plan_nodes or current_nodes or [],
            "plan_required_total": 0,
            "plan_required_completed": 0,
            "latest_simulation_run": None,
            "latest_run_failures": [],
            "latest_run_proposals": [],
            "latest_run_change_sets": [],
            "latest_run_turn": None,
        }

    def test_milestone_stage_current_nodes_excludes_stage_itself(self):
        from observer.mainline_context import build_mainline_context

        milestone = self._make_node("n0", "M1", "阶段一", "milestone", "in_progress")
        child = self._make_node("n1", "T1", "任务A", "task", "in_progress", parent=milestone)
        raw = self._raw_data(current_nodes=[milestone, child])
        ctx = build_mainline_context(raw)

        self.assertIsNotNone(ctx["stage"])
        self.assertEqual(ctx["stage"]["code"], "M1")
        # stage milestone should not appear in current_nodes
        node_ids = {n["node_id"] for n in ctx["current_nodes"]}
        self.assertNotIn("n0", node_ids)
        self.assertIn("n1", node_ids)

    def test_only_milestone_fallback_to_current_nodes(self):
        from observer.mainline_context import build_mainline_context

        milestone = self._make_node("n0", "M1", "阶段一", "milestone", "in_progress")
        raw = self._raw_data(current_nodes=[milestone])
        ctx = build_mainline_context(raw)

        self.assertIsNotNone(ctx["stage"])
        self.assertEqual(ctx["stage"]["code"], "M1")
        # when only stage exists, it should fall back into current_nodes
        self.assertTrue(len(ctx["current_nodes"]) >= 1)
        self.assertIn("n0", {n["node_id"] for n in ctx["current_nodes"]})

    def test_stage_a_child_priority_over_stage_b_child(self):
        from observer.mainline_context import build_mainline_context

        stage_a = self._make_node("st-a", "SA", "阶段A", "milestone", "in_progress")
        child_a = self._make_node("ca1", "T1", "阶段A子任务", "task", "in_progress", parent=stage_a)
        stage_b = self._make_node("st-b", "SB", "阶段B", "milestone", "in_progress")
        child_b = self._make_node("cb1", "T2", "阶段B子任务", "task", "in_progress", parent=stage_b)
        raw = self._raw_data(current_nodes=[stage_a, child_a, stage_b, child_b])
        ctx = build_mainline_context(raw)

        self.assertIsNotNone(ctx["stage"])
        self.assertEqual(ctx["stage"]["code"], "SA")  # first stage wins
        node_ids = {n["node_id"] for n in ctx["current_nodes"]}
        # stage_children (ca1) appears; non-stage nodes of other stage
        # are not promoted when current stage has children
        self.assertIn("ca1", node_ids)
        self.assertNotIn("st-a", node_ids)
        self.assertNotIn("st-b", node_ids)
        self.assertNotIn("cb1", node_ids)

    def test_stage_a_children_empty_fallback_to_other_stage_children(self):
        from observer.mainline_context import build_mainline_context

        stage_a = self._make_node("st-a", "SA", "阶段A", "milestone", "in_progress")
        stage_b = self._make_node("st-b", "SB", "阶段B", "milestone", "in_progress")
        child_b = self._make_node("cb1", "T2", "阶段B子任务", "task", "in_progress", parent=stage_b)
        raw = self._raw_data(current_nodes=[stage_a, stage_b, child_b])
        ctx = build_mainline_context(raw)

        self.assertIsNotNone(ctx["stage"])
        self.assertEqual(ctx["stage"]["code"], "SA")
        node_ids = {n["node_id"] for n in ctx["current_nodes"]}
        # stage_a has no non-stage children → fallback to other_non_stage (cb1)
        self.assertIn("cb1", node_ids)
        self.assertNotIn("st-a", node_ids)
        self.assertNotIn("st-b", node_ids)

    def test_stage_without_children_fallback_to_other_nodes(self):
        from observer.mainline_context import build_mainline_context

        stage_a = self._make_node("st-a", "SA", "阶段A", "milestone", "in_progress")
        orphan = self._make_node("n1", "T1", "无父节点任务", "task", "in_progress")
        raw = self._raw_data(current_nodes=[stage_a, orphan])
        ctx = build_mainline_context(raw)

        self.assertIsNotNone(ctx["stage"])
        self.assertEqual(ctx["stage"]["code"], "SA")
        node_ids = {n["node_id"] for n in ctx["current_nodes"]}
        # orphan belongs to no stage → other_non_stage → appears in current_nodes
        self.assertIn("n1", node_ids)
        self.assertNotIn("st-a", node_ids)

    def test_primary_task_and_next_action_in_mainline_context(self):
        from observer.mainline_context import build_mainline_context

        stage = self._make_node("st", "Z0", "启动", "milestone", "in_progress")
        child = self._make_node("c1", "T1", "子任务", "task", "in_progress", parent=stage)
        next_node = self._make_node("n1", "N1", "下一步", "task", "planned", parent=stage)
        raw = self._raw_data(
            current_nodes=[stage, child],
            next_nodes=[next_node],
        )
        ctx = build_mainline_context(raw)
        self.assertIsNotNone(ctx["primary_task"])
        self.assertEqual(ctx["primary_task"]["node_id"], "c1")
        self.assertIsNotNone(ctx["next_action"])
        self.assertEqual(ctx["next_action"]["node_id"], "n1")

    def test_all_nodes_and_stages_in_mainline_context(self):
        from observer.mainline_context import build_mainline_context

        stage = self._make_node("st", "Z0", "启动", "milestone", "in_progress")
        child = self._make_node("c1", "T1", "子任务", "task", "in_progress", parent=stage,
                                completion_criteria=["完成点A", "完成点B"])
        raw = self._raw_data(
            current_nodes=[stage, child],
            plan_nodes=[stage, child],
        )
        ctx = build_mainline_context(raw)
        self.assertTrue(len(ctx["all_nodes"]) >= 2)
        self.assertTrue(len(ctx["stages"]) >= 1)
        stage_list = ctx["stages"]
        z0_stage = next(s for s in stage_list if s["code"] == "Z0")
        self.assertTrue(z0_stage["is_current"])
        self.assertEqual(len(z0_stage["children"]), 1)
        child_node = z0_stage["children"][0]
        self.assertEqual(len(child_node["completion_criteria"]), 2)

    def test_stage_node_not_repeated_in_map_point_source(self):
        from observer.mainline_context import build_mainline_context

        milestone = self._make_node("n0", "M1", "阶段一", "milestone", "in_progress")
        child = self._make_node("n1", "T1", "任务", "task", "in_progress", parent=milestone)
        raw = self._raw_data(current_nodes=[milestone, child])
        ctx = build_mainline_context(raw)

        # current_nodes should contain child but not the stage
        node_ids = {n["node_id"] for n in ctx["current_nodes"]}
        self.assertIn("n1", node_ids)
        self.assertNotIn("n0", node_ids)

    def test_stage_work_package_task_deep_hierarchy_in_stages(self):
        from observer.mainline_context import build_mainline_context

        stage = self._make_node("st", "Z0", "启动", "milestone", "in_progress")
        work_package = self._make_node("wp", "WP1", "工作包", "task", "in_progress", parent=stage)
        task = self._make_node("tk", "T1", "具体任务", "task", "in_progress", parent=work_package)
        raw = self._raw_data(
            current_nodes=[stage, work_package, task],
            plan_nodes=[stage, work_package, task],
        )
        ctx = build_mainline_context(raw)
        self.assertEqual(len(ctx["stages"]), 1)
        z0 = ctx["stages"][0]
        self.assertEqual(z0["code"], "Z0")
        child_ids = {c["node_id"] for c in z0["children"]}
        self.assertIn("wp", child_ids)
        self.assertIn("tk", child_ids)  # deep node not lost
        tk = next(c for c in z0["children"] if c["node_id"] == "tk")
        wp = next(c for c in z0["children"] if c["node_id"] == "wp")
        self.assertEqual(wp["depth"], 1)   # direct child of stage
        self.assertEqual(tk["depth"], 2)   # grandchild of stage

    def test_orphan_with_stages_still_shows_ungrouped(self):
        from observer.mainline_context import build_mainline_context

        stage = self._make_node("st", "Z0", "启动", "milestone", "in_progress")
        orphan = self._make_node("o1", "OW", "游离节点", "task", "in_progress", parent=None)
        raw = self._raw_data(
            current_nodes=[stage, orphan],
            plan_nodes=[stage, orphan],
        )
        ctx = build_mainline_context(raw)
        stage_ids = {s["node_id"] for s in ctx["stages"]}
        self.assertIn("st", stage_ids)
        ungrouped = next((s for s in ctx["stages"] if s["code"] == "未分组"), None)
        self.assertIsNotNone(ungrouped)
        self.assertIn("o1", {c["node_id"] for c in ungrouped["children"]})

    def test_deep_current_node_detects_nearest_stage_ancestor(self):
        from observer.mainline_context import build_mainline_context

        stage = self._make_node("st", "Z0", "启动", "milestone", "in_progress")
        work_package = self._make_node("wp", "WP1", "工作包", "task", "in_progress", parent=stage)
        task = self._make_node("tk", "T1", "具体任务", "task", "in_progress", parent=work_package)
        raw = self._raw_data(
            current_nodes=[task],  # only the deep IN_PROGRESS node
            plan_nodes=[stage, work_package, task],
        )
        ctx = build_mainline_context(raw)

        self.assertIsNotNone(ctx["stage"])
        self.assertEqual(ctx["stage"]["code"], stage.code)  # nearest STAGE ancestor, not work_package
        self.assertIsNotNone(ctx["primary_task"])
        self.assertEqual(ctx["primary_task"]["code"], task.code)  # task is the primary task

    def test_deep_current_node_belongs_to_stage_children(self):
        from observer.mainline_context import build_mainline_context

        stage = self._make_node("st", "Z0", "启动", "milestone", "in_progress")
        work_package = self._make_node("wp", "WP1", "工作包", "task", "in_progress", parent=stage)
        task = self._make_node("tk", "T1", "具体任务", "task", "in_progress", parent=work_package)
        raw = self._raw_data(
            current_nodes=[task],
            plan_nodes=[stage, work_package, task],
        )
        ctx = build_mainline_context(raw)

        # task is the IN_PROGRESS node, belongs to stage (grandparent)
        node_ids = {n["node_id"] for n in ctx["current_nodes"]}
        self.assertIn("tk", node_ids)
        self.assertNotIn("st", node_ids)  # stage itself excluded from current_nodes

        # stages renders deep hierarchy correctly
        self.assertEqual(len(ctx["stages"]), 1)
        z0 = ctx["stages"][0]
        child_ids = {c["node_id"] for c in z0["children"]}
        self.assertIn("wp", child_ids)
        self.assertIn("tk", child_ids)
        wp = next(c for c in z0["children"] if c["node_id"] == "wp")
        tk = next(c for c in z0["children"] if c["node_id"] == "tk")
        self.assertEqual(wp["depth"], 1)
        self.assertEqual(tk["depth"], 2)

    def _create_plan_with_n_nodes(self, node_count: int = 65) -> list:
        """Helper: create a ProjectPlan + published PlanRevision + N PlanNodes."""
        from core.models import PlanNode, PlanRevision, ProjectPlan
        from django.utils import timezone

        now = timezone.now()
        plan = ProjectPlan.objects.create(
            plan_id="plan-full-node-test",
            name="全量节点测试计划",
            status=ProjectPlan.Status.ACTIVE,
            created_at=now,
        )
        revision = PlanRevision.objects.create(
            revision_id="rev-full-node-test",
            plan=plan,
            revision_code="v1",
            title="全量节点测试修订",
            status=PlanRevision.Status.PUBLISHED,
            created_at=now,
        )
        nodes = []
        for i in range(1, node_count + 1):
            nodes.append(PlanNode.objects.create(
                node_id=f"node-full-{i:03d}",
                revision=revision,
                sequence=i,
                code=f"N{i:03d}",
                title=f"测试节点 {i}",
                node_type=PlanNode.NodeType.RECRUITMENT,
                status=PlanNode.Status.PLANNED,
                created_at=now,
                metadata={},
            ))
        return nodes

    def test_observer_context_default_truncates_at_60(self):
        from observer.page_context import observer_context

        self._create_plan_with_n_nodes(65)
        ctx = observer_context()
        self.assertEqual(len(ctx["plan_nodes"]), 60)
        self.assertFalse(any(str(getattr(n, "node_id", "")) == "node-full-065" for n in ctx["plan_nodes"]))

    def test_observer_context_full_plan_nodes_no_truncation(self):
        from observer.page_context import observer_context

        self._create_plan_with_n_nodes(65)
        ctx = observer_context(full_plan_nodes=True)
        self.assertGreaterEqual(len(ctx["plan_nodes"]), 65)
        self.assertTrue(any(str(getattr(n, "node_id", "")) == "node-full-065" for n in ctx["plan_nodes"]))

