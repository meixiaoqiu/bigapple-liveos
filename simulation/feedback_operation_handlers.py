"""Failure-specific plan-change operation builders."""

from __future__ import annotations

from decimal import Decimal

from core.models import PlanChangeOperation, PlanDependency, PlanNode, PlanRequirement, PlanRevisionProposal

from .feedback_suggestions import plan_node_payload_for_preparation
from .world_snapshot import decimal_from_metadata


def skill_shortage_operations(proposal: PlanRevisionProposal) -> list[dict[str, object]]:
    node = proposal.plan_node
    failure = proposal.source_failure
    metadata = failure.metadata
    missing_skills = list(metadata.get("missing_skills", []))
    prep_node = plan_node_payload_for_preparation(
        node=node,
        suffix="SKILL",
        title=f"补齐{node.title}所需技能",
        duration_days=14,
        cost=Decimal("300000.00"),
    )
    prep_node["node_type"] = PlanNode.NodeType.RECRUITMENT
    prep_node["required_skills"] = ["招募", "培训", "外包协调"]
    prep_node["completion_criteria"] = [
        f"确认具备 {', '.join(missing_skills)} 能力的负责人或外部团队。",
        "形成施工、验收和运维责任清单。",
    ]
    return [
        {
            "operation_type": PlanChangeOperation.OperationType.ADD_NODE,
            "target_model": "PlanNode",
            "target_id": "",
            "target_field": "",
            "old_value": {},
            "new_value": prep_node,
            "rationale": failure.description,
            "is_required": True,
        },
        {
            "operation_type": PlanChangeOperation.OperationType.ADD_DEPENDENCY,
            "target_model": "PlanDependency",
            "target_id": "",
            "target_field": "",
            "old_value": {},
            "new_value": {
                "revision_id": node.revision_id,
                "node_id": node.node_id,
                "depends_on_code": prep_node["code"],
                "dependency_type": PlanDependency.DependencyType.FINISH_TO_START,
                "description": f"{node.code} 启动前必须补齐关键技能：{', '.join(missing_skills)}。",
            },
            "rationale": failure.description,
            "is_required": True,
        },
        {
            "operation_type": PlanChangeOperation.OperationType.ADD_REQUIREMENT,
            "target_model": "PlanRequirement",
            "target_id": "",
            "target_field": "",
            "old_value": {},
            "new_value": {
                "node_id": node.node_id,
                "requirement_type": PlanRequirement.RequirementType.SKILL,
                "name": "关键技能缺口",
                "quantity": len(missing_skills),
                "unit": "项",
                "unit_cost": "0.00",
                "total_cost_estimate": "0.00",
                "is_must": True,
                "notes": f"模拟失败显示当前成员技能画像缺少：{', '.join(missing_skills)}。",
                "metadata": {"missing_skills": missing_skills},
            },
            "rationale": failure.description,
            "is_required": True,
        },
    ]


