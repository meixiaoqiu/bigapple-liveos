"""Plan-node feasibility checks for simulation runs."""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum

from core.models import PlanNode, PlanNodeRunState, Resource, SimulationFailure, SimulationRun

from .responsibility_closure import missing_responsibility_closures_for_node, responsibility_closure_failure_for_node
from .world_snapshot import decimal_from_metadata, normalize_skill


def unmet_dependency_titles(*, run: SimulationRun, node: PlanNode) -> list[str]:
    unmet: list[str] = []
    dependencies = node.dependencies.select_related("depends_on").order_by("dependency_id")
    for dependency in dependencies:
        dependency_state = PlanNodeRunState.objects.filter(run=run, plan_node=dependency.depends_on).first()
        if dependency_state is None or dependency_state.status != PlanNodeRunState.Status.COMPLETED:
            unmet.append(f"{dependency.depends_on.code} {dependency.depends_on.title}")
    return unmet


def resource_shortages_for_node(node: PlanNode) -> list[dict[str, str]]:
    shortages: list[dict[str, str]] = []
    for requirement in node.required_resources:
        if not isinstance(requirement, dict):
            continue
        resource_type = requirement.get("resource_type") or requirement.get("type")
        if not resource_type:
            continue
        needed = decimal_from_metadata(requirement.get("quantity"), default="0")
        available = (
            Resource.objects.filter(resource_type=resource_type).aggregate(total=Sum("current_stock"))["total"]
            or Decimal("0")
        )
        if needed > Decimal(available):
            shortages.append(
                {
                    "resource_type": str(resource_type),
                    "needed": str(needed),
                    "available": str(available),
                }
            )
    return shortages


def feasibility_failure_for_node(run: SimulationRun, node: PlanNode) -> dict[str, object] | None:
    """Return failure metadata when the next planned node cannot be executed."""

    unmet_dependencies = unmet_dependency_titles(run=run, node=node)
    if unmet_dependencies:
        return {
            "failure_type": SimulationFailure.FailureType.DEPENDENCY_UNMET,
            "title": f"{node.code} {node.title} 前置条件未满足",
            "description": f"节点 {node.code} 不能启动，因为前置节点尚未完成：{'、'.join(unmet_dependencies)}。",
            "metadata": {"unmet_dependencies": unmet_dependencies},
        }

    available_people = int(run.metadata.get("available_people") or 0)
    if node.required_people_min > available_people:
        return {
            "failure_type": SimulationFailure.FailureType.LABOR_SHORTAGE,
            "title": f"{node.code} {node.title} 人力不足",
            "description": f"节点最低需要 {node.required_people_min} 人，但当前可用于模拟的正式成员只有 {available_people} 人。",
            "metadata": {"required_people_min": node.required_people_min, "available_people": available_people},
        }

    fatigue = decimal_from_metadata(run.metadata.get("average_fatigue"), default="0")
    if fatigue >= Decimal("85") and node.required_people_min >= max(1, available_people // 3):
        return {
            "failure_type": SimulationFailure.FailureType.PERSONNEL_ISSUE,
            "title": f"{node.code} {node.title} 人员状态不可承受",
            "description": f"当前平均疲劳值为 {fatigue}，继续推进该节点会显著增加退出和冲突风险。",
            "metadata": {"average_fatigue": str(fatigue), "threshold": "85"},
        }

    remaining_budget = decimal_from_metadata(run.metadata.get("remaining_budget"), default="0")
    if node.estimated_cost_expected > remaining_budget:
        shortfall = node.estimated_cost_expected - remaining_budget
        return {
            "failure_type": SimulationFailure.FailureType.BUDGET_UNREALISTIC,
            "title": f"{node.code} {node.title} 预算不足",
            "description": f"节点预计需要 {node.estimated_cost_expected} 元，但本次模拟剩余预算只有 {remaining_budget} 元，缺口 {shortfall} 元。",
            "metadata": {
                "estimated_cost_expected": str(node.estimated_cost_expected),
                "remaining_budget": str(remaining_budget),
                "budget_shortfall": str(shortfall),
            },
        }

    shortages = resource_shortages_for_node(node)
    if shortages:
        return {
            "failure_type": SimulationFailure.FailureType.RESOURCE_SHORTAGE,
            "title": f"{node.code} {node.title} 资源不足",
            "description": f"节点所需资源不足：{shortages[0]['resource_type']} 需要 {shortages[0]['needed']}，当前只有 {shortages[0]['available']}。",
            "metadata": {"resource_shortages": shortages},
        }

    missing_responsibility_closures = missing_responsibility_closures_for_node(node)
    if missing_responsibility_closures:
        return responsibility_closure_failure_for_node(node, missing_responsibility_closures)

    available_skills = set(run.metadata.get("available_skills") or [])
    missing_skills = [skill for skill in node.required_skills if normalize_skill(skill) not in available_skills]
    if missing_skills:
        return {
            "failure_type": SimulationFailure.FailureType.SKILL_SHORTAGE,
            "title": f"{node.code} {node.title} 技能缺口",
            "description": f"节点需要 {', '.join(missing_skills)}，但当前成员技能画像中没有这些能力。",
            "metadata": {"missing_skills": missing_skills, "available_skills": sorted(available_skills)},
        }

    return None
