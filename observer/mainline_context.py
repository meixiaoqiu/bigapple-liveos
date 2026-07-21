"""Build the "current mainline" display context for the observer dashboard.

Consumes data already queried by ``observer.page_context.observer_context``
and enriches it with stage detection, progress computation and blocker
resolution.
"""

from __future__ import annotations

from typing import Any


def build_mainline_context(raw_data: dict[str, Any]) -> dict[str, Any]:
    """Return a ``mainline`` dict for the theme-facing dashboard context."""

    empty: dict[str, Any] = {
        "plan_title": "",
        "revision_title": "",
        "stage": None,
        "current_nodes": [],
        "next_nodes": [],
        "blockers": [],
        "progress": {"completed": 0, "total": 0, "percent": 0},
        "latest_run": None,
        "proposal_summary": None,
        "primary_task": None,
        "next_action": None,
        "all_nodes": [],
        "stages": [],
        "detail_url": "/dashboard/mainline/",
        "empty": True,
    }

    active_plan = raw_data.get("active_plan")
    active_revision = raw_data.get("active_revision")
    if active_plan is None or active_revision is None:
        return empty

    current_nodes_raw = list(raw_data.get("current_plan_nodes") or [])
    next_nodes_raw = list(raw_data.get("next_plan_nodes") or [])

    # ---- stage detection: first current STAGE node or parent chain ----
    stage_node = _detect_stage(current_nodes_raw, next_nodes_raw)
    stage = _stage_dict(stage_node) if stage_node else None

    # ---- current nodes (top 4, non-stage preferred, scoped to current stage) ----
    current_nodes: list[dict[str, Any]] = []
    stage_children: list[dict[str, Any]] = []    # non-stage nodes of current stage
    other_non_stage: list[dict[str, Any]] = []    # non-stage nodes of other stages
    skipped_stage: dict[str, Any] | None = None   # current stage_node itself

    for node in current_nodes_raw:
        if _is_stage_node(node):
            if stage_node is not None and _is_same_node(node, stage_node):
                skipped_stage = _node_dict(node)
                continue
            # other stage/milestone nodes — never in current_nodes
            continue
        elif stage_node is not None and _node_belongs_to_stage(node, stage_node):
            stage_children.append(_node_dict(node))
        else:
            other_non_stage.append(_node_dict(node))

    # Priority: stage_children → other_non_stage (fallback) → skipped_stage (last)
    for item in stage_children:
        if len(current_nodes) >= 4:
            break
        current_nodes.append(item)
    if len(current_nodes) == 0:
        for item in other_non_stage:
            if len(current_nodes) >= 4:
                break
            current_nodes.append(item)
    if skipped_stage is not None and len(current_nodes) == 0:
        current_nodes.append(skipped_stage)
    stage_current = current_nodes_raw if current_nodes_raw else []

    # ---- next nodes (PLANNED, top 3) ----
    next_nodes = [_node_dict(node) for node in next_nodes_raw[:3]]

    # ---- progress ----
    completed = int(raw_data.get("plan_required_completed") or 0)
    total = int(raw_data.get("plan_required_total") or 0)
    percent = round(completed / total * 100) if total > 0 else 0
    progress = {"completed": completed, "total": total, "percent": percent}

    # ---- blockers ----
    blockers = _resolve_blockers(raw_data, stage_current)

    # ---- latest simulation run ----
    latest_run = _latest_run_dict(raw_data)

    # ---- proposal summary ----
    proposal_summary = _proposal_summary_dict(raw_data)

    # ---- primary task & next action ----
    primary_task = None
    if current_nodes:
        primary_task = current_nodes[0]
    elif stage is not None:
        primary_task = stage
    next_action = next_nodes[0] if next_nodes else None

    # ---- all_nodes & stages (for detail page) ----
    all_plan_nodes = list(raw_data.get("plan_nodes") or [])
    all_nodes = [_node_dict(n) for n in all_plan_nodes]
    stages = _build_stages(all_plan_nodes, stage_node)

    return {
        "plan_title": str(getattr(active_plan, "name", "") or ""),
        "revision_title": str(getattr(active_revision, "title", "") or getattr(active_revision, "revision_code", "") or ""),
        "stage": stage,
        "current_nodes": current_nodes,
        "next_nodes": next_nodes,
        "blockers": blockers,
        "progress": progress,
        "latest_run": latest_run,
        "proposal_summary": proposal_summary,
        "primary_task": primary_task,
        "next_action": next_action,
        "all_nodes": all_nodes,
        "stages": stages,
        "detail_url": "/dashboard/mainline/",
        "empty": False,
    }


