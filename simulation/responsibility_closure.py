from __future__ import annotations

from typing import Any

from core.models import PlanNode, SimulationFailure


REQUIRED_RESPONSIBILITY_CLOSURES_KEY = "required_responsibility_closures"
RESPONSIBILITY_DOCUMENTS_KEY = "responsibility_documents"


def photovoltaic_responsibility_closure_requirements() -> list[dict[str, object]]:
    return [
        {
            "code": "structure_safety",
            "label": "结构/建筑安全责任文件",
            "examples": ["屋顶荷载复核报告", "结构安全评估报告", "房屋安全鉴定报告", "支架基础安全复核意见", "加固设计文件"],
            "responsible_subjects": ["结构工程师", "建筑设计院", "房屋安全鉴定机构", "检测机构", "结构专业设计单位"],
        },
        {
            "code": "pv_system_design",
            "label": "光伏系统设计责任文件",
            "examples": ["光伏系统设计方案", "组件布置方案", "逆变器配置方案", "设备清单", "发电量测算", "施工图或专业设计文件"],
            "responsible_subjects": ["光伏设计单位", "EPC", "设计顾问", "可承担方案责任的专业主体"],
        },
        {
            "code": "electrical_grid_connection",
            "label": "电气接入与并网责任文件",
            "examples": ["电气接入方案", "一次系统图", "保护配置方案", "防雷接地方案", "并网申请材料", "电网企业并网意见"],
            "responsible_subjects": ["电气设计单位", "并网顾问", "EPC", "电网企业流程责任主体"],
        },
        {
            "code": "construction_safety_quality",
            "label": "施工安全与质量责任主体",
            "examples": ["施工合同", "施工组织方案", "安全施工方案", "高处作业记录", "电气作业记录", "隐蔽工程验收记录"],
            "responsible_subjects": ["施工单位", "安全负责人", "质量负责人", "监理或项目管理责任主体"],
        },
        {
            "code": "acceptance_archive",
            "label": "验收与归档责任安排",
            "examples": ["并网验收资料", "调试记录", "竣工资料", "运维交接资料", "后续巡检和责任边界说明"],
            "responsible_subjects": ["验收责任主体", "运维责任主体", "资料归档责任人", "电网或第三方验收流程"],
        },
    ]


def missing_responsibility_closures_for_node(node: PlanNode) -> list[dict[str, object]]:
    metadata = node.metadata if isinstance(node.metadata, dict) else {}
    requirements = metadata.get(REQUIRED_RESPONSIBILITY_CLOSURES_KEY) or []
    documents = metadata.get(RESPONSIBILITY_DOCUMENTS_KEY) or []
    if not isinstance(requirements, list) or not isinstance(documents, list):
        return []

    missing: list[dict[str, object]] = []
    for requirement in requirements:
        if not isinstance(requirement, dict):
            continue
        code = str(requirement.get("code") or "").strip()
        if not code:
            continue
        matching_documents = [
            document
            for document in documents
            if isinstance(document, dict) and str(document.get("closure_code") or "") == code
        ]
        if any(responsibility_document_is_valid(document) for document in matching_documents):
            continue
        missing.append(
            {
                "code": code,
                "label": str(requirement.get("label") or code),
                "status": "未取得",
                "examples": list(requirement.get("examples") or []),
                "responsible_subjects": list(requirement.get("responsible_subjects") or []),
                "missing_reasons": invalid_document_reasons(matching_documents[0]) if matching_documents else ["未取得可归档、可追责的书面责任文件。"],
            }
        )
    return missing


def responsibility_document_is_valid(document: dict[str, Any]) -> bool:
    required_truthy_fields = [
        "issuer",
        "document_name",
        "signed_or_sealed",
        "clear_conclusion",
        "applicable_to_current_site",
        "applicable_to_current_scale",
    ]
    if not all(bool(document.get(field)) for field in required_truthy_fields):
        return False
    if document.get("professional_evaluation_only") or document.get("oral_opinion_only"):
        return False
    restrictions = document.get("restrictions") or document.get("limitations") or []
    if restrictions and not document.get("restrictions_converted_to_constraints"):
        return False
    return True


def invalid_document_reasons(document: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    checks = [
        ("issuer", "缺少可追责出具主体。"),
        ("document_name", "缺少文件名称。"),
        ("signed_or_sealed", "缺少签字、盖章或合同责任约束。"),
        ("clear_conclusion", "缺少明确结论。"),
        ("applicable_to_current_site", "未明确适用于当前场地。"),
        ("applicable_to_current_scale", "未明确适用于当前光伏规模。"),
    ]
    for field, message in checks:
        if not document.get(field):
            reasons.append(message)
    if document.get("professional_evaluation_only"):
        reasons.append("只有专业人员评估通过，缺少可归档责任文件。")
    if document.get("oral_opinion_only"):
        reasons.append("只有口头判断，不能作为通过条件。")
    restrictions = document.get("restrictions") or document.get("limitations") or []
    if restrictions and not document.get("restrictions_converted_to_constraints"):
        reasons.append("文件限制条件尚未转化为后续施工约束。")
    return reasons or ["文件不满足责任闭环要求。"]


def responsibility_closure_failure_for_node(node: PlanNode, missing: list[dict[str, object]]) -> dict[str, object]:
    missing_labels = [str(item["label"]) for item in missing]
    cannot_continue_reasons = [
        "没有机构或责任人对屋顶/场地承载能力出具书面结论。",
        "没有机构对并网接入、电气保护、防雷接地承担设计责任。",
        "没有施工单位对施工质量和安全承担责任。",
        "现有判断如果只是技能或经验判断，无法在现实中追责。",
    ]
    recommended_actions = [
        "租场地前先做并网预筛。",
        "租场地前或附条件租赁阶段取得结构/建筑安全判断。",
        "不接受成员自评、顾问口头判断、已有专业人员评估通过作为通过条件。",
        "必须以可归档、可追责、可作为决策依据的书面文件作为通过依据。",
    ]
    return {
        "failure_type": SimulationFailure.FailureType.RESPONSIBILITY_CLOSURE_MISSING,
        "title": f"{node.code} {node.title} 责任闭环缺失",
        "description": (
            f"{node.code} {node.title} 进入采购、施工、调试或并网前，缺少关键责任闭环："
            f"{'、'.join(missing_labels)}。"
        ),
        "metadata": {
            "missing_responsibility_closures": missing,
            "cannot_continue_reasons": cannot_continue_reasons,
            "recommended_actions": recommended_actions,
            "low_cost_boundary": {
                "community_allowed": ["场地清理", "资料整理", "询价比价", "搬运", "看护", "巡检记录", "低风险辅助施工"],
                "community_not_allowed": ["结构安全判断", "电气接入设计", "并网调试", "防雷接地设计", "施工安全责任主体", "口头经验替代签字盖章文件"],
            },
        },
    }
