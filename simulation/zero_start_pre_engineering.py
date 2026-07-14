"""Zero-start simulation: pre-engineering state computation.

Computes the pre-engineering phase state (candidate sites, milestones,
document signers) that follows after the startup gate is satisfied.
Does NOT import ``zero_start.py``.
"""

from __future__ import annotations

from core.models import PartnerApplication, SimulationRun
from .projections import partner_snapshot
from .zero_start_observations import pre_engineering_blockers


PRE_ENGINEERING_SITE_CANDIDATES: tuple[dict[str, object], ...] = (
    {
        "code": "site-roof-a",
        "name": "C3-A 候选屋顶",
        "site_type": "roof",
        "area_sqm": 5200,
        "property_status": "产权资料可核验，业主接受附条件合作",
        "nearby_grid_condition": "低压接入点近，但需确认容量和消纳",
        "estimated_capacity_kw": 520,
        "estimated_monthly_rent": "18000.00",
        "risk_points": ["屋顶荷载必须复核", "租赁协议必须绑定并网和结构条件"],
        "grid_prescreen": "conditional_pass",
        "legal_review": "conditional_pass",
    },
    {
        "code": "site-roof-b",
        "name": "C3-B 老厂房屋顶",
        "site_type": "roof",
        "area_sqm": 4300,
        "property_status": "产权链条较长，需要补充授权文件",
        "nearby_grid_condition": "接入点距离适中，但增容成本不确定",
        "estimated_capacity_kw": 390,
        "estimated_monthly_rent": "12000.00",
        "risk_points": ["产权授权不清", "屋面年限较长"],
        "grid_prescreen": "needs_follow_up",
        "legal_review": "blocked",
    },
    {
        "code": "site-ground-c",
        "name": "C3-C 空置地块",
        "site_type": "ground",
        "area_sqm": 8600,
        "property_status": "用途与建设边界不清",
        "nearby_grid_condition": "接入点远，线缆和增容成本高",
        "estimated_capacity_kw": 600,
        "estimated_monthly_rent": "9000.00",
        "risk_points": ["用地合规风险", "接入距离过远"],
        "grid_prescreen": "rejected",
        "legal_review": "blocked",
    },
)

PRE_ENGINEERING_MILESTONES: tuple[dict[str, object], ...] = (
    {
        "code": "candidate_site_pool",
        "name": "候选场地池",
        "complete_after_hours": 0,
        "description": "先形成多个候选场地，不立即租赁。",
    },
    {
        "code": "grid_prescreen",
        "name": "并网预筛与接入风险判断",
        "complete_after_hours": 24,
        "description": "租赁前判断接入点、容量、消纳和增容风险。",
    },
    {
        "code": "legal_conditional_lease_review",
        "name": "场地合法性与附条件租赁审查",
        "complete_after_hours": 48,
        "description": "确认产权、用途、租期和失败退出条件。",
    },
    {
        "code": "structural_safety_document",
        "name": "结构/建筑安全责任文件取得",
        "complete_after_hours": 72,
        "document_code": "structural_safety_document",
        "description": "取得适用于当前场地和规模的结构安全书面结论。",
    },
    {
        "code": "pv_system_design_document",
        "name": "光伏系统设计责任文件取得",
        "complete_after_hours": 96,
        "document_code": "pv_system_design_document",
        "description": "取得组件布置、逆变器配置、设备清单和发电测算等设计文件。",
    },
    {
        "code": "electrical_grid_document",
        "name": "电气接入与并网责任文件取得",
        "complete_after_hours": 120,
        "document_code": "electrical_grid_document",
        "description": "取得电气接入、保护配置、防雷接地和并网材料责任文件。",
    },
    {
        "code": "construction_safety_quality_document",
        "name": "施工安全与质量责任主体确认",
        "complete_after_hours": 144,
        "document_code": "construction_safety_quality_document",
        "description": "确认施工组织、安全质量和隐蔽工程记录责任主体。",
    },
    {
        "code": "acceptance_archive_document",
        "name": "验收、调试、归档责任安排",
        "complete_after_hours": 168,
        "document_code": "acceptance_archive_document",
        "description": "形成并网验收、调试、竣工和运维交接资料责任安排。",
    },
)


def _metadata_int(metadata: dict[str, object], key: str, default: int) -> int:
    try:
        return int(metadata.get(key, default))
    except (TypeError, ValueError):
        return default


