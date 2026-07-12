"""Project plan demo seed data."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from core.models import (
    PlanCapacityImpact,
    PlanDependency,
    PlanNode,
    PlanRequirement,
    PlanRevision,
    ProjectPlan,
    Ruleset,
)

from .helpers import RULE_VERSION, actor, upsert
from .project_plan_specs import capacity_impact_specs, dependency_specs, plan_node_specs


def seed_project_plan(*, now, mark) -> tuple[Ruleset, PlanRevision, dict[str, PlanNode]]:
    ruleset = mark(
        upsert(
            Ruleset,
            {"ruleset_id": "ruleset-v0_1_0"},
            {
                "version": RULE_VERSION,
                "status": Ruleset.Status.ACTIVE,
                "effective_from": now.date(),
                "effective_to": None,
                "negative_point_floor": {
                    "ordinary_member": -300,
                    "new_member": -100,
                    "high_trust_member": -500,
                    "restricted_member": -50,
                },
                "task_point_rules": [
                    {"task_type": "cooking", "base_points": 30, "role_coefficient": 1.2},
                    {"task_type": "public_cleaning", "base_points": 20, "role_coefficient": 1.0},
                    {"task_type": "warehouse", "base_points": 24, "role_coefficient": 1.1},
                ],
                "created_at": now,
                "created_by": actor("member-admin-0001", "开荒队治理成员"),
                "change_summary": "v0.1 演示规则版本，用于本地后台预览。",
                "metadata": {"seed": True},
            },
        )
    )

    project_plan = mark(
        upsert(
            ProjectPlan,
            {"plan_id": "plan-bigapple001"},
            {
                "name": "bigapple001据点执行计划",
                "status": ProjectPlan.Status.ACTIVE,
                "description": "从人员招募、分批抵达、先遣准备、开会定计划，到基础设施、扩容、新成员接纳和长期空间建设的完整执行计划。",
                "target_location": "bigapple001据点",
                "owner": actor("member-admin-0001", "开荒队治理成员"),
                "created_at": now,
                "updated_at": now,
                "metadata": {
                    "seed": True,
                    "scope": "from_zero_to_full_operation",
                    "planning_principle": "计划是数据库中的可编辑源头，模拟结果只能提出修订建议。",
                },
            },
        )
    )
    plan_revision = mark(
        upsert(
            PlanRevision,
            {"revision_id": "plan-bigapple001-rev-v0_1_0"},
            {
                "plan": project_plan,
                "revision_code": "v0.1.0",
                "status": PlanRevision.Status.PUBLISHED,
                "title": "bigapple001据点执行计划第一版",
                "change_summary": "建立从 0 到 1 再到 100% 的主线执行计划骨架，供观察台、Admin 和后续模拟运行使用。",
                "created_at": now,
                "created_by": actor("member-admin-0001", "开荒队治理成员"),
                "published_at": now,
                "metadata": {"seed": True, "source": "seed_demo"},
            },
        )
    )

    plan_nodes: dict[str, PlanNode] = {}
    for index, spec in enumerate(plan_node_specs(), start=1):
        parent = plan_nodes.get(spec.get("parent", ""))
        cost = Decimal(str(spec.get("cost", 0)))
        node = mark(
            upsert(
                PlanNode,
                {"node_id": f"node-bigapple001-{spec['code'].lower()}"},
                {
                    "revision": plan_revision,
                    "parent": parent,
                    "sequence": index * 10,
                    "code": spec["code"],
                    "title": spec["title"],
                    "node_type": spec["node_type"],
                    "status": spec["status"],
                    "is_required": spec.get("is_required", True),
                    "is_expandable": spec.get("is_expandable", False),
                    "allow_simulation_adjustment": True,
                    "description": spec.get("description", ""),
                    "planned_start_day": spec.get("start_day"),
                    "planned_duration_days": spec.get("duration", 1),
                    "planned_end_day": spec.get("end_day"),
                    "estimated_cost_low": (cost * Decimal("0.80")).quantize(Decimal("0.01")),
                    "estimated_cost_expected": cost,
                    "estimated_cost_high": (cost * Decimal("1.25")).quantize(Decimal("0.01")),
                    "required_people_min": spec.get("people", (0, 0))[0],
                    "required_people_max": spec.get("people", (0, 0))[1],
                    "required_person_days": Decimal(str(spec.get("person_days", 0))),
                    "required_skills": spec.get("skills", []),
                    "required_resources": spec.get("resources", []),
                    "completion_criteria": spec.get("criteria", []),
                    "risk_notes": spec.get("risk_notes", ""),
                    "created_at": now,
                    "updated_at": now,
                    "metadata": {"seed": True, "plan_code": spec["code"], **spec.get("metadata", {})},
                },
            )
        )
        plan_nodes[spec["code"]] = node
        mark(
            upsert(
                PlanRequirement,
                {"requirement_id": f"req-bigapple001-{spec['code'].lower()}-budget"},
                {
                    "node": node,
                    "requirement_type": PlanRequirement.RequirementType.BUDGET,
                    "name": "预算资金",
                    "quantity": cost,
                    "unit": "元",
                    "unit_cost": Decimal("1.00"),
                    "total_cost_estimate": cost,
                    "is_must": True,
                    "notes": "演示估算，后续应拆分为材料、人工、设备和手续。",
                    "metadata": {"seed": True},
                },
            )
        )
        if spec.get("person_days", 0):
            mark(
                upsert(
                    PlanRequirement,
                    {"requirement_id": f"req-bigapple001-{spec['code'].lower()}-labor"},
                    {
                        "node": node,
                        "requirement_type": PlanRequirement.RequirementType.LABOR,
                        "name": "执行人天",
                        "quantity": Decimal(str(spec["person_days"])),
                        "unit": "人天",
                        "unit_cost": Decimal("0.00"),
                        "total_cost_estimate": Decimal("0.00"),
                        "is_must": True,
                        "notes": "用于模拟人力瓶颈和执行进度。",
                        "metadata": {"seed": True},
                    },
                )
            )

    for node_code, depends_on_code, dependency_type, description in dependency_specs():
        mark(
            upsert(
                PlanDependency,
                {"dependency_id": f"dep-bigapple001-{depends_on_code.lower()}-{node_code.lower()}"},
                {
                    "revision": plan_revision,
                    "node": plan_nodes[node_code],
                    "depends_on": plan_nodes[depends_on_code],
                    "dependency_type": dependency_type,
                    "description": description,
                    "metadata": {"seed": True},
                },
            )
        )

    for node_code, impact_type, delta, unit, description in capacity_impact_specs():
        mark(
            upsert(
                PlanCapacityImpact,
                {"impact_id": f"impact-bigapple001-{node_code.lower()}-{impact_type}"},
                {
                    "node": plan_nodes[node_code],
                    "impact_type": impact_type,
                    "delta": Decimal(delta),
                    "unit": unit,
                    "description": description,
                    "metadata": {"seed": True},
                },
            )
        )
    return ruleset, plan_revision, plan_nodes