def responsibility_closure_operations(proposal: PlanRevisionProposal) -> list[dict[str, object]]:
    node = proposal.plan_node
    failure = proposal.source_failure
    missing_closures = list(failure.metadata.get("missing_responsibility_closures", []))
    closure_labels = [str(item.get("label") or item.get("code")) for item in missing_closures if isinstance(item, dict)]
    node_specs = [
        (
            "GRID-PRESCREEN",
            "并网预筛与接入风险判断",
            "在正式租赁前形成并网预判断，识别接入容量、接入距离、消纳、增容成本和批复风险。",
            ["形成可归档的并网预筛记录。", "明确不宜先租赁再碰运气并网。"],
        ),
        (
            "LEASE-REVIEW",
            "场地合法性与附条件租赁审查",
            "确认产权、用途、租期、建设许可、施工运维边界，并优先采用附条件租赁。",
            ["租赁协议包含并网、结构、安全或审批失败时的退出条件。", "明确施工和运维边界。"],
        ),
        (
            "STRUCTURE-DOC",
            "结构/建筑安全责任文件取得",
            "取得结构或建筑安全方面的书面责任文件，不能用口头判断或成员自评替代。",
            ["取得签字盖章或合同责任约束下的结构/建筑安全结论。", "限制条件已转化为后续施工约束。"],
        ),
        (
            "PV-DESIGN-DOC",
            "光伏系统设计责任文件取得",
            "取得光伏系统设计方案、组件布置、逆变器配置、设备清单和发电量测算等责任文件。",
            ["设计文件适用于当前场地和 0.5MW 规模。", "明确方案责任主体。"],
        ),
        (
            "GRID-DOC",
            "电气接入与并网责任文件取得",
            "取得电气接入、一次系统、保护配置、防雷接地和并网流程责任文件。",
            ["明确电气和并网责任主体。", "并网流程资料可归档追溯。"],
        ),
        (
            "CONSTRUCTION-QA",
            "施工安全与质量责任主体确认",
            "确认施工合同、施工组织方案、安全施工方案和质量验收记录责任主体。",
            ["施工单位或责任主体对安全和质量承担责任。", "社区成员只承担低风险辅助工作。"],
        ),
        (
            "ACCEPTANCE-ARCHIVE",
            "验收、调试、归档责任安排",
            "确认并网验收、调试、竣工资料、运维交接和后续巡检责任边界。",
            ["验收和归档资料责任明确。", "运维交接和巡检边界可追溯。"],
        ),
    ]
    operations: list[dict[str, object]] = []
    for suffix, title, description, criteria in node_specs:
        prep_node = plan_node_payload_for_preparation(
            node=node,
            suffix=suffix,
            title=title,
            duration_days=7,
            cost=Decimal("50000.00"),
        )
        prep_node["node_type"] = PlanNode.NodeType.WORK_PACKAGE
        prep_node["description"] = description
        prep_node["required_skills"] = ["业主方管理", "资料整理", "外部专业协作"]
        prep_node["completion_criteria"] = criteria
        prep_node["metadata"] = {
            "source": "simulation_responsibility_closure",
            "blocks_node_id": node.node_id,
            "missing_responsibility_closures": closure_labels,
        }
        operations.extend(
            [
                {
                    "operation_type": PlanChangeOperation.OperationType.ADD_NODE,
                    "target_model": "PlanNode",
                    "target_id": "",
                    "target_field": "",
                    "old_value": {},
                    "new_value": prep_node,
                    "rationale": failure.description,
                    "is_required": True,
                    "metadata": {"responsibility_closure": True},
                },
                {
                    "operation_type": PlanChangeOperation.OperationType.ADD_DEPENDENCY,
                    "target_model": "PlanDependency",
                    "target_id": "",
                    "target_field": "",
                    "old_value": {},
                    "new_value": {
                        "revision_id": node.revision_id,
                        "node_id": node.node_id,
                        "depends_on_code": prep_node["code"],
                        "dependency_type": PlanDependency.DependencyType.FINISH_TO_START,
                        "description": f"{node.code} 启动前必须完成：{title}。",
                    },
                    "rationale": failure.description,
                    "is_required": True,
                    "metadata": {"responsibility_closure": True},
                },
            ]
        )
    for missing in missing_closures:
        if not isinstance(missing, dict):
            continue
        operations.append(
            {
                "operation_type": PlanChangeOperation.OperationType.ADD_REQUIREMENT,
                "target_model": "PlanRequirement",
                "target_id": "",
                "target_field": "",
                "old_value": {},
                "new_value": {
                    "node_id": node.node_id,
                    "requirement_type": PlanRequirement.RequirementType.PERMIT,
                    "name": missing.get("label") or missing.get("code"),
                    "quantity": 1,
                    "unit": "份",
                    "unit_cost": "0.00",
                    "total_cost_estimate": "0.00",
                    "is_must": True,
                    "notes": "必须取得可归档、可追责、可作为决策依据的书面责任文件。",
                    "metadata": {"responsibility_closure_code": missing.get("code"), "missing_reasons": missing.get("missing_reasons", [])},
                },
                "rationale": failure.description,
                "is_required": True,
                "metadata": {"responsibility_closure": True},
            }
        )
    return operations