# ----------------------------------------------------------------- helpers


def _node_dict(node) -> dict[str, Any]:
    parent = getattr(node, "parent", None)
    completion_criteria = getattr(node, "completion_criteria", None) or []
    if callable(completion_criteria):
        completion_criteria = []
    return {
        "node_id": str(getattr(node, "node_id", "")),
        "parent_id": str(getattr(parent, "node_id", "")) if parent else "",
        "code": str(getattr(node, "code", "")),
        "title": str(getattr(node, "title", "") or "未命名节点"),
        "node_type": str(getattr(node, "node_type", "")),
        "status": str(getattr(node, "status", "")),
        "description": str(getattr(node, "description", "") or ""),
        "planned_duration_days": int(getattr(node, "planned_duration_days", 0) or 0),
        "required_people_min": int(getattr(node, "required_people_min", 0) or 0),
        "required_people_max": int(getattr(node, "required_people_max", 0) or 0),
        "completion_criteria": list(completion_criteria),
        "risk_notes": str(getattr(node, "risk_notes", "") or ""),
        "depth": 0,
    }


def _stage_dict(node) -> dict[str, Any]:
    return {
        "node_id": str(getattr(node, "node_id", "")),
        "code": str(getattr(node, "code", "")),
        "title": str(getattr(node, "title", "") or "当前阶段"),
        "description": str(getattr(node, "description", "") or ""),
    }


def _detect_stage(current_nodes: list, next_nodes: list):
    """Pick the most likely stage node from current nodes or the parent chain.

    1. Return the first STAGE / MILESTONE node in *current_nodes*.
    2. Otherwise, walk the parent chain of each current node and return
       the *nearest* STAGE / MILESTONE ancestor found.
    3. Fall back to *next_nodes* using the same logic.
    """
    result = _first_stage_or_ancestor(current_nodes)
    if result is not None:
        return result
    return _first_stage_or_ancestor(next_nodes)


def _first_stage_or_ancestor(nodes: list):
    """Return first STAGE / MILESTONE in *nodes*, or their nearest stage ancestor."""
    for node in nodes:
        if _is_stage_node(node):
            return node
    for node in nodes:
        ancestor = _nearest_stage_ancestor_node(node)
        if ancestor is not None:
            return ancestor
    return None


def _nearest_stage_ancestor_node(node) -> object | None:
    """Walk the ``parent`` chain upwards and return the first STAGE / MILESTONE ancestor.

    Returns ``None`` if no stage ancestor is found or a cycle is detected.
    """
    seen: set[str] = set()
    current = node
    max_iter = 100
    for _ in range(max_iter):
        parent = getattr(current, "parent", None)
        if parent is None:
            return None
        parent_id = str(getattr(parent, "node_id", ""))
        if not parent_id:
            return None
        if parent_id in seen:
            return None
        seen.add(parent_id)
        if _is_stage_node(parent):
            return parent
        current = parent
    return None


def _is_stage_node(node) -> bool:
    """Return True if *node* is a stage or milestone typed node."""
    return str(getattr(node, "node_type", "")).lower() in {"stage", "milestone"}


def _is_same_node(node_a, node_b) -> bool:
    """Compare two PlanNode instances by node_id."""
    return str(getattr(node_a, "node_id", "")) == str(getattr(node_b, "node_id", ""))


def _node_belongs_to_stage(node, stage_node) -> bool:
    """Return True if *node* belongs to *stage_node* (any ancestor, not just direct parent)."""
    if stage_node is None:
        return False
    if _is_same_node(node, stage_node):
        return True
    return _node_has_ancestor(node, stage_node)


def _node_has_ancestor(node, ancestor_node) -> bool:
    """Walk the ``parent`` chain and return True if *ancestor_node* is found."""
    seen: set[str] = set()
    current = node
    max_iter = 100
    for _ in range(max_iter):
        parent = getattr(current, "parent", None)
        if parent is None:
            return False
        parent_id = str(getattr(parent, "node_id", ""))
        if not parent_id:
            return False
        if parent_id in seen:
            return False
        seen.add(parent_id)
        if _is_same_node(parent, ancestor_node):
            return True
        current = parent
    return False


