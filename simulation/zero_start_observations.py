"""Zero-start simulation: observer event payload and summary assembly.

Pure-functions module.  Does NOT query the ORM, does NOT write to the
database, and does NOT import ``zero_start.py``.  The orchestration engine
passes in all required data so this layer only cares about payload shape.
"""

from __future__ import annotations


def build_hour_payload(
    *,
    run,
    hour: int,
    applied: list,
    partner_applied: list,
    screening_rows: list[dict[str, object]],
    partner_screening_rows: list[dict[str, object]],
    candidate_summary: dict[str, int | bool],
    startup_gate: dict[str, object],
    pre_engineering: dict[str, object],
    simulation_day: int,
    driver_mode: str,
    candidate_status: str,
) -> dict[str, object]:
    """Assemble the per-hour observer-event payload.

    All domain constants (*driver_mode* and *candidate_status*) are
    injected by the engine so this module does not import form_drivers
    or zero_start_strategy.
    """
    payload: dict[str, object] = {
        "scenario": "zero_start",
        "simulation_hour": hour,
        "virtual_time": {
            "hour": hour,
            "day": simulation_day,
            "hour_of_day": hour % 24,
        },
        "project_phase": pre_engineering.get(
            "project_phase",
            startup_gate.get("project_phase", "preparation"),
        ),
        "state_machine": (
            "zero_start_recruitment_screening"
            if not pre_engineering
            else "zero_start_recruitment_and_pre_engineering"
        ),
        "driver_mode": driver_mode,
        "applicants_applied": [spec.index for spec in applied],
        "partners_applied": [spec.index for spec in partner_applied],
        "screening_results": screening_rows,
        "partner_screening_results": partner_screening_rows,
        "funnel_delta": {
            "new_member_applications": len(applied),
            "new_partner_applications": len(partner_applied),
            "member_screened": len(screening_rows),
            "partner_screened": len(partner_screening_rows),
            "member_candidates": len(
                [row for row in screening_rows if row.get("decision") == candidate_status]
            ),
            "partner_qualified": len(
                [row for row in partner_screening_rows if row.get("decision") == "qualified"]
            ),
        },
        "candidate_summary": candidate_summary,
        "startup_gate": startup_gate,
        "blockers": startup_gate_blockers(startup_gate),
        "next_actions": combined_next_actions(startup_gate, pre_engineering),
    }
    if pre_engineering:
        payload["pre_engineering"] = pre_engineering
    return payload


def startup_gate_blockers(startup_gate: dict[str, object]) -> list[dict[str, str]]:
    """Extract capability + document-signer blockers from a gate summary."""
    blockers: list[dict[str, str]] = [
        {"kind": "capability", "code": str(row.get("code") or ""), "name": str(row.get("name") or "")}
        for row in startup_gate.get("missing_capabilities", [])
    ]
    blockers.extend(
        {"kind": "document_signer", "code": str(row.get("code") or ""), "name": str(row.get("name") or "")}
        for row in startup_gate.get("missing_document_signers", [])
    )
    return blockers


def startup_gate_next_actions(startup_gate: dict[str, object]) -> list[str]:
    """Return human-readable next actions when the startup gate is not yet satisfied."""
    if startup_gate.get("startup_gate_satisfied"):
        return ["启动门槛满足，进入候选场地、并网预筛和工程责任文件前置审查。"]
    actions: list[str] = []
    if startup_gate.get("missing_capabilities"):
        actions.append("继续通过自媒体报名和筛选补齐成员能力矩阵。")
    if startup_gate.get("missing_document_signers"):
        actions.append("继续开放合作方报名，重点寻找可出具书面责任文件的主体。")
    return actions or ["继续观察报名质量和合作方资质变化。"]


def pre_engineering_blockers(milestones: list[dict[str, object]]) -> list[dict[str, str]]:
    """Return incomplete pre-engineering milestones as blockers."""
    return [
        {"kind": "pre_engineering", "code": str(row["code"]), "name": str(row["name"])}
        for row in milestones
        if not row["completed"]
    ]