def budget_unrealistic_operations(proposal: PlanRevisionProposal) -> list[dict[str, object]]:
    node = proposal.plan_node
    failure = proposal.source_failure
    metadata = failure.metadata
    shortfall = decimal_from_metadata(metadata.get("budget_shortfall"), default="0")
    funding_node = plan_node_payload_for_preparation(
        node=node,
        suffix="FUNDING",
        title=f"补足{node.title}启动预算",
        duration_days=10,
        cost=Decimal("0.00"),
    )
    funding_node["node_type"] = PlanNode.NodeType.OPERATIONS
    funding_node["completion_criteria"] = [f"确认至少 {shortfall} 元追加预算已经到账或锁定。"]
    return [
        {
            "operation_type": PlanChangeOperation.OperationType.ADD_NODE,
            "target_model": "PlanNode",
            "target_id": "",
            "target_field": "",
            "old_value": {},
            "new_value": funding_node,
            "rationale": failure.description,
            "is_required": True,
        },
        {
            "operation_type": PlanChangeOperation.OperationType.ADD_REQUIREMENT,
            "target_model": "PlanRequirement",
            "target_id": "",
            "target_field": "",
            "old_value": {},
            "new_value": {
                "node_id": node.node_id,
                "requirement_type": PlanRequirement.RequirementType.BUDGET,
                "name": "追加预算缺口",
                "quantity": str(shortfall),
                "unit": "元",
                "unit_cost": "1.00",
                "total_cost_estimate": str(shortfall),
                "is_must": True,
                "notes": "自动模拟发现本节点启动时预算不足。",
                "metadata": {"budget_shortfall": str(shortfall)},
            },
            "rationale": failure.description,
            "is_required": True,
        },
    ]


def labor_shortage_operations(proposal: PlanRevisionProposal) -> list[dict[str, object]]:
    node = proposal.plan_node
    failure = proposal.source_failure
    recommended_duration = int(proposal.suggested_changes.get("recommended_duration_days", node.planned_duration_days * 2))
    return [
        {
            "operation_type": PlanChangeOperation.OperationType.UPDATE_NODE_FIELD,
            "target_model": "PlanNode",
            "target_id": node.node_id,
            "target_field": "planned_duration_days",
            "old_value": {"value": node.planned_duration_days},
            "new_value": {"value": recommended_duration},
            "rationale": failure.description,
            "is_required": True,
        },
        {
            "operation_type": PlanChangeOperation.OperationType.ADD_PREPARATION,
            "target_model": "PlanNode",
            "target_id": "",
            "target_field": "",
            "old_value": {},
            "new_value": plan_node_payload_for_preparation(
                node=node,
                suffix="LABOR",
                title=f"补齐{node.title}执行人力",
                duration_days=7,
                cost=Decimal("120000.00"),
            ),
            "rationale": failure.description,
            "is_required": True,
        },
    ]


def resource_shortage_operations(proposal: PlanRevisionProposal) -> list[dict[str, object]]:
    node = proposal.plan_node
    failure = proposal.source_failure
    shortages = failure.metadata.get("resource_shortages", [])
    return [
        {
            "operation_type": PlanChangeOperation.OperationType.ADD_REQUIREMENT,
            "target_model": "PlanRequirement",
            "target_id": "",
            "target_field": "",
            "old_value": {},
            "new_value": {
                "node_id": node.node_id,
                "requirement_type": PlanRequirement.RequirementType.MATERIAL,
                "name": "补齐短缺资源",
                "quantity": len(shortages),
                "unit": "类",
                "unit_cost": "0.00",
                "total_cost_estimate": "0.00",
                "is_must": True,
                "notes": "自动模拟发现节点启动前存在资源短缺。",
                "metadata": {"resource_shortages": shortages},
            },
            "rationale": failure.description,
            "is_required": True,
        }
    ]


def personnel_issue_operations(proposal: PlanRevisionProposal) -> list[dict[str, object]]:
    failure = proposal.source_failure
    metadata = failure.metadata
    return [
        {
            "operation_type": PlanChangeOperation.OperationType.REDUCE_ADMISSION,
            "target_model": "PlanRevision",
            "target_id": proposal.plan_revision_id,
            "target_field": "capacity_policy",
            "old_value": {},
            "new_value": {
                "policy": "暂停新增接纳，直到平均疲劳值低于 70。",
                "average_fatigue": metadata.get("average_fatigue"),
            },
            "rationale": failure.description,
            "is_required": True,
        }
    ]


def dependency_unmet_operations(proposal: PlanRevisionProposal) -> list[dict[str, object]]:
    node = proposal.plan_node
    failure = proposal.source_failure
    return [
        {
            "operation_type": PlanChangeOperation.OperationType.NOTE,
            "target_model": "PlanNode",
            "target_id": node.node_id,
            "target_field": "",
            "old_value": {},
            "new_value": {
                "revision_id": node.revision_id,
                "node_id": node.node_id,
                "unmet_dependencies": failure.metadata.get("unmet_dependencies", []),
                "note": "自动模拟发现已有前置依赖尚未满足；需要人工判断是否补充新的结构化依赖。",
            },
            "rationale": failure.description,
            "is_required": False,
        }
    ]