def _build_stages(all_plan_nodes: list, current_stage_node) -> list[dict[str, Any]]:
    """Group all plan nodes by nearest stage/milestone ancestor, mark current stage.

    Walks parent chain for every non-stage node so that deep hierarchies
    (e.g. stage -> work_package -> task) are all included in the stage's
    children list.  Orphan nodes (no stage ancestor) go into an "未分组节点"
    group.
    """
    if not all_plan_nodes:
        return []

    nodes_by_id: dict[str, Any] = {}
    stage_ids: set[str] = set()
    stage_nodes_ordered: list[Any] = []
    for node in all_plan_nodes:
        nid = str(getattr(node, "node_id", ""))
        nodes_by_id[nid] = node
        if _is_stage_node(node):
            stage_ids.add(nid)
            stage_nodes_ordered.append(node)

    if not stage_ids:
        # No stages: dump all non-stage nodes into "未分组节点"
        orphans = [_node_dict(node) for node in all_plan_nodes if not _is_stage_node(node)]
        if orphans:
            return [{
                "node_id": "",
                "parent_id": "",
                "code": "未分组",
                "title": "未分组节点",
                "node_type": "",
                "status": "",
                "description": "",
                "depth": 0,
                "children": orphans,
                "is_current": False,
            }]
        return []

    result: list[dict[str, Any]] = []
    stage_children: dict[str, list[dict[str, Any]]] = {sid: [] for sid in stage_ids}
    orphans: list[dict[str, Any]] = []

    for node in all_plan_nodes:
        if _is_stage_node(node):
            continue
        node_dict_item = _node_dict(node)
        ancestor_id = _find_nearest_stage_ancestor(node, nodes_by_id, stage_ids)
        if ancestor_id:
            depth = _ancestor_depth(node, nodes_by_id, ancestor_id)
            node_dict_item["depth"] = depth
            stage_children[ancestor_id].append(node_dict_item)
        else:
            orphans.append(node_dict_item)

    for s_node in stage_nodes_ordered:
        s_dict = _node_dict(s_node)
        s_dict["children"] = stage_children.get(s_dict["node_id"], [])
        s_dict["is_current"] = (
            current_stage_node is not None and _is_same_node(s_node, current_stage_node)
        )
        result.append(s_dict)

    if orphans:
        result.append({
            "node_id": "",
            "parent_id": "",
            "code": "未分组",
            "title": "未分组节点",
            "node_type": "",
            "status": "",
            "description": "",
            "depth": 0,
            "children": orphans,
            "is_current": False,
        })

    return result


def _find_nearest_stage_ancestor(node, nodes_by_id: dict[str, Any], stage_ids: set[str]) -> str:
    """Walk parent chain to find the nearest stage/milestone ancestor node_id.

    Returns empty string if no stage ancestor found (orphan).
    """
    seen: set[str] = set()
    current = node
    max_iter = 100  # safety limit
    for _ in range(max_iter):
        parent = getattr(current, "parent", None)
        if parent is None:
            return ""
        parent_id = str(getattr(parent, "node_id", ""))
        if not parent_id:
            return ""
        if parent_id in seen:
            return ""  # cycle detected
        seen.add(parent_id)
        if parent_id in stage_ids:
            return parent_id
        current = nodes_by_id.get(parent_id)
        if current is None:
            return ""
    return ""


def _ancestor_depth(node, nodes_by_id: dict[str, Any], ancestor_id: str) -> int:
    """Count steps from *node* up to *ancestor_id* (exclusive of ancestor).

    Direct child of stage returns 1, grandchild returns 2, etc.
    """
    depth = 0
    seen: set[str] = set()
    current = node
    max_iter = 100
    for _ in range(max_iter):
        parent = getattr(current, "parent", None)
        if parent is None:
            break
        parent_id = str(getattr(parent, "node_id", ""))
        if not parent_id or parent_id in seen:
            break
        seen.add(parent_id)
        depth += 1
        if parent_id == ancestor_id:
            return depth
        current = nodes_by_id.get(parent_id)
        if current is None:
            break
    return depth


