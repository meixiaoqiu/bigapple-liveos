"""Display helpers for archived simulation snapshot indexes."""

from __future__ import annotations

import json
from pathlib import Path

from core.models import SimulationSnapshot, SimulationSnapshotItem


SOURCE_MODEL_LABELS = {
    "core.Event": "观察事件",
    "core.PlanChangeOperation": "计划变更操作",
    "core.PlanChangeSet": "计划变更集",
    "core.PlanNodeRunState": "计划节点状态",
    "core.PlanRevisionProposal": "计划修订建议",
    "core.SimulationFailure": "失败记录",
    "core.SimulationRun": "仿真运行",
    "core.SimulationTurn": "推演日志",
}


def source_model_label(source_model: str) -> str:
    return SOURCE_MODEL_LABELS.get(source_model, source_model)


def snapshot_item_title(item: SimulationSnapshotItem, *, node_title_map: dict[str, str] | None = None) -> str:
    node_title_map = node_title_map or {}
    payload = item.payload_json if isinstance(item.payload_json, dict) else {}
    display = payload.get("display") if isinstance(payload.get("display"), dict) else {}
    plan_node_label = str(display.get("plan_node_label") or "")
    if plan_node_label:
        return plan_node_label

    if item.source_model == "core.PlanNodeRunState":
        fields = payload.get("fields") if isinstance(payload.get("fields"), dict) else {}
        plan_node_id = str(fields.get("plan_node") or item.title or "")
        return node_title_map.get(plan_node_id) or item.title

    return item.title


def raw_plan_node_title_map(snapshot: SimulationSnapshot) -> dict[str, str]:
    raw_path = Path(snapshot.raw_archive_path) / "raw" / "core.PlanNode.json"
    if not raw_path.is_file():
        return {}
    try:
        rows = json.loads(raw_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(rows, list):
        return {}

    titles: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        fields = row.get("fields") if isinstance(row.get("fields"), dict) else {}
        code = str(fields.get("code") or "")
        title = str(fields.get("title") or "")
        label = f"{code} {title}".strip()
        if row.get("pk") and label:
            titles[str(row["pk"])] = label
    return titles
