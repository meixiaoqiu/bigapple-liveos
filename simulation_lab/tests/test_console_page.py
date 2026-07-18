from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone

from core.member_roles import ROLE_CONTRIBUTOR
from core.models import (
    Event,
    LedgerEntry,
    Member,
    PlanChangeOperation,
    PlanChangeSet,
    PlanNode,
    PlanRevision,
    PlanRevisionProposal,
    ProjectPlan,
    Resource,
    SimulationFailure,
    SimulationRun,
    SimulationRunDisposition,
    SimulationSnapshot,
    SimulationSnapshotItem,
    SimulationTurn,
    Task,
)
from core.tests.helpers import create_governance_admin_member, create_member, login_as_member
from core.exceptions import DomainError
from simulation.boundary import run_simulation_turn
from worlds.models import WorldRegistry


class ObserverSimulationConsoleTests(TestCase):
    """覆盖 Observer 只观察、Lab 才控制仿真的边界。"""

    def setUp(self) -> None:
        self.member = create_member(
            member_no="mem-0001",
            role_name=ROLE_CONTRIBUTOR,
            status=Member.Status.ADMITTED,
            batch_id="batch-opening",
            joined_simulation_day=1,
            credit_floor=-100,
            profile={"display_name": "成员一号"},
            created_at=timezone.now(),
        )
        self.reviewer = create_governance_admin_member(
            member_no="member-admin-0001",
            status=Member.Status.ACTIVE,
            batch_id="batch-opening",
            joined_simulation_day=1,
            credit_floor=-500,
            profile={"display_name": "开荒队治理成员"},
            created_at=timezone.now(),
        )
        self.task = Task.objects.create(
            task_id="task-open-0001",
            title="准备晚餐",
            task_type=Task.TaskType.COOKING,
            status=Task.Status.OPEN,
            standard_hours=2,
            base_points=20,
            role_coefficient=Decimal("1.000"),
            can_be_delayed=True,
            requires_review=True,
            failure_consequence=Task.FailureConsequence.MEDIUM,
            rule_version="ruleset-v0.1.0",
            created_at=timezone.now(),
            metadata={"simulation_day": 1},
        )
        self.resource = Resource.objects.create(
            resource_id="res-grain",
            resource_type=Resource.ResourceType.GRAIN,
            unit=Resource.Unit.KG,
            current_stock=Decimal("100.000"),
            daily_consumption_estimate=Decimal("10.000"),
            replenishment_method=Resource.ReplenishmentMethod.PURCHASE,
            loss_rate=Decimal("0.01000"),
            warning_threshold=Decimal("20.000"),
            shortage_impact={"satisfaction_delta": -12},
            updated_at=timezone.now(),
            rule_version="ruleset-v0.1.0",
            metadata={},
        )

    def login_as_superuser(self):
        user = get_user_model().objects.create_user(username="simulation-root", password="test-password")
        user.is_staff = True
        user.is_superuser = True
        user.save(update_fields=["is_staff", "is_superuser"])
        self.client.force_login(user)
        return user

    def create_snapshot(self, *, raw_archive_path: str = "var/missing-simulation-archive/snapshot-test-0001") -> SimulationSnapshot:
        snapshot = SimulationSnapshot.objects.create(
            snapshot_id="snapshot-test-0001",
            title="simulation0001 / sim-run-test / 责任闭环缺失",
            source_world_id="simulation0001",
            source_world_type="simulation",
            source_database_alias="default",
            source_database_name="test_control",
            source_run_id="sim-run-test",
            plan_revision_id="rev-test",
            run_status="failed",
            failure_type="responsibility_closure_missing",
            failure_title="责任闭环缺失",
            snapshot_schema_version=1,
            status=SimulationSnapshot.Status.ARCHIVED,
            raw_archive_path=raw_archive_path,
            raw_archive_hash="0" * 64,
            report_path="",
            raw_table_counts={"core.SimulationRun": 1},
            normalized_summary={
                "counts": {
                    "turns": 0,
                    "events": 0,
                    "node_states": 1,
                    "failures": 1,
                    "proposals": 0,
                    "change_sets": 0,
                    "change_operations": 0,
                },
                "failures": [
                    {
                        "failure_type": "responsibility_closure_missing",
                        "title": "责任闭环缺失",
                        "description": "缺少结构、光伏、电气、施工与验收责任文件。",
                    }
                ],
            },
            code_version="test",
            archived_at=timezone.now(),
            metadata={},
        )
        SimulationSnapshotItem.objects.create(
            item_id="snapshot-test-0001-item-000001",
            snapshot=snapshot,
            item_type=SimulationSnapshotItem.ItemType.RUN,
            source_model="core.SimulationRun",
            source_pk="sim-run-test",
            title="仿真运行 sim-run-test",
            summary="仿真失败。",
            sort_order=1,
            payload_json={"model": "core.simulationrun", "pk": "sim-run-test"},
        )
        SimulationSnapshotItem.objects.create(
            item_id="snapshot-test-0001-item-000101",
            snapshot=snapshot,
            item_type=SimulationSnapshotItem.ItemType.NODE_STATE,
            source_model="core.PlanNodeRunState",
            source_pk="state-c3",
            title="node-bigapple001-c3",
            summary="失败",
            sort_order=101,
            payload_json={"fields": {"plan_node": "node-bigapple001-c3"}},
        )
        SimulationSnapshotItem.objects.create(
            item_id="snapshot-test-0001-item-002001",
            snapshot=snapshot,
            item_type=SimulationSnapshotItem.ItemType.FAILURE,
            source_model="core.SimulationFailure",
            source_pk="failure-test",
            title="责任闭环缺失",
            summary="缺少结构、光伏、电气、施工与验收责任文件。",
            sort_order=2001,
            payload_json={"model": "core.simulationfailure", "pk": "failure-test"},
        )
        return snapshot

    def create_raw_plan_node_archive(self, archive_path: str) -> None:
        raw_dir = Path(archive_path) / "raw"
        raw_dir.mkdir(parents=True)
        (raw_dir / "core.PlanNode.json").write_text(
            json.dumps(
                [
                    {
                        "model": "core.plannode",
                        "pk": "node-bigapple001-c3",
                        "fields": {"code": "C3", "title": "光伏一期 0.5MW"},
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def create_simulation_world(self, *, database_alias: str = "default", database_name: str = "test_control") -> WorldRegistry:
        world, _ = WorldRegistry.objects.update_or_create(
            world_id="simulation0001",
            defaults={
                "name": "Simulation 0001",
                "world_type": WorldRegistry.WorldType.SIMULATION,
                "database_alias": database_alias,
                "database_name": database_name,
                "status": WorldRegistry.Status.ACTIVE,
            },
        )
        return world

    def create_finished_run(self, run_id: str = "sim-run-lab-test", *, using: str = "default") -> SimulationRun:
        plan = ProjectPlan.objects.using(using).create(
            plan_id=f"plan-{run_id}",
            name="测试计划",
            status=ProjectPlan.Status.ACTIVE,
            description="测试计划",
            target_location="测试据点",
            created_at=timezone.now(),
        )
        revision = PlanRevision.objects.using(using).create(
            revision_id=f"rev-{run_id}",
            plan=plan,
            revision_code="v0.1.0",
            status=PlanRevision.Status.PUBLISHED,
            title="测试版本",
            change_summary="测试计划版本",
            created_at=timezone.now(),
            published_at=timezone.now(),
        )
        return SimulationRun.objects.using(using).create(
            run_id=run_id,
            plan_revision=revision,
            status=SimulationRun.Status.FAILED,
            current_day=1,
            max_turns=1,
            started_at=timezone.now(),
            ended_at=timezone.now(),
            failure_summary="测试失败摘要",
            metadata={"scenario": "zero_start"},
        )

    def test_observer_page_renders_simulation_console(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "大苹果社区动态")
        self.assertContains(response, "事件时间线")
        self.assertContains(response, "数据日志")
        self.assertContains(response, "任务与提案线索")
        self.assertNotContains(response, "仿真控制台")
        self.assertNotContains(response, "推进一回合")
        self.assertNotContains(response, "自动跑到失败")
        self.assertNotContains(response, 'href="/simulation/"')

    def test_simulation_console_has_no_standalone_page(self) -> None:
        response = self.client.get("/simulation/")

        self.assertEqual(response.status_code, 404)

    def test_root_lab_route_is_not_exposed(self) -> None:
        self.login_as_superuser()

        response = self.client.get("/lab/")

        self.assertEqual(response.status_code, 404)

    def test_admin_simulation_lab_requires_superuser(self) -> None:
        login_as_member(self.client, self.reviewer, is_staff=True)

        response = self.client.get("/admin/simulation-lab/")

        self.assertEqual(response.status_code, 403)

    def test_admin_simulation_lab_uses_admin_login(self) -> None:
        response = self.client.get("/admin/simulation-lab/")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/admin/login/"))
        self.assertFalse(response["Location"].startswith("/login/"))

    def test_admin_simulation_lab_page_allows_superuser(self) -> None:
        self.login_as_superuser()
        self.create_simulation_world()

        response = self.client.get("/admin/simulation-lab/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "仿真实验后台")
        self.assertContains(response, "大苹果 Live OS 管理后台")
        self.assertNotContains(response, "选择世界后")
        self.assertContains(response, "simulation0001")
        self.assertContains(response, "启动零起点仿真")
        self.assertContains(response, "确认启动新的零起点仿真吗？")
        self.assertContains(response, 'max="168"')
        self.assertContains(response, "网页单次最多推进 168 个虚拟小时")
        self.assertContains(response, "运行控制")
        self.assertContains(response, "仿真写库边界自检（待遗弃功能）")
        self.assertContains(response, "执行边界自检")
        self.assertNotContains(response, "待处置计划变更集")
        self.assertNotContains(response, "/workspace/")
        self.assertNotContains(response, "最近仿真快照")
        self.assertNotContains(response, "最近仿真运行")
        self.assertNotContains(response, "最近处置记录")

    def test_admin_simulation_lab_page_can_continue_active_zero_start_run(self) -> None:
        self.login_as_superuser()
        self.create_simulation_world()
        run = self.create_finished_run("sim-run-lab-active-zero-start")
        run.status = SimulationRun.Status.RUNNING
        run.ended_at = None
        run.metadata = {"scenario": "zero_start", "current_hour": 167, "can_continue": True}
        run.save(update_fields=["status", "ended_at", "metadata"])

        response = self.client.get("/admin/simulation-lab/?world_id=simulation0001")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "当前运行")
        self.assertContains(response, run.run_id)
        self.assertContains(response, "继续当前仿真")
        self.assertContains(response, "中止当前仿真")
        self.assertNotContains(response, 'value="继续当前仿真" disabled')
        self.assertContains(response, "确认继续推进当前零起点仿真 sim-run-lab-active-zero-start 吗？")
        self.assertNotContains(response, "确认启动新的零起点仿真吗？")

    def test_admin_simulation_lab_page_can_continue_legacy_startup_gate_failed_run(self) -> None:
        self.login_as_superuser()
        self.create_simulation_world()
        run = self.create_finished_run("sim-run-lab-legacy-zero-start")
        run.failure_summary = "Z0 自媒体报名筛选后仍未达到启动门槛"
        run.metadata = {"scenario": "zero_start", "startup_gate_satisfied": False, "current_hour": 167}
        run.save(update_fields=["failure_summary", "metadata"])

        response = self.client.get("/admin/simulation-lab/?world_id=simulation0001")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "当前运行")
        self.assertContains(response, run.run_id)
        self.assertContains(response, "继续当前仿真")
        self.assertContains(response, "中止当前仿真")
        self.assertNotContains(response, 'value="继续当前仿真" disabled')
        self.assertContains(response, "确认继续推进当前零起点仿真 sim-run-lab-legacy-zero-start 吗？")
        self.assertNotContains(response, "存在已结束但未处置的仿真运行")

    def test_admin_simulation_lab_rejects_large_sync_hours_before_running(self) -> None:
        self.login_as_superuser()
        self.create_simulation_world()

        with (
            patch("simulation_lab.views.call_command") as seed_command,
            patch("simulation_lab.views.run_zero_start_recruitment_simulation") as runner,
        ):
            response = self.client.post(
                "/admin/simulation-lab/run-until-failure/",
                {"world_id": "simulation0001", "hours": "1680"},
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        seed_command.assert_not_called()
        runner.assert_not_called()
        self.assertFalse(SimulationRun.objects.exists())
        self.assertContains(response, "单次最多推进 168 个虚拟小时")

    def test_admin_simulation_lab_page_keeps_plan_change_sets_inside_run_detail(self) -> None:
        self.login_as_superuser()
        self.create_simulation_world()
        run = self.create_finished_run("sim-run-lab-pending-change")
        proposal = PlanRevisionProposal.objects.create(
            proposal_id="proposal-lab-pending-change",
            run=run,
            plan_revision=run.plan_revision,
            proposal_type=PlanRevisionProposal.ProposalType.ADD_NODE,
            status=PlanRevisionProposal.Status.DRAFT,
            title="增加网络报名与责任能力筛选前置阶段",
            rationale="报名数量和兴趣不能代表可执行团队形成。",
            suggested_changes={"add_stage": "Z0 网络招募、报名筛选与责任能力识别"},
            created_at=timezone.now(),
            metadata={"scenario": "zero_start"},
        )
        change_set = PlanChangeSet.objects.create(
            change_set_id="changeset-lab-pending-change",
            run=run,
            proposal=proposal,
            plan_revision=run.plan_revision,
            status=PlanChangeSet.Status.DRAFT,
            title="零起点招募筛选结构化变更",
            summary="新增 Z0 前置阶段。",
            created_at=timezone.now(),
            metadata={"scenario": "zero_start"},
        )
        PlanChangeOperation.objects.create(
            operation_id="changeop-lab-pending-change-001",
            change_set=change_set,
            sequence=1,
            operation_type=PlanChangeOperation.OperationType.ADD_NODE,
            target_model="PlanNode",
            new_value={"code": "Z0", "title": "网络招募、报名筛选与责任能力识别"},
            rationale="新增 Z0 网络招募、报名筛选与责任能力识别阶段。",
            is_required=True,
            metadata={},
        )

        response = self.client.get("/admin/simulation-lab/?world_id=simulation0001")

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "待处置计划变更集")
        self.assertNotContains(response, "零起点招募筛选结构化变更")
        self.assertNotContains(response, "/admin/core/planchangeset/changeset-lab-pending-change/change/")

        detail_response = self.client.get(f"/admin/simulation-lab/runs/{run.run_id}/?world_id=simulation0001")
        self.assertContains(detail_response, "计划变更处置")
        self.assertContains(detail_response, "零起点招募筛选结构化变更")
        self.assertContains(detail_response, "可应用")

    def test_admin_simulation_lab_run_detail_marks_malformed_change_set_as_not_applicable(self) -> None:
        self.login_as_superuser()
        self.create_simulation_world()
        run = self.create_finished_run("sim-run-lab-pending-invalid")
        proposal = PlanRevisionProposal.objects.create(
            proposal_id="proposal-lab-pending-invalid",
            run=run,
            plan_revision=run.plan_revision,
            proposal_type=PlanRevisionProposal.ProposalType.ADD_NODE,
            status=PlanRevisionProposal.Status.DRAFT,
            title="坏格式计划建议",
            rationale="测试坏格式变更集。",
            suggested_changes={},
            created_at=timezone.now(),
            metadata={"scenario": "zero_start"},
        )
        change_set = PlanChangeSet.objects.create(
            change_set_id="changeset-lab-pending-invalid",
            run=run,
            proposal=proposal,
            plan_revision=run.plan_revision,
            status=PlanChangeSet.Status.DRAFT,
            title="坏格式计划变更集",
            summary="缺少 add_node 必填字段。",
            created_at=timezone.now(),
            metadata={"scenario": "zero_start"},
        )
        PlanChangeOperation.objects.create(
            operation_id="changeop-lab-pending-invalid-001",
            change_set=change_set,
            sequence=1,
            operation_type=PlanChangeOperation.OperationType.ADD_NODE,
            target_model="ProjectPlan",
            new_value={"scenario": "zero_start"},
            rationale="旧生成逻辑留下的半成品操作。",
            is_required=True,
            metadata={"scenario": "zero_start"},
        )

        response = self.client.get(f"/admin/simulation-lab/runs/{run.run_id}/?world_id=simulation0001")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "坏格式计划变更集")
        self.assertContains(response, "不可应用")
        self.assertContains(response, "缺少必填字段：code")
        self.assertNotContains(response, '<input type="submit" value="弃用">')
        self.assertNotContains(response, "查看 run 详情并设为基线")

    def test_admin_simulation_lab_run_detail_handles_missing_change_set_proposal(self) -> None:
        self.login_as_superuser()
        self.create_simulation_world()
        run = self.create_finished_run("sim-run-lab-missing-proposal")
        proposal = PlanRevisionProposal.objects.create(
            proposal_id="proposal-lab-orphan-source",
            run=run,
            plan_revision=run.plan_revision,
            proposal_type=PlanRevisionProposal.ProposalType.ADD_NODE,
            status=PlanRevisionProposal.Status.DRAFT,
            title="来源建议随后丢失",
            rationale="模拟生产库中遗留的孤儿变更集。",
            suggested_changes={},
            created_at=timezone.now(),
            metadata={"scenario": "zero_start"},
        )
        change_set = PlanChangeSet.objects.create(
            change_set_id="changeset-lab-orphan-proposal",
            run=run,
            proposal=proposal,
            plan_revision=run.plan_revision,
            status=PlanChangeSet.Status.DRAFT,
            title="孤儿计划变更集",
            summary="来源修订建议记录已不存在。",
            created_at=timezone.now(),
            metadata={"scenario": "zero_start"},
        )
        PlanChangeOperation.objects.create(
            operation_id="changeop-lab-orphan-proposal-001",
            change_set=change_set,
            sequence=1,
            operation_type=PlanChangeOperation.OperationType.ADD_NODE,
            target_model="PlanNode",
            new_value={"code": "Z9", "title": "孤儿变更集测试节点"},
            rationale="结构本身有效，但来源建议缺失时不应允许采纳。",
            is_required=True,
            metadata={"scenario": "zero_start"},
        )
        with connection.constraint_checks_disabled():
            PlanChangeSet.objects.filter(change_set_id=change_set.change_set_id).update(
                proposal_id="proposal-lab-missing-source"
            )

        try:
            response = self.client.get(f"/admin/simulation-lab/runs/{run.run_id}/?world_id=simulation0001")
        finally:
            with connection.constraint_checks_disabled():
                PlanChangeSet.objects.filter(change_set_id=change_set.change_set_id).update(
                    proposal_id=proposal.proposal_id
                )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "孤儿计划变更集")
        self.assertContains(response, "来源修订建议")
        self.assertContains(response, "缺失")
        self.assertContains(response, "来源修订建议缺失：proposal-lab-missing-source")
        self.assertContains(response, "不可应用")
        self.assertContains(response, "建议弃用")
        self.assertContains(response, "无法可靠追溯问题来源")
        self.assertNotContains(response, "采纳为下一轮仿真基线")
        self.assertContains(response, "弃用此计划变更")

    def test_admin_simulation_lab_blocks_new_run_when_finished_run_is_unresolved(self) -> None:
        self.login_as_superuser()
        self.create_simulation_world()
        run = self.create_finished_run()
        run.failure_summary = "Z0 网络报名筛选后仍未达到启动门槛"
        run.metadata = {"scenario": "zero_start", "system_interaction_failed": True}
        run.save(update_fields=["failure_summary", "metadata"])

        response = self.client.get("/admin/simulation-lab/?world_id=simulation0001")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "存在已结束但未处置的仿真运行")
        self.assertContains(response, run.run_id)
        self.assertContains(response, "查看详情并处置")
        self.assertContains(response, "disabled")

    def test_admin_simulation_lab_run_detail_shows_pre_disposition_evidence(self) -> None:
        self.login_as_superuser()
        self.create_simulation_world()
        run = self.create_finished_run("sim-run-lab-detail")
        run.failure_summary = "零起点仿真表单交互失败"
        run.metadata = {
            "scenario": "zero_start",
            "completed_hours": 168,
            "observation_window_hours": 168,
            "registered_applicants": 12,
            "screened_applicants": 8,
            "candidate_members": 4,
            "partner_applications": 3,
            "qualified_partners": 0,
            "startup_gate_satisfied": False,
        }
        run.save(update_fields=["failure_summary", "metadata"])
        failure = SimulationFailure.objects.create(
            failure_id="failure-lab-detail",
            run=run,
            failure_type=SimulationFailure.FailureType.RESPONSIBILITY_CLOSURE_MISSING,
            severity=SimulationFailure.Severity.CRITICAL,
            title="Z0 网络报名筛选后仍缺少责任能力闭环",
            description="报名者自述技能不能替代可追责责任文件。",
            simulation_day=8,
            detected_at=timezone.now(),
            metadata={
                "missing_responsibility_domains": ["结构/建筑安全责任", "电气接入与并网责任"],
                "missing_capabilities": [
                    {
                        "code": "meal_support",
                        "name": "做饭与基础生活支持",
                        "required_count": 1,
                        "covered_count": 0,
                        "missing_count": 1,
                    }
                ],
                "missing_document_signers": [
                    {
                        "code": "structural_safety_document",
                        "name": "结构/建筑安全责任文件签署方",
                        "required_count": 1,
                        "covered_count": 0,
                        "missing_count": 1,
                        "document_examples": ["屋顶荷载复核报告"],
                        "acceptable_signers": ["结构工程师"],
                    }
                ],
                "cannot_continue_reasons": ["没有签字盖章或合同责任。"],
                "recommended_actions": ["建立可追责主体线索库。"],
            },
        )
        SimulationTurn.objects.create(
            turn_id="turn-lab-detail-001",
            run=run,
            turn_number=1,
            simulation_day=1,
            summary="收到第一批网络报名。",
            occurred_at=timezone.now(),
            metadata={
                "simulation_hour": 1,
                "applicants_applied": [1, 2],
                "partners_applied": [1],
                "screening_results": [{"application_id": "app-1"}],
                "partner_screening_results": [],
                "candidate_summary": {
                    "registered_applicants": 12,
                    "candidate_members": 4,
                    "partner_applications": 3,
                    "qualified_partners": 0,
                },
                "startup_gate": {
                    "missing_capabilities": [{"name": "做饭与基础生活支持"}],
                    "missing_document_signers": [{"name": "结构/建筑安全责任文件签署方"}],
                },
            },
        )
        proposal = PlanRevisionProposal.objects.create(
            proposal_id="proposal-lab-detail",
            run=run,
            source_failure=failure,
            plan_revision=run.plan_revision,
            proposal_type=PlanRevisionProposal.ProposalType.ADD_NODE,
            status=PlanRevisionProposal.Status.DRAFT,
            title="增加网络报名与责任能力筛选前置阶段",
            rationale="报名数量和兴趣不能代表可执行团队形成。",
            suggested_changes={"add_stage": "Z0 网络招募、报名筛选与责任能力识别"},
            created_at=timezone.now(),
            metadata={"scenario": "zero_start"},
        )
        change_set = PlanChangeSet.objects.create(
            change_set_id="changeset-lab-detail",
            run=run,
            proposal=proposal,
            plan_revision=run.plan_revision,
            status=PlanChangeSet.Status.DRAFT,
            title="零起点招募筛选结构化变更",
            summary="新增 Z0 前置阶段。",
            created_at=timezone.now(),
            metadata={"scenario": "zero_start"},
        )
        PlanChangeOperation.objects.create(
            operation_id="changeop-lab-detail-001",
            change_set=change_set,
            sequence=1,
            operation_type=PlanChangeOperation.OperationType.ADD_NODE,
            target_model="PlanNode",
            new_value={"code": "Z0", "title": "网络招募、报名筛选与责任能力识别"},
            rationale="新增 Z0 网络招募、报名筛选与责任能力识别阶段。",
            is_required=True,
            metadata={},
        )

        response = self.client.get(f"/admin/simulation-lab/runs/{run.run_id}/?world_id=simulation0001")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, run.run_id)
        self.assertContains(response, "仿真审阅报告")
        self.assertContains(response, "审阅结论")
        self.assertContains(response, "启动门槛未满足")
        self.assertContains(response, "关键统计")
        self.assertContains(response, "主动报名人数")
        self.assertContains(response, "12")
        self.assertContains(response, "审阅证据清单")
        self.assertContains(response, "责任文件签署方缺口")
        self.assertContains(response, "屋顶荷载复核报告")
        self.assertContains(response, "关键时间线")
        self.assertContains(response, "能力/文件缺口")
        self.assertContains(response, "运行控制")
        self.assertContains(response, "缺失责任闭环")
        self.assertContains(response, "结构/建筑安全责任")
        self.assertContains(response, "成员能力缺口")
        self.assertContains(response, "做饭与基础生活支持")
        self.assertContains(response, "当前不能继续的原因")
        self.assertContains(response, "没有签字盖章或合同责任。")
        self.assertContains(response, "增加网络报名与责任能力筛选前置阶段")
        self.assertContains(response, "零起点招募筛选结构化变更")
        self.assertContains(response, "新增 Z0 网络招募、报名筛选与责任能力识别阶段。")
        self.assertContains(response, "尚未吸收到下一轮仿真基线")
        self.assertContains(response, "这里处理的是是否采纳本变更集")
        self.assertContains(response, "计划变更处置")
        self.assertContains(response, "采纳为下一轮仿真基线")
        self.assertNotContains(response, "/admin/core/planchangeset/changeset-lab-detail/change/")
        self.assertContains(response, "收到第一批网络报名。")
        self.assertContains(response, "该仿真运行仍可继续推进")
        self.assertContains(response, "继续当前仿真")
        self.assertContains(response, "中止本轮仿真")
        self.assertContains(response, "显示原始 JSON 数据")

    def test_admin_simulation_lab_marks_malformed_change_set_as_not_applicable(self) -> None:
        self.login_as_superuser()
        self.create_simulation_world()
        run = self.create_finished_run("sim-run-lab-invalid-change")
        proposal = PlanRevisionProposal.objects.create(
            proposal_id="proposal-lab-invalid-change",
            run=run,
            plan_revision=run.plan_revision,
            proposal_type=PlanRevisionProposal.ProposalType.ADD_NODE,
            status=PlanRevisionProposal.Status.DRAFT,
            title="增加零起点筛选阶段",
            rationale="测试坏格式变更集。",
            suggested_changes={},
            created_at=timezone.now(),
            metadata={"scenario": "zero_start"},
        )
        change_set = PlanChangeSet.objects.create(
            change_set_id="changeset-lab-invalid-change",
            run=run,
            proposal=proposal,
            plan_revision=run.plan_revision,
            status=PlanChangeSet.Status.DRAFT,
            title="坏格式计划变更集",
            summary="缺少 add_node 必填字段。",
            created_at=timezone.now(),
            metadata={"scenario": "zero_start"},
        )
        PlanChangeOperation.objects.create(
            operation_id="changeop-lab-invalid-change-001",
            change_set=change_set,
            sequence=1,
            operation_type=PlanChangeOperation.OperationType.ADD_NODE,
            target_model="ProjectPlan",
            new_value={"scenario": "zero_start"},
            rationale="旧生成逻辑留下的半成品操作。",
            is_required=True,
            metadata={"scenario": "zero_start"},
        )

        response = self.client.get(f"/admin/simulation-lab/runs/{run.run_id}/?world_id=simulation0001")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "不可应用")
        self.assertContains(response, "缺少必填字段：code")
        self.assertContains(response, "建议先修复或弃用")
        self.assertNotContains(response, '<input type="submit" value="采纳为下一轮仿真基线">')

    def test_admin_simulation_lab_completed_run_marks_old_failure_as_resolved(self) -> None:
        self.login_as_superuser()
        self.create_simulation_world()
        run = self.create_finished_run("sim-run-lab-completed-with-history")
        run.status = SimulationRun.Status.COMPLETED
        run.failure_summary = ""
        run.metadata = {
            "scenario": "zero_start",
            "completed_hours": 504,
            "observation_window_hours": 168,
            "startup_gate": {
                "startup_gate_satisfied": True,
                "project_phase": "ready_to_start",
                "missing_capabilities": [],
                "missing_document_signers": [],
                "capability_coverage": [
                    {
                        "code": "meal_support",
                        "name": "做饭与基础生活支持",
                        "required_count": 1,
                        "covered_count": 5,
                        "missing_count": 0,
                    }
                ],
                "document_signer_coverage": [
                    {
                        "code": "structural_safety_document",
                        "name": "结构/建筑安全责任文件签署方",
                        "required_count": 1,
                        "covered_count": 1,
                        "missing_count": 0,
                    }
                ],
            },
        }
        run.save(update_fields=["status", "failure_summary", "metadata"])
        failure = SimulationFailure.objects.create(
            failure_id="failure-lab-completed-history",
            run=run,
            failure_type=SimulationFailure.FailureType.RESPONSIBILITY_CLOSURE_MISSING,
            severity=SimulationFailure.Severity.CRITICAL,
            title="Z0 自媒体报名筛选后仍未达到启动门槛",
            description="初始成员能力矩阵和文件签署方矩阵尚未补齐。",
            simulation_day=8,
            detected_at=timezone.now(),
            metadata={
                "scenario": "zero_start",
                "startup_gate_satisfied": False,
                "missing_capabilities": [
                    {
                        "code": "meal_support",
                        "name": "做饭与基础生活支持",
                        "required_count": 1,
                        "covered_count": 0,
                        "missing_count": 1,
                    }
                ],
                "missing_document_signers": [
                    {
                        "code": "structural_safety_document",
                        "name": "结构/建筑安全责任文件签署方",
                        "required_count": 1,
                        "covered_count": 0,
                        "missing_count": 1,
                    }
                ],
                "cannot_continue_reasons": ["责任文件签署方尚未到位。"],
            },
        )
        SimulationTurn.objects.create(
            turn_id="turn-lab-completed-history",
            run=run,
            turn_number=507,
            simulation_day=22,
            summary="启动门槛和工程前置责任闭环均已满足。",
            occurred_at=timezone.now(),
            metadata={
                "simulation_hour": 504,
                "title": "工程前置责任闭环观察窗口结束",
                "candidate_summary": {
                    "registered_applicants": 156,
                    "candidate_members": 129,
                    "partner_applications": 17,
                    "qualified_partners": 10,
                },
                "startup_gate": run.metadata["startup_gate"],
                "pre_engineering": {
                    "status": "completed",
                    "completed": True,
                    "completed_milestone_count": 8,
                    "pending_milestone_count": 0,
                    "selected_site_code": "site-roof-a",
                },
            },
        )
        proposal = PlanRevisionProposal.objects.create(
            proposal_id="proposal-lab-completed-history",
            run=run,
            source_failure=failure,
            plan_revision=run.plan_revision,
            proposal_type=PlanRevisionProposal.ProposalType.ADD_NODE,
            status=PlanRevisionProposal.Status.DRAFT,
            title="增加自媒体报名筛选与启动门槛矩阵",
            rationale="主动报名不等于项目可以启动。",
            suggested_changes={"add_stage": "Z0 网络招募、报名筛选与责任能力识别"},
            created_at=timezone.now(),
            metadata={"scenario": "zero_start"},
        )
        change_set = PlanChangeSet.objects.create(
            change_set_id="changeset-lab-completed-history",
            run=run,
            proposal=proposal,
            plan_revision=run.plan_revision,
            status=PlanChangeSet.Status.DRAFT,
            title="零起点启动门槛结构化变更",
            summary="新增 Z0 前置阶段。",
            created_at=timezone.now(),
            metadata={"scenario": "zero_start"},
        )
        PlanChangeOperation.objects.create(
            operation_id="changeop-lab-completed-history-001",
            change_set=change_set,
            sequence=1,
            operation_type=PlanChangeOperation.OperationType.ADD_NODE,
            target_model="PlanNode",
            new_value={
                "code": "Z0",
                "title": "网络招募、报名筛选与责任能力识别",
                "node_type": PlanNode.NodeType.RECRUITMENT,
                "planned_duration_days": 7,
            },
            rationale="新增 Z0 网络招募、报名筛选与责任能力识别阶段。",
            is_required=True,
            metadata={},
        )

        response = self.client.get(f"/admin/simulation-lab/runs/{run.run_id}/?world_id=simulation0001")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "仿真完成：中途阻塞已被后续推进解除")
        self.assertContains(response, "本轮共有 1 条中途阻塞记录，后续推进已经补齐对应门槛")
        self.assertContains(response, "中途阻塞（已解除）")
        self.assertContains(response, "后续推进已补齐当前门槛")
        self.assertContains(response, "中途阻塞，后续已解除")
        self.assertContains(response, "对应中途阻塞已在本轮后续推进中解除")
        self.assertContains(response, "本轮后续推进已自然补齐该问题")
        self.assertContains(response, "系统建议")
        self.assertContains(response, "建议采纳")
        self.assertContains(response, "说明该前置阶段是真实经验")
        self.assertNotContains(response, "启动门槛未满足：本轮有复盘价值")

    def test_admin_simulation_lab_completed_run_does_not_resolve_non_gate_failure(self) -> None:
        self.login_as_superuser()
        self.create_simulation_world()
        run = self.create_finished_run("sim-run-lab-completed-system-failure")
        run.status = SimulationRun.Status.COMPLETED
        run.failure_summary = ""
        run.metadata = {
            "scenario": "zero_start",
            "completed_hours": 504,
            "startup_gate": {
                "startup_gate_satisfied": True,
                "missing_capabilities": [],
                "missing_document_signers": [],
                "capability_coverage": [],
                "document_signer_coverage": [],
            },
        }
        run.save(update_fields=["status", "failure_summary", "metadata"])
        failure = SimulationFailure.objects.create(
            failure_id="failure-lab-completed-system",
            run=run,
            failure_type=SimulationFailure.FailureType.EXECUTION_ISSUE,
            severity=SimulationFailure.Severity.CRITICAL,
            title="报名表单系统交互失败",
            description="虚拟报名者提交表单时出现系统错误。",
            simulation_day=2,
            detected_at=timezone.now(),
            metadata={
                "scenario": "zero_start",
                "failure_kind": "system_form_interaction_failed",
                "cannot_continue_reasons": ["报名表单链路失败。"],
            },
        )
        PlanRevisionProposal.objects.create(
            proposal_id="proposal-lab-completed-system",
            run=run,
            source_failure=failure,
            plan_revision=run.plan_revision,
            proposal_type=PlanRevisionProposal.ProposalType.ADD_NODE,
            status=PlanRevisionProposal.Status.DRAFT,
            title="修复报名表单系统交互",
            rationale="系统错误不能被业务门槛自然覆盖。",
            suggested_changes={},
            created_at=timezone.now(),
            metadata={"scenario": "zero_start"},
        )

        response = self.client.get(f"/admin/simulation-lab/runs/{run.run_id}/?world_id=simulation0001")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "当前失败证据")
        self.assertNotContains(response, "中途阻塞（已解除）")
        self.assertNotContains(response, "本轮共有 1 条中途阻塞记录")
        self.assertNotContains(response, "本轮后续推进已自然补齐该问题")

    def test_admin_simulation_lab_completed_status_does_not_hide_open_gate_gaps(self) -> None:
        self.login_as_superuser()
        self.create_simulation_world()
        run = self.create_finished_run("sim-run-lab-completed-open-gate")
        run.status = SimulationRun.Status.COMPLETED
        run.failure_summary = ""
        run.metadata = {
            "scenario": "zero_start",
            "completed_hours": 504,
            "startup_gate": {
                "startup_gate_satisfied": False,
                "missing_capabilities": [
                    {
                        "code": "meal_support",
                        "name": "做饭与基础生活支持",
                        "required_count": 1,
                        "covered_count": 0,
                        "missing_count": 1,
                    }
                ],
                "missing_document_signers": [],
                "capability_coverage": [],
                "document_signer_coverage": [],
            },
        }
        run.save(update_fields=["status", "failure_summary", "metadata"])

        response = self.client.get(f"/admin/simulation-lab/runs/{run.run_id}/?world_id=simulation0001")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "启动门槛未满足：本轮有复盘价值")
        self.assertNotContains(response, "仿真完成：未发现阻断性失败")

    def test_admin_simulation_lab_can_reject_change_set(self) -> None:
        self.login_as_superuser()
        self.create_simulation_world()
        run = self.create_finished_run("sim-run-lab-reject-change")
        proposal = PlanRevisionProposal.objects.create(
            proposal_id="proposal-lab-reject-change",
            run=run,
            plan_revision=run.plan_revision,
            proposal_type=PlanRevisionProposal.ProposalType.ADD_NODE,
            status=PlanRevisionProposal.Status.DRAFT,
            title="待弃用计划建议",
            rationale="测试弃用变更集。",
            suggested_changes={},
            created_at=timezone.now(),
            metadata={"scenario": "zero_start"},
        )
        change_set = PlanChangeSet.objects.create(
            change_set_id="changeset-lab-reject-change",
            run=run,
            proposal=proposal,
            plan_revision=run.plan_revision,
            status=PlanChangeSet.Status.DRAFT,
            title="待弃用计划变更集",
            summary="测试弃用动作。",
            created_at=timezone.now(),
            metadata={"scenario": "zero_start"},
        )

        response = self.client.post(
            f"/admin/simulation-lab/runs/{run.run_id}/change-sets/{change_set.change_set_id}/reject/",
            {"world_id": "simulation0001", "reason": "旧模型已被替代。"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        change_set.refresh_from_db()
        self.assertEqual(change_set.status, PlanChangeSet.Status.REJECTED)
        self.assertEqual(change_set.metadata["rejection"]["reason"], "旧模型已被替代。")
        self.assertContains(response, "已弃用计划变更集")

    def test_admin_simulation_lab_can_apply_change_set_from_run_detail(self) -> None:
        self.login_as_superuser()
        self.create_simulation_world()
        run = self.create_finished_run("sim-run-lab-apply")
        proposal = PlanRevisionProposal.objects.create(
            proposal_id="proposal-lab-apply",
            run=run,
            plan_revision=run.plan_revision,
            proposal_type=PlanRevisionProposal.ProposalType.ADD_NODE,
            status=PlanRevisionProposal.Status.DRAFT,
            title="增加网络报名与责任能力筛选前置阶段",
            rationale="报名数量和兴趣不能代表可执行团队形成。",
            suggested_changes={"add_stage": "Z0 网络招募、报名筛选与责任能力识别"},
            created_at=timezone.now(),
            metadata={"scenario": "zero_start"},
        )
        change_set = PlanChangeSet.objects.create(
            change_set_id="changeset-lab-apply",
            run=run,
            proposal=proposal,
            plan_revision=run.plan_revision,
            status=PlanChangeSet.Status.DRAFT,
            title="零起点招募筛选结构化变更",
            summary="新增 Z0 前置阶段。",
            created_at=timezone.now(),
            metadata={"scenario": "zero_start"},
        )
        PlanChangeOperation.objects.create(
            operation_id="changeop-lab-apply-001",
            change_set=change_set,
            sequence=1,
            operation_type=PlanChangeOperation.OperationType.ADD_NODE,
            target_model="PlanNode",
            new_value={
                "code": "Z0",
                "title": "网络招募、报名筛选与责任能力识别",
                "node_type": PlanNode.NodeType.RECRUITMENT,
                "planned_duration_days": 7,
            },
            rationale="新增 Z0 网络招募、报名筛选与责任能力识别阶段。",
            is_required=True,
            metadata={},
        )

        response = self.client.post(
            f"/admin/simulation-lab/runs/{run.run_id}/change-sets/{change_set.change_set_id}/apply/",
            {"world_id": "simulation0001"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        change_set.refresh_from_db()
        self.assertEqual(change_set.status, PlanChangeSet.Status.APPLIED)
        self.assertIsNotNone(change_set.applied_revision)
        self.assertEqual(change_set.applied_revision.status, PlanRevision.Status.PUBLISHED)
        self.assertIsNotNone(change_set.applied_revision.published_at)
        self.assertTrue(PlanNode.objects.filter(revision=change_set.applied_revision, code="Z0").exists())
        self.assertContains(response, "已采纳并设为下一轮基线")
        self.assertContains(response, change_set.applied_revision.revision_code)

    def test_admin_simulation_lab_can_publish_already_applied_draft_change_set(self) -> None:
        self.login_as_superuser()
        self.create_simulation_world()
        run = self.create_finished_run("sim-run-lab-publish-draft")
        proposal = PlanRevisionProposal.objects.create(
            proposal_id="proposal-lab-publish-draft",
            run=run,
            plan_revision=run.plan_revision,
            proposal_type=PlanRevisionProposal.ProposalType.ADD_NODE,
            status=PlanRevisionProposal.Status.DRAFT,
            title="增加网络报名与责任能力筛选前置阶段",
            rationale="报名数量和兴趣不能代表可执行团队形成。",
            suggested_changes={"add_stage": "Z0 网络招募、报名筛选与责任能力识别"},
            created_at=timezone.now(),
            metadata={"scenario": "zero_start"},
        )
        draft_revision = PlanRevision.objects.create(
            revision_id="rev-lab-publish-draft-v0_1_1",
            plan=run.plan_revision.plan,
            revision_code="v0.1.1",
            status=PlanRevision.Status.DRAFT,
            title="已应用但未发布版本",
            change_summary="修复前生成的草稿版本。",
            created_at=timezone.now(),
        )
        change_set = PlanChangeSet.objects.create(
            change_set_id="changeset-lab-publish-draft",
            run=run,
            proposal=proposal,
            plan_revision=run.plan_revision,
            status=PlanChangeSet.Status.APPLIED,
            title="零起点招募筛选结构化变更",
            summary="新增 Z0 前置阶段。",
            created_at=timezone.now(),
            applied_at=timezone.now(),
            applied_revision=draft_revision,
            metadata={"scenario": "zero_start"},
        )

        detail_response = self.client.get(f"/admin/simulation-lab/runs/{run.run_id}/?world_id=simulation0001")
        self.assertContains(detail_response, "已生成但尚未设为基线")
        self.assertContains(detail_response, "采纳为下一轮仿真基线")

        response = self.client.post(
            f"/admin/simulation-lab/runs/{run.run_id}/change-sets/{change_set.change_set_id}/apply/",
            {"world_id": "simulation0001"},
            follow=True,
        )

        draft_revision.refresh_from_db()
        run.plan_revision.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(draft_revision.status, PlanRevision.Status.PUBLISHED)
        self.assertIsNotNone(draft_revision.published_at)
        self.assertEqual(run.plan_revision.status, PlanRevision.Status.RETIRED)
        self.assertContains(response, "已采纳并设为下一轮基线")

    def test_admin_simulation_lab_archive_action_records_current_admin(self) -> None:
        user = self.login_as_superuser()
        self.create_simulation_world()
        run = self.create_finished_run("sim-run-lab-archive")

        with TemporaryDirectory() as archive_root, override_settings(SIMULATION_ARCHIVE_ROOT=archive_root):
            response = self.client.post(
                f"/admin/simulation-lab/runs/{run.run_id}/archive/",
                {
                    "world_id": "simulation0001",
                    "reason": "人工复盘后确认需要永久归档。",
                },
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        disposition = SimulationRunDisposition.objects.get(source_run_id=run.run_id)
        snapshot = SimulationSnapshot.objects.get(source_run_id=run.run_id)
        self.assertEqual(disposition.disposition, SimulationRunDisposition.Disposition.ARCHIVED)
        self.assertEqual(disposition.snapshot, snapshot)
        self.assertEqual(disposition.decided_by, user.username)
        self.assertContains(response, "已归档")

    def test_admin_simulation_lab_discard_action_records_current_admin(self) -> None:
        user = self.login_as_superuser()
        self.create_simulation_world()
        run = self.create_finished_run("sim-run-lab-discard")

        response = self.client.post(
            f"/admin/simulation-lab/runs/{run.run_id}/discard/",
            {
                "world_id": "simulation0001",
                "reason": "参数误设，不作为正式历史保留。",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        disposition = SimulationRunDisposition.objects.get(source_run_id=run.run_id)
        self.assertEqual(disposition.disposition, SimulationRunDisposition.Disposition.DISCARDED)
        self.assertEqual(disposition.decided_by, user.username)
        self.assertContains(response, "已记录废弃处置")

    def test_admin_simulation_lab_abort_action_stops_running_run(self) -> None:
        user = self.login_as_superuser()
        self.create_simulation_world()
        run = self.create_finished_run("sim-run-lab-abort")
        run.status = SimulationRun.Status.RUNNING
        run.ended_at = None
        run.failure_summary = "启动门槛未满足，继续筹备和招募。"
        run.metadata = {"scenario": "zero_start", "current_hour": 1007, "can_continue": True}
        run.save(update_fields=["status", "ended_at", "failure_summary", "metadata"])

        response = self.client.post(
            f"/admin/simulation-lab/runs/{run.run_id}/abort/",
            {
                "world_id": "simulation0001",
                "reason": "合作方生成模型不完整，本轮不作为正式仿真结论。",
            },
            follow=True,
        )

        run.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(run.status, SimulationRun.Status.ABORTED)
        self.assertIsNotNone(run.ended_at)
        self.assertIn("人工中止", run.failure_summary)
        self.assertEqual(run.metadata["aborted"]["aborted_by"], user.username)
        self.assertTrue(SimulationTurn.objects.filter(run=run, metadata__title="人工中止本轮仿真").exists())
        self.assertTrue(Event.objects.filter(simulation_run=run, title="人工中止本轮仿真").exists())
        self.assertContains(response, "已中止本轮仿真")
        self.assertContains(response, "归档本次仿真运行")
        self.assertContains(response, "废弃本次仿真运行")

    def test_admin_simulation_lab_lists_archived_snapshots(self) -> None:
        self.login_as_superuser()
        snapshot = self.create_snapshot()

        response = self.client.get("/admin/simulation-lab/snapshots/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "仿真快照")
        self.assertContains(response, snapshot.snapshot_id)
        self.assertContains(response, "simulation0001")

    def test_admin_simulation_lab_snapshot_detail_shows_indexed_items(self) -> None:
        self.login_as_superuser()
        with TemporaryDirectory() as archive_path:
            self.create_raw_plan_node_archive(archive_path)
            snapshot = self.create_snapshot(raw_archive_path=archive_path)

            response = self.client.get(f"/admin/simulation-lab/snapshots/{snapshot.snapshot_id}/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "责任闭环缺失")
        self.assertContains(response, "C3 光伏一期 0.5MW")
        self.assertContains(response, "core.SimulationRun")
        self.assertContains(response, "原始归档包")

    def test_admin_simulation_lab_snapshot_verify_reports_archive_errors(self) -> None:
        self.login_as_superuser()
        snapshot = self.create_snapshot()

        response = self.client.post(f"/admin/simulation-lab/snapshots/{snapshot.snapshot_id}/verify/", follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "快照校验失败")
        self.assertContains(response, "raw archive directory is missing")

    def test_admin_simulation_lab_advance_does_not_write_real_world_state_without_run_scope(self) -> None:
        self.login_as_superuser()
        response = self.client.post("/admin/simulation-lab/advance/", follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "仿真写库边界自检通过")
        self.assertContains(response, "不能默认写入真实世界数据")
        self.task.refresh_from_db()
        self.resource.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.OPEN)
        self.assertIsNone(self.task.assignee_member_id)
        self.assertEqual(self.resource.current_stock, Decimal("100.000"))
        self.assertFalse(LedgerEntry.objects.filter(related_task=self.task).exists())
        self.assertFalse(Event.objects.filter(generated_by=Event.GeneratedBy.SIMULATION_ENGINE).exists())

    def test_unscoped_simulation_turn_rejects_real_world_mutation(self) -> None:
        with self.assertRaisesMessage(DomainError, "不能默认写入真实世界数据"):
            run_simulation_turn(simulation_day=1)

        self.task.refresh_from_db()
        self.resource.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.OPEN)
        self.assertIsNone(self.task.assignee_member_id)
        self.assertEqual(self.resource.current_stock, Decimal("100.000"))
        self.assertFalse(LedgerEntry.objects.filter(related_task=self.task).exists())
        self.assertFalse(Event.objects.filter(generated_by=Event.GeneratedBy.SIMULATION_ENGINE).exists())


class SimulationLabResetWorldTests(TestCase):
    """Tests for the reset-world-to-zero-start maintenance feature."""

    def setUp(self) -> None:
        self.user = get_user_model().objects.create_user(
            username="simulation-root",
            password="test-password",
        )
        self.user.is_staff = True
        self.user.is_superuser = True
        self.user.save(update_fields=["is_staff", "is_superuser"])
        self.client.force_login(self.user)

    def _create_simulation_world(self, world_id: str = "simulation0001") -> WorldRegistry:
        world, _ = WorldRegistry.objects.update_or_create(
            world_id=world_id,
            defaults={
                "name": f"Simulation {world_id[-4:]}",
                "world_type": WorldRegistry.WorldType.SIMULATION,
                "database_alias": "default",
                "database_name": "test_control",
                "status": WorldRegistry.Status.ACTIVE,
            },
        )
        return world

    def _reset_post_data(self, world: WorldRegistry, *, force: bool = False):
        return {
            "world_id": world.world_id,
            "confirm_world_id": world.world_id,
            "confirm_text": "确认重置",
            "force_reset": "on" if force else "",
        }

    def test_reset_world_requires_superuser(self) -> None:
        """Non-superuser should get 403 for POST to reset-world."""
        non_staff = get_user_model().objects.create_user(username="regular", password="test")
        non_staff.is_staff = True
        non_staff.save(update_fields=["is_staff"])
        self.client.force_login(non_staff)

        world = self._create_simulation_world()
        response = self.client.post("/admin/simulation-lab/reset-world/", self._reset_post_data(world))

        self.assertEqual(response.status_code, 403)

    def test_reset_world_rejects_missing_confirm_world_id(self) -> None:
        """Missing confirm_world_id should reject without clearing data."""
        world = self._create_simulation_world()
        Member.objects.create(
            member_no="test-001",
            display_name="测试成员",
            status=Member.Status.ACTIVE,
            batch_id="test-batch",
            joined_simulation_day=0,
            credit_floor=-100,
            profile={},
            created_at=timezone.now(),
        )

        response = self.client.post(
            "/admin/simulation-lab/reset-world/",
            {
                "world_id": world.world_id,
                "confirm_world_id": "",
                "confirm_text": "确认重置",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "世界ID确认不匹配")
        self.assertTrue(Member.objects.filter(member_no="test-001").exists())

    def test_reset_world_rejects_wrong_confirm_text(self) -> None:
        """Wrong confirm_text should reject without clearing data."""
        world = self._create_simulation_world()
        Member.objects.create(
            member_no="test-002",
            display_name="测试成员2",
            status=Member.Status.ACTIVE,
            batch_id="test-batch",
            joined_simulation_day=0,
            credit_floor=-100,
            profile={},
            created_at=timezone.now(),
        )

        response = self.client.post(
            "/admin/simulation-lab/reset-world/",
            {
                "world_id": world.world_id,
                "confirm_world_id": world.world_id,
                "confirm_text": "错误的文字",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "必须输入「确认重置」四个字")
        self.assertTrue(Member.objects.filter(member_no="test-002").exists())

    def test_reset_world_rejects_realworld(self) -> None:
        """Realworld should be rejected for reset.
        This tests the service directly since selected_simulation_world will
        never return a realworld in the view pipeline."""
        from simulation.world_reset import reset_simulation_world_to_zero_start

        world, _ = WorldRegistry.objects.update_or_create(
            world_id="realworld",
            defaults={
                "name": "Real World",
                "world_type": WorldRegistry.WorldType.REAL,
                "database_alias": "default",
                "database_name": "test_control",
                "status": WorldRegistry.Status.ACTIVE,
            },
        )

        with self.assertRaises(DomainError) as ctx:
            reset_simulation_world_to_zero_start(world, actor="test", force=True)
        self.assertIn("只允许对仿真世界", str(ctx.exception))

    def test_reset_world_rejects_inactive_world(self) -> None:
        """Archived world should be rejected at the view level with explicit error."""
        world = self._create_simulation_world()
        world.status = WorldRegistry.Status.ARCHIVED
        world.save(update_fields=["status"])

        response = self.client.post(
            "/admin/simulation-lab/reset-world/",
            self._reset_post_data(world),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "只允许对启用状态的仿真世界重置")

    def test_reset_service_rejects_inactive_world(self) -> None:
        """The service-level validation rejects inactive worlds."""
        world = self._create_simulation_world()
        world.status = WorldRegistry.Status.ARCHIVED
        world.save(update_fields=["status"])

        from simulation.world_reset import reset_simulation_world_to_zero_start

        with self.assertRaises(DomainError) as ctx:
            reset_simulation_world_to_zero_start(world, actor="test", force=True)
        self.assertIn("只允许对启用状态", str(ctx.exception))

    def test_reset_world_rejects_running_run_without_force(self) -> None:
        """Running run without force_reset should block."""
        world = self._create_simulation_world()
        plan = ProjectPlan.objects.create(
            plan_id="plan-running",
            name="Running Plan",
            status=ProjectPlan.Status.ACTIVE,
            created_at=timezone.now(),
        )
        revision = PlanRevision.objects.create(
            revision_id="rev-running",
            plan=plan,
            revision_code="v0.1.0",
            status=PlanRevision.Status.PUBLISHED,
            title="Test Revision",
            change_summary="test",
            created_at=timezone.now(),
            published_at=timezone.now(),
        )
        SimulationRun.objects.create(
            run_id="sim-run-running",
            plan_revision=revision,
            status=SimulationRun.Status.RUNNING,
            current_day=1,
            max_turns=1,
            started_at=timezone.now(),
            metadata={},
        )

        response = self.client.post(
            "/admin/simulation-lab/reset-world/",
            self._reset_post_data(world, force=False),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "仍有运行中的仿真")
        self.assertTrue(SimulationRun.objects.filter(run_id="sim-run-running").exists())

    def test_reset_world_unresolved_run_without_force(self) -> None:
        """Unresolved finished run without force_reset should block."""
        world = self._create_simulation_world()
        plan = ProjectPlan.objects.create(
            plan_id="plan-unresolved",
            name="Unresolved Plan",
            status=ProjectPlan.Status.ACTIVE,
            created_at=timezone.now(),
        )
        revision = PlanRevision.objects.create(
            revision_id="rev-unresolved",
            plan=plan,
            revision_code="v0.1.0",
            status=PlanRevision.Status.PUBLISHED,
            title="Test Revision",
            change_summary="test",
            created_at=timezone.now(),
            published_at=timezone.now(),
        )
        SimulationRun.objects.create(
            run_id="sim-run-unresolved",
            plan_revision=revision,
            status=SimulationRun.Status.FAILED,
            current_day=1,
            max_turns=1,
            started_at=timezone.now(),
            ended_at=timezone.now(),
            metadata={"scenario": "completed_example"},
        )

        response = self.client.post(
            "/admin/simulation-lab/reset-world/",
            self._reset_post_data(world, force=False),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "已结束但未处置")
        self.assertTrue(SimulationRun.objects.filter(run_id="sim-run-unresolved").exists())

    def test_reset_world_force_reset_succeeds(self) -> None:
        """Force reset with correct confirmation should flush and re-seed."""
        world = self._create_simulation_world()
        # Create some pre-existing business data
        Member.objects.create(
            member_no="old-member-001",
            display_name="旧成员",
            status=Member.Status.ACTIVE,
            batch_id="old-batch",
            joined_simulation_day=1,
            credit_floor=-500,
            profile={},
            created_at=timezone.now(),
        )
        plan = ProjectPlan.objects.create(
            plan_id="old-plan",
            name="旧计划",
            status=ProjectPlan.Status.ACTIVE,
            created_at=timezone.now(),
        )
        revision = PlanRevision.objects.create(
            revision_id="old-rev",
            plan=plan,
            revision_code="v1.0.0",
            status=PlanRevision.Status.PUBLISHED,
            title="旧版本",
            change_summary="test",
            created_at=timezone.now(),
            published_at=timezone.now(),
        )
        run = SimulationRun.objects.create(
            run_id="sim-run-force",
            plan_revision=revision,
            status=SimulationRun.Status.RUNNING,
            current_day=1,
            max_turns=1,
            started_at=timezone.now(),
            metadata={"scenario": "zero_start"},
        )
        SimulationTurn.objects.create(
            turn_id="turn-force",
            run=run,
            turn_number=1,
            simulation_day=1,
            occurred_at=timezone.now(),
        )

        response = self.client.post(
            "/admin/simulation-lab/reset-world/",
            self._reset_post_data(world, force=True),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "已成功重置到 zero_start 基线")

        # Old data should be gone
        self.assertFalse(Member.objects.filter(member_no="old-member-001").exists())
        self.assertFalse(SimulationRun.objects.filter(run_id="sim-run-force").exists())
        self.assertFalse(SimulationTurn.objects.filter(turn_id="turn-force").exists())

        # Zero-start baseline should exist
        self.assertTrue(Member.objects.filter(member_no="founder-0001").exists())
        self.assertTrue(ProjectPlan.objects.filter(plan_id="plan-zero-start").exists())
        self.assertTrue(PlanRevision.objects.filter(revision_id="plan-zero-start-rev-v0_0_1").exists())

        # No SimulationRun or SimulationTurn should have been created by reset
        self.assertEqual(SimulationRun.objects.count(), 0)
        self.assertEqual(SimulationTurn.objects.count(), 0)

    def test_reset_world_writes_maintenance_log(self) -> None:
        """Successful reset should write a WorldMaintenanceLog in control DB."""
        from worlds.models import WorldMaintenanceLog

        world = self._create_simulation_world()

        self.client.post(
            "/admin/simulation-lab/reset-world/",
            self._reset_post_data(world, force=True),
            follow=True,
        )

        log = WorldMaintenanceLog.objects.first()
        self.assertIsNotNone(log)
        self.assertEqual(log.world_id, world.world_id)
        self.assertEqual(log.action, WorldMaintenanceLog.Action.RESET_ZERO_START)
        self.assertEqual(log.status, WorldMaintenanceLog.StatusChoices.SUCCEEDED)
        self.assertEqual(log.actor_username, self.user.username)
        self.assertTrue(log.force)

    def test_reset_world_page_shows_count_table_and_reset_form(self) -> None:
        """The simulation-lab page should show reset module with counts and form."""
        world = self._create_simulation_world()

        response = self.client.get(f"/admin/simulation-lab/?world_id={world.world_id}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "重置仿真世界")
        self.assertContains(response, "重置到零起点基线")
        self.assertContains(response, "确认重置")
        self.assertContains(response, "force_reset")
        self.assertContains(response, "当前记录数")

    def test_reset_world_with_bootstrap_admin_uses_configured_founder(self) -> None:
        """With bootstrap admin enabled, zero_start founder is the real admin user."""
        import os
        from unittest import mock

        world = self._create_simulation_world()
        # First, do a regular seed to populate baseline
        member = Member.objects.create(
            member_no="some-existing-data",
            display_name="existing",
            status=Member.Status.ACTIVE,
            batch_id="x",
            joined_simulation_day=0,
            credit_floor=-100,
            profile={},
            created_at=timezone.now(),
        )

        bootstrap_env = {
            "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_ENABLED": "true",
            "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_USERNAME": self.user.username,
            "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_PASSWORD": "not-change-me-pls",
            "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_EMAIL": "admin@test.dev",
            "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_MEMBER_NO": self.user.username,
            "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_DISPLAY_NAME": "Bootstrap Admin",
        }

        with mock.patch.dict(os.environ, bootstrap_env, clear=False):
            response = self.client.post(
                "/admin/simulation-lab/reset-world/",
                self._reset_post_data(world, force=True),
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "已成功重置到 zero_start 基线")

        # Reset should have created the bootstrap admin member
        self.assertTrue(Member.objects.filter(member_no=self.user.username).exists())
        bootstrap_member = Member.objects.get(member_no=self.user.username)
        self.assertEqual(bootstrap_member.display_name, "Bootstrap Admin")

        # Founder-0001 should NOT have been created as an extra member
        self.assertFalse(Member.objects.filter(member_no="founder-0001").exists())

    def test_reset_world_rejects_world_id_mismatch(self) -> None:
        """confirm_world_id must match the actual world_id."""
        world = self._create_simulation_world()

        response = self.client.post(
            "/admin/simulation-lab/reset-world/",
            {
                "world_id": world.world_id,
                "confirm_world_id": "simulation0002",
                "confirm_text": "确认重置",
                "force_reset": "on",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "世界ID确认不匹配")

    def test_reset_world_missing_world_id_rejected(self) -> None:
        """POST without world_id must be rejected, not fallback to any world."""
        response = self.client.post(
            "/admin/simulation-lab/reset-world/",
            {
                "world_id": "",
                "confirm_world_id": "anything",
                "confirm_text": "确认重置",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "必须提交目标 world_id")

    def test_reset_world_nonexistent_world_id_rejected(self) -> None:
        """POST with a world_id that does not exist must be rejected."""
        response = self.client.post(
            "/admin/simulation-lab/reset-world/",
            {
                "world_id": "nonexistent",
                "confirm_world_id": "nonexistent",
                "confirm_text": "确认重置",
                "force_reset": "on",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "仿真世界不存在：nonexistent")

    def test_reset_world_realworld_rejected_even_when_simulation0001_present(self) -> None:
        """Both realworld and simulation0001 exist; POST world_id=realworld
        must be rejected even if confirm matches simulation0001."""
        # Create both worlds
        self._create_simulation_world("simulation0001")
        WorldRegistry.objects.update_or_create(
            world_id="realworld",
            defaults={
                "name": "Real World",
                "world_type": WorldRegistry.WorldType.REAL,
                "database_alias": "default",
                "database_name": "test_control",
                "status": WorldRegistry.Status.ACTIVE,
            },
        )

        # Post world_id=realworld even though confirm matches simulation0001
        response = self.client.post(
            "/admin/simulation-lab/reset-world/",
            {
                "world_id": "realworld",
                "confirm_world_id": "simulation0001",
                "confirm_text": "确认重置",
                "force_reset": "on",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "realworld")
        self.assertContains(response, "只允许对仿真世界执行重置操作")

        # simulation0001 must NOT have been reset
        self.assertTrue(
            WorldRegistry.objects.filter(world_id="simulation0001").exists()
        )

    def test_reset_world_archived_does_not_fallback_to_active(self) -> None:
        """POST world_id of an archived world must not fallback to another active world."""
        # Create an archived simulation world
        WorldRegistry.objects.update_or_create(
            world_id="simulation0001",
            defaults={
                "name": "Simulation 0001",
                "world_type": WorldRegistry.WorldType.SIMULATION,
                "database_alias": "default",
                "database_name": "test_control",
                "status": WorldRegistry.Status.ARCHIVED,
            },
        )
        # Also create active simulation0002
        WorldRegistry.objects.update_or_create(
            world_id="simulation0002",
            defaults={
                "name": "Simulation 0002",
                "world_type": WorldRegistry.WorldType.SIMULATION,
                "database_alias": "default",
                "database_name": "test_control",
                "status": WorldRegistry.Status.ACTIVE,
            },
        )

        response = self.client.post(
            "/admin/simulation-lab/reset-world/",
            {
                "world_id": "simulation0001",
                "confirm_world_id": "simulation0001",
                "confirm_text": "确认重置",
                "force_reset": "on",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "只允许对启用状态的仿真世界重置")

    def test_reset_world_flush_failure_writes_failed_maintenance_log(self) -> None:
        """If flush raises CommandError, a FAILED WorldMaintenanceLog must be written."""
        from unittest.mock import patch
        from django.core.management.base import CommandError as CE
        from worlds.models import WorldMaintenanceLog

        world = self._create_simulation_world()

        with patch("simulation.world_reset.call_command") as mock_flush:
            mock_flush.side_effect = CE("模拟的 flush 失败")

            response = self.client.post(
                "/admin/simulation-lab/reset-world/",
                self._reset_post_data(world, force=True),
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "重置失败")

        log = WorldMaintenanceLog.objects.first()
        self.assertIsNotNone(log)
        self.assertEqual(log.status, WorldMaintenanceLog.StatusChoices.FAILED)
        self.assertIn("flush", log.message)
        self.assertIn("清空目标世界数据库失败", log.message)
        self.assertEqual(log.world_id, world.world_id)