def combined_next_actions(
    startup_gate: dict[str, object],
    pre_engineering: dict[str, object],
) -> list[str]:
    """Resolve the right set of next actions depending on the current phase."""
    if not startup_gate.get("startup_gate_satisfied"):
        return startup_gate_next_actions(startup_gate)
    if pre_engineering:
        return list(pre_engineering.get("next_actions") or [])
    return startup_gate_next_actions(startup_gate)


def observation_window_title(*, gate: dict[str, object], pre_engineering: dict[str, object]) -> str:
    if not gate.get("startup_gate_satisfied"):
        return "零起点报名筛选观察窗口结束"
    if pre_engineering.get("completed"):
        return "工程前置责任闭环观察窗口结束"
    return "工程前置流程观察窗口结束"


def observation_window_summary(*, gate: dict[str, object], pre_engineering: dict[str, object]) -> str:
    if not gate.get("startup_gate_satisfied"):
        return (
            "本观察窗口已结束。若成员能力矩阵和文件签署方矩阵仍未满足，"
            "项目继续停留在筹备阶段，可以继续向后推进招募和合作方报名。"
        )
    if pre_engineering.get("completed"):
        return (
            "启动门槛和工程前置责任闭环均已满足。仿真已形成从报名筛选到候选场地、"
            "并网预筛、附条件租赁和责任文件取得的完整链条。"
        )
    return (
        "启动门槛已满足，但候选场地、并网预筛、附条件租赁或工程责任文件仍在推进，"
        "本轮可以继续向后模拟。"
    )


def build_hour_summary(
    *,
    hour: int,
    applied: list,
    partner_applied: list,
    screening_rows: list[dict[str, object]],
    partner_screening_rows: list[dict[str, object]],
    candidate_summary: dict[str, int | bool],
    startup_gate: dict[str, object],
    pre_engineering: dict[str, object],
    pre_engineering_summary: str = "",
) -> str:
    """Assemble the per-hour human-readable event summary.

    Accepts *pre_engineering_summary* as a plain string computed by the
    engine so this module does not need to import ``zero_start_pre_engineering``.
    """
    phrases = [
        (
            f"第 {hour} 小时：发起人继续通过自媒体说明大苹果计划，"
            f"累计主动报名 {candidate_summary['registered_applicants']} 人，"
            f"进入候选池 {candidate_summary['candidate_members']} 人，"
            f"合作方报名 {candidate_summary['partner_applications']} 个，"
            f"合格责任合作方 {candidate_summary['qualified_partners']} 个。"
        ),
    ]
    if hour == 0:
        phrases.append("项目仍处于真正的零起点：只有一个发起人，没有成熟成员池、资源和工程计划。")
    for spec in applied:
        phrases.append(f"{spec.display_name} 提交报名：{spec.motivation}")
    for spec in partner_applied:
        phrases.append(f"{spec.organization_name} 提交合作方报名：{spec.qualification_summary}")
    for row in screening_rows:
        phrases.append(f"{row['display_name']} 完成初筛，结论：{row['decision']}。")
    for row in partner_screening_rows:
        phrases.append(f"{row['organization_name']} 完成合作方初筛，结论：{row['decision']}。")
    if hour % 24 == 0 and hour > 0:
        phrases.append("阶段复盘：报名数量不是启动条件，必须同时满足成员能力矩阵和文件签署方矩阵。")
    if startup_gate["missing_capabilities"]:
        phrases.append(f"能力缺口：{startup_gate['missing_capabilities'][0]['name']}。")
    if startup_gate["missing_document_signers"]:
        phrases.append(f"文件责任缺口：{startup_gate['missing_document_signers'][0]['name']}。")
    if startup_gate["startup_gate_satisfied"]:
        phrases.append("启动门槛已经满足：成员能力矩阵和责任文件签署方矩阵均已覆盖。")
    if pre_engineering:
        phrases.append(pre_engineering_summary)
    return " ".join(phrases)
