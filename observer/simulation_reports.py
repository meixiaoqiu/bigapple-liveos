"""Public read models for archived simulation reports."""

from __future__ import annotations

from dataclasses import dataclass

from core.models import SimulationSnapshot, SimulationSnapshotItem
from simulation.archive import CONTROL_DATABASE_ALIAS
from simulation.snapshot_display import raw_plan_node_title_map, snapshot_item_title, source_model_label


@dataclass(frozen=True)
class PublicSimulationReport:
    snapshot: SimulationSnapshot
    headline: str
    conclusion: str
    key_findings: tuple[str, ...]
    improvements: tuple[str, ...]
    unresolved_questions: tuple[str, ...]
    timeline: tuple[dict[str, str], ...]
    counts: dict[str, int]
    short_hash: str


def public_simulation_reports(limit: int = 30) -> list[PublicSimulationReport]:
    snapshots = (
        SimulationSnapshot.objects.using(CONTROL_DATABASE_ALIAS)
        .filter(publication_status=SimulationSnapshot.PublicationStatus.PUBLIC)
        .order_by("-archived_at", "snapshot_id")[:limit]
    )
    return [build_public_simulation_report(snapshot, timeline_limit=8) for snapshot in snapshots]


def public_simulation_report(snapshot_id: str) -> PublicSimulationReport:
    snapshot = SimulationSnapshot.objects.using(CONTROL_DATABASE_ALIAS).get(
        snapshot_id=snapshot_id,
        publication_status=SimulationSnapshot.PublicationStatus.PUBLIC,
    )
    return build_public_simulation_report(snapshot, timeline_limit=80)


def build_public_simulation_report(
    snapshot: SimulationSnapshot,
    *,
    timeline_limit: int,
) -> PublicSimulationReport:
    summary = snapshot.normalized_summary if isinstance(snapshot.normalized_summary, dict) else {}
    failures = [item for item in summary.get("failures", []) if isinstance(item, dict)]
    change_sets = [item for item in summary.get("change_sets", []) if isinstance(item, dict)]
    counts = {str(key): int(value or 0) for key, value in (summary.get("counts") or {}).items()}
    first_failure = failures[0] if failures else {}

    headline = _headline(snapshot, first_failure)
    scenario = _scenario(first_failure)
    conclusion = _conclusion(snapshot, first_failure, scenario=scenario)
    key_findings = tuple(_key_findings(snapshot, failures, scenario=scenario))
    improvements = tuple(_improvements(change_sets))
    unresolved_questions = tuple(_unresolved_questions(snapshot, failures, scenario=scenario))
    timeline = tuple(_timeline_rows(snapshot, limit=timeline_limit))
    return PublicSimulationReport(
        snapshot=snapshot,
        headline=headline,
        conclusion=conclusion,
        key_findings=key_findings,
        improvements=improvements,
        unresolved_questions=unresolved_questions,
        timeline=timeline,
        counts=counts,
        short_hash=(snapshot.raw_archive_hash or "")[:16],
    )


def _headline(snapshot: SimulationSnapshot, first_failure: dict[str, object]) -> str:
    if snapshot.public_title:
        return snapshot.public_title
    if first_failure.get("title"):
        return str(first_failure["title"])
    if snapshot.failure_title:
        return snapshot.failure_title
    return f"{snapshot.source_world_id} / {snapshot.source_run_id} / {snapshot.run_status}"


def _scenario(first_failure: dict[str, object]) -> str:
    metadata = first_failure.get("metadata") if isinstance(first_failure.get("metadata"), dict) else {}
    return str(metadata.get("scenario") or "")


def _conclusion(snapshot: SimulationSnapshot, first_failure: dict[str, object], *, scenario: str) -> str:
    if snapshot.public_summary:
        return snapshot.public_summary
    if scenario == "zero_start":
        return "本次推演从一个发起人开始，说明网络报名可以形成兴趣和候选线索，但必须更早识别可追责责任能力。"
    if snapshot.failure_type == "responsibility_closure_missing":
        return "本次推演说明：工程类节点不能只看成员技能，必须提前补齐可归档、可追责的责任主体和责任文件。"
    if first_failure.get("description"):
        return str(first_failure["description"])
    if snapshot.run_status == "failed":
        return "本次推演在当前假设下触发失败，后续需要根据失败节点继续修订计划。"
    return "本次推演未触发阻断性失败，可继续对假设和过程颗粒度做压力测试。"


def _key_findings(snapshot: SimulationSnapshot, failures: list[dict[str, object]], *, scenario: str) -> list[str]:
    if scenario == "zero_start":
        return [
            "项目真正的零起点不是 A0 抵达，而是只有一个发起人和一个尚未成形的倡议。",
            "报名数量不是核心，候选人是否具备稳定参与意愿、可用时间和可验证能力才是核心。",
            "自述经验不能直接等同于责任能力，报名表和初筛必须区分兴趣、经验、专业能力和可追责责任能力。",
        ]
    if snapshot.failure_type == "responsibility_closure_missing":
        return [
            "低成本开荒不等于用成员自评替代专业责任。",
            "场地、结构、电气、并网、施工和验收都需要可追责文件形成闭环。",
            "能力缺口应尽早在招募、筛选和计划前置阶段暴露，而不是等到采购或施工前才发现。",
        ]
    findings: list[str] = []
    for failure in failures[:3]:
        title = str(failure.get("title") or "")
        description = str(failure.get("description") or "")
        if title and description:
            findings.append(f"{title}：{description}")
        elif title:
            findings.append(title)
    return findings or ["本次快照已归档为后续对比基线。"]


def _improvements(change_sets: list[dict[str, object]]) -> list[str]:
    improvements = [str(item.get("summary") or item.get("title") or "") for item in change_sets[:5]]
    return [item for item in improvements if item] or ["后续报告将记录本次推演带来的计划修订和参数调整。"]


def _unresolved_questions(snapshot: SimulationSnapshot, failures: list[dict[str, object]], *, scenario: str) -> list[str]:
    if scenario == "zero_start":
        return [
            "不同招募渠道的真实转化率、噪声比例和失联概率应该如何设定？",
            "报名者画像应如何验证，避免系统把自述技能当成真实能力？",
            "筛选后形成的候选池如何进一步转化为抵达、食宿、任务和治理流程？",
        ]
    if snapshot.failure_type == "responsibility_closure_missing":
        return [
            "哪些责任主体可以低成本但可追责地参与早期方案？",
            "招募和筛选阶段如何提前识别责任能力，而不是只识别兴趣和经验？",
            "下一次推演应从网络报名与成员筛选开始，避免默认已经存在可靠团队。",
        ]
    if failures:
        return ["该失败是否来自真实约束、参数设置，还是当前仿真颗粒度不足？"]
    return ["当前未失败并不代表现实可行，还需要继续增加更细的过程事件和压力测试。"]


def _timeline_rows(snapshot: SimulationSnapshot, *, limit: int) -> list[dict[str, str]]:
    node_title_map = raw_plan_node_title_map(snapshot)
    items = (
        SimulationSnapshotItem.objects.using(CONTROL_DATABASE_ALIAS)
        .filter(snapshot=snapshot)
        .exclude(item_type=SimulationSnapshotItem.ItemType.NODE_STATE)
        .order_by("sort_order", "item_id")[:limit]
    )
    rows = []
    for item in items:
        rows.append(
            {
                "order": str(item.sort_order),
                "type": item.get_item_type_display(),
                "source": source_model_label(item.source_model),
                "title": snapshot_item_title(item, node_title_map=node_title_map),
                "summary": item.summary,
            }
        )
    return rows
