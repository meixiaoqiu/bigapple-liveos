"""Generate simulation failure proposal types and suggested changes."""

from __future__ import annotations

from decimal import Decimal

from core.models import PlanNode, PlanRevisionProposal, SimulationFailure


def proposal_type_for_failure(failure_type: str) -> str:
    mapping = {
        SimulationFailure.FailureType.BUDGET_UNREALISTIC: PlanRevisionProposal.ProposalType.ADJUST_BUDGET,
        SimulationFailure.FailureType.LABOR_SHORTAGE: PlanRevisionProposal.ProposalType.ADJUST_DURATION,
        SimulationFailure.FailureType.SKILL_SHORTAGE: PlanRevisionProposal.ProposalType.ADD_REQUIREMENT,
        SimulationFailure.FailureType.RESPONSIBILITY_CLOSURE_MISSING: PlanRevisionProposal.ProposalType.ADD_REQUIREMENT,
        SimulationFailure.FailureType.RESOURCE_SHORTAGE: PlanRevisionProposal.ProposalType.ADD_REQUIREMENT,
        SimulationFailure.FailureType.DEPENDENCY_UNMET: PlanRevisionProposal.ProposalType.ADD_DEPENDENCY,
        SimulationFailure.FailureType.PERSONNEL_ISSUE: PlanRevisionProposal.ProposalType.REDUCE_ADMISSION,
    }
    return mapping.get(failure_type, PlanRevisionProposal.ProposalType.ADD_NODE)


def suggested_changes_for_failure(*, node: PlanNode, failure_type: str, metadata: dict[str, object]) -> dict[str, object]:
    if failure_type == SimulationFailure.FailureType.BUDGET_UNREALISTIC:
        shortfall = metadata.get("budget_shortfall", "0")
        return {
            "node_id": node.node_id,
            "change": "在该节点启动前补足预算，或拆分为更小的分期节点。",
            "budget_shortfall": shortfall,
            "recommended_extra_budget": shortfall,
            "recommended_predecessor_node": f"{node.code}-FUNDING",
        }
    if failure_type == SimulationFailure.FailureType.SKILL_SHORTAGE:
        missing_skills = metadata.get("missing_skills", [])
        return {
            "node_id": node.node_id,
            "change": "补充刚性技能需求，并在本节点前增加招募、培训或外包节点。",
            "missing_skills": missing_skills,
            "recommended_predecessor_node": f"{node.code}-SKILL",
        }
    if failure_type == SimulationFailure.FailureType.RESPONSIBILITY_CLOSURE_MISSING:
        missing_closures = metadata.get("missing_responsibility_closures", [])
        return {
            "node_id": node.node_id,
            "change": "增加前置责任闭环节点，补齐光伏一期所需的责任主体和责任文件。",
            "missing_responsibility_closures": missing_closures,
            "cannot_continue_reasons": metadata.get("cannot_continue_reasons", []),
            "recommended_actions": metadata.get("recommended_actions", []),
            "recommended_predecessor_nodes": [
                f"{node.code}-GRID-PRESCREEN",
                f"{node.code}-LEASE-REVIEW",
                f"{node.code}-STRUCTURE-DOC",
                f"{node.code}-PV-DESIGN-DOC",
                f"{node.code}-GRID-DOC",
                f"{node.code}-CONSTRUCTION-QA",
                f"{node.code}-ACCEPTANCE-ARCHIVE",
            ],
        }
    if failure_type == SimulationFailure.FailureType.LABOR_SHORTAGE:
        return {
            "node_id": node.node_id,
            "change": "降低并行施工强度，延长工期，或先补充执行人员。",
            "required_people_min": node.required_people_min,
            "recommended_duration_days": node.planned_duration_days * 2,
        }
    if failure_type == SimulationFailure.FailureType.PERSONNEL_ISSUE:
        return {
            "node_id": node.node_id,
            "change": "降低接纳节奏，增加休整、轮班和心理支持节点。",
            "recommended_capacity_policy": "暂停新增接纳，直到平均疲劳值低于 70。",
        }
    if failure_type == SimulationFailure.FailureType.DEPENDENCY_UNMET:
        return {
            "node_id": node.node_id,
            "change": "补齐前置依赖，避免计划顺序允许未完成条件下启动。",
            "unmet_dependencies": metadata.get("unmet_dependencies", []),
        }
    return {
        "node_id": node.node_id,
        "change": "增加前置准备节点，并拆分风险较高的执行步骤。",
    }


def plan_node_payload_for_preparation(
    *, node: PlanNode, suffix: str, title: str, duration_days: int, cost: Decimal
) -> dict[str, object]:
    """Build a future PlanNode payload used by generated change operations."""

    return {
        "revision_id": node.revision_id,
        "parent_id": node.parent_id,
        "code": f"{node.code}-{suffix}",
        "title": title,
        "node_type": PlanNode.NodeType.WORK_PACKAGE,
        "status": PlanNode.Status.PLANNED,
        "is_required": True,
        "is_expandable": False,
        "allow_simulation_adjustment": True,
        "planned_duration_days": duration_days,
        "estimated_cost_low": str((cost * Decimal("0.80")).quantize(Decimal("0.01"))),
        "estimated_cost_expected": str(cost.quantize(Decimal("0.01"))),
        "estimated_cost_high": str((cost * Decimal("1.25")).quantize(Decimal("0.01"))),
        "required_people_min": min(max(node.required_people_min, 1), 8),
        "required_people_max": min(max(node.required_people_max, 3), 16),
        "required_person_days": str((Decimal(duration_days) * Decimal("4")).quantize(Decimal("0.01"))),
        "required_skills": [],
        "required_resources": [],
        "completion_criteria": [f"{title} 已完成，并形成可验收记录。"],
        "risk_notes": "由自动模拟失败生成的前置准备节点草案，需人工审核后才能进入新计划版本。",
    }