def _resolve_blockers(raw_data: dict[str, Any], stage_current: list) -> list[dict[str, Any]]:
    """Resolve blockers in priority: SimulationFailure > Turn metadata blockers > PlanRevisionProposal > node risk_notes."""

    blockers: list[dict[str, Any]] = []

    # 1. SimulationFailures (latest run)
    failures = list(raw_data.get("latest_run_failures") or [])
    for f in failures[:4]:
        node = getattr(f, "plan_node", None)
        node_label = f"{getattr(node, 'code', '')} {getattr(node, 'title', '')}".strip()
        blockers.append({
            "source": "simulation_failure",
            "title": str(getattr(f, "title", "") or getattr(f, "description", "") or "仿真失败"),
            "node": node_label or str(getattr(f, "plan_node_id", "")),
            "description": str(getattr(f, "description", "") or ""),
            "failure_type": str(getattr(f, "failure_type", "") or ""),
        })

    if blockers:
        return blockers

    # 2. Turn metadata blockers
    latest_turn = raw_data.get("latest_run_turn")
    if latest_turn is not None:
        metadata = getattr(latest_turn, "metadata", {}) or {}
        if isinstance(metadata, dict):
            turn_blockers = list(metadata.get("blockers") or metadata.get("current_blockers") or [])
            for b in turn_blockers[:4]:
                if isinstance(b, dict):
                    blockers.append({
                        "source": "simulation_turn",
                        "title": str(b.get("title") or b.get("description") or "当前阻塞"),
                        "node": str(b.get("node") or ""),
                        "description": str(b.get("description") or ""),
                        "failure_type": "",
                    })
                elif isinstance(b, str):
                    blockers.append({
                        "source": "simulation_turn",
                        "title": b,
                        "node": "",
                        "description": "",
                        "failure_type": "",
                    })

    if blockers:
        return blockers

    # 3. PlanRevisionProposal entries
    proposals = list(raw_data.get("latest_run_proposals") or [])
    for p in proposals[:4]:
        node = getattr(p, "plan_node", None)
        node_label = f"{getattr(node, 'code', '')} {getattr(node, 'title', '')}".strip()
        blockers.append({
            "source": "plan_revision_proposal",
            "title": str(getattr(p, "title", "") or getattr(p, "proposal_id", "") or "计划修订建议"),
            "node": node_label or "",
            "description": str(getattr(p, "change_summary", "") or getattr(p, "description", "") or ""),
            "failure_type": "",
        })

    if blockers:
        return blockers

    # 4. Node-level risk_notes from current / next nodes
    for node in stage_current[:3]:
        risk = str(getattr(node, "risk_notes", "") or "").strip()
        if risk:
            blockers.append({
                "source": "risk_note",
                "title": risk,
                "node": f"{getattr(node, 'code', '')} {getattr(node, 'title', '')}".strip(),
                "description": "",
                "failure_type": "",
            })

    if not blockers:
        blockers.append({
            "source": "none",
            "title": "暂无阻塞",
            "node": "",
            "description": "",
            "failure_type": "",
        })

    # Deduplicate
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for b in blockers:
        key = f"{b['source']}:{b['title']}:{b['node']}"
        if key not in seen:
            seen.add(key)
            unique.append(b)
    return unique


def _latest_run_dict(raw_data: dict[str, Any]) -> dict[str, Any] | None:
    run = raw_data.get("latest_simulation_run")
    if run is None:
        return None
    status_value = str(getattr(run, "status", "") or "")
    return {
        "run_id": str(getattr(run, "run_id", "")),
        "status": status_value,
        "status_display": {
            "running": "运行中",
            "completed": "已完成",
            "failed": "失败",
            "aborted": "已中止",
        }.get(status_value, status_value),
        "current_day": int(getattr(run, "current_day", 0) or 0),
        "failure_summary": str(getattr(run, "failure_summary", "") or ""),
    }


def _proposal_summary_dict(raw_data: dict[str, Any]) -> dict[str, Any] | None:
    proposals = list(raw_data.get("latest_run_proposals") or [])
    change_sets = list(raw_data.get("latest_run_change_sets") or [])
    if not proposals and not change_sets:
        return None
    return {
        "proposal_count": len(proposals),
        "change_set_count": len(change_sets),
        "first_title": str(getattr(proposals[0], "title", "") or getattr(proposals[0], "proposal_id", "") or "") if proposals else "",
    }