def pre_engineering_state(
    *,
    run: SimulationRun,
    hour: int,
    startup_gate: dict[str, object],
) -> dict[str, object]:
    """Compute pre-engineering phase state.  Returns an empty dict when the
    startup gate is not yet satisfied.
    """
    if not startup_gate.get("startup_gate_satisfied"):
        return {}
    started_hour = _metadata_int(run.metadata, "pre_engineering_started_hour", hour)
    elapsed_hours = max(hour - started_hour, 0)
    milestones = [
        pre_engineering_milestone_row(run=run, milestone=m, elapsed_hours=elapsed_hours)
        for m in PRE_ENGINEERING_MILESTONES
    ]
    completed = all(bool(r["completed"]) for r in milestones)
    selected_site = selected_site_candidate(elapsed_hours)
    return {
        "project_phase": "pre_engineering_completed" if completed else "pre_engineering",
        "status": "completed" if completed else "running",
        "completed": completed,
        "started_hour": started_hour,
        "elapsed_hours": elapsed_hours,
        "selected_site_code": selected_site["code"] if selected_site else "",
        "candidate_sites": candidate_site_rows(elapsed_hours),
        "milestones": milestones,
        "completed_milestone_count": len([r for r in milestones if r["completed"]]),
        "pending_milestone_count": len([r for r in milestones if not r["completed"]]),
        "blockers": pre_engineering_blockers(milestones),
        "next_actions": pre_engineering_next_actions(milestones),
    }


def pre_engineering_milestone_row(
    *,
    run: SimulationRun,
    milestone: dict[str, object],
    elapsed_hours: int,
) -> dict[str, object]:
    completed = elapsed_hours >= int(milestone["complete_after_hours"])
    document_code = str(milestone.get("document_code") or "")
    signer = document_signer_for_code(run=run, document_code=document_code) if document_code else {}
    return {
        "code": milestone["code"],
        "name": milestone["name"],
        "description": milestone["description"],
        "complete_after_hours": milestone["complete_after_hours"],
        "completed": completed,
        "status": "completed" if completed else "pending",
        "document_code": document_code,
        "covered_by": signer if completed and signer else {},
    }


def document_signer_for_code(*, run: SimulationRun, document_code: str) -> dict[str, object]:
    if not document_code:
        return {}
    partners = (
        PartnerApplication.objects.filter(
            metadata__simulation_run_id=run.run_id,
            status=PartnerApplication.Status.QUALIFIED,
            can_issue_responsibility_documents=True,
        ).order_by("application_id")
    )
    for partner in partners:
        if document_code in (partner.responsibility_document_domains or []):
            return partner_snapshot(partner)
    return {}


def candidate_site_rows(elapsed_hours: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    grid_visible = elapsed_hours >= 24
    legal_visible = elapsed_hours >= 48
    for site in PRE_ENGINEERING_SITE_CANDIDATES:
        grid_status = str(site["grid_prescreen"]) if grid_visible else "pending"
        legal_status = str(site["legal_review"]) if legal_visible else "pending"
        shortlisted = grid_status in {"conditional_pass", "needs_follow_up"} and legal_status == "conditional_pass"
        rows.append({
            "code": site["code"],
            "name": site["name"],
            "site_type": site["site_type"],
            "area_sqm": site["area_sqm"],
            "property_status": site["property_status"],
            "nearby_grid_condition": site["nearby_grid_condition"],
            "estimated_capacity_kw": site["estimated_capacity_kw"],
            "estimated_monthly_rent": site["estimated_monthly_rent"],
            "risk_points": site["risk_points"],
            "grid_prescreen_status": grid_status,
            "legal_review_status": legal_status,
            "shortlisted": shortlisted,
        })
    return rows


def selected_site_candidate(elapsed_hours: int) -> dict[str, object] | None:
    if elapsed_hours < 48:
        return None
    for row in candidate_site_rows(elapsed_hours):
        if row["shortlisted"]:
            return row
    return None


def pre_engineering_next_actions(milestones: list[dict[str, object]]) -> list[str]:
    for row in milestones:
        if not row["completed"]:
            return [f"继续推进：{row['name']}。"]
    return ["工程前置责任闭环已形成，可以进入采购、施工、调试和验收计划细化。"]


def pre_engineering_hour_summary(pre_engineering: dict[str, object]) -> str:
    if pre_engineering.get("status") == "completed":
        selected_site = pre_engineering.get("selected_site_code") or "候选场地"
        return f"工程前置阶段完成：{selected_site} 已通过预筛、附条件租赁审查和责任文件闭环。"
    blockers = pre_engineering.get("blockers") or []
    if blockers:
        return f"工程前置阶段推进中，下一项未完成：{blockers[0]['name']}。"
    return "工程前置阶段推进中。"
