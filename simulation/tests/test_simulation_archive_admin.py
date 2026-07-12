from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib import admin
from django.test import TestCase
from django.utils import timezone

from core.models import SimulationSnapshot, SimulationSnapshotItem
from simulation.admin_archives import SimulationSnapshotItemAdmin


class SimulationSnapshotAdminDisplayTests(TestCase):
    def create_snapshot_item(self, *, archive_path: str) -> SimulationSnapshotItem:
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
        snapshot = SimulationSnapshot.objects.create(
            snapshot_id="snapshot-admin-display",
            title="测试快照",
            source_world_id="simulation0001",
            source_world_type="simulation",
            source_database_alias="default",
            source_database_name="test",
            source_run_id="sim-run-test",
            plan_revision_id="rev-test",
            run_status="failed",
            failure_type="responsibility_closure_missing",
            failure_title="责任闭环缺失",
            snapshot_schema_version=1,
            status=SimulationSnapshot.Status.ARCHIVED,
            raw_archive_path=archive_path,
            raw_archive_hash="0" * 64,
            report_path="",
            raw_table_counts={},
            normalized_summary={"counts": {"node_states": 1}},
            code_version="test",
            archived_at=timezone.now(),
            metadata={},
        )
        return SimulationSnapshotItem.objects.create(
            item_id="snapshot-admin-display:item-000101",
            snapshot=snapshot,
            item_type=SimulationSnapshotItem.ItemType.NODE_STATE,
            source_model="core.PlanNodeRunState",
            source_pk="state-c3",
            title="node-bigapple001-c3",
            summary="失败",
            sort_order=101,
            payload_json={"fields": {"plan_node": "node-bigapple001-c3"}},
        )

    def test_admin_displays_human_readable_snapshot_item_fields(self) -> None:
        with TemporaryDirectory() as archive_path:
            item = self.create_snapshot_item(archive_path=archive_path)
            model_admin = SimulationSnapshotItemAdmin(SimulationSnapshotItem, admin.site)

            self.assertEqual(model_admin.display_source_model(item), "计划节点状态")
            self.assertEqual(model_admin.display_title(item), "C3 光伏一期 0.5MW")
