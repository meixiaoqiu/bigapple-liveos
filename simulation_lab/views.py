import json

from django.contrib import admin, messages
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core.exceptions import DomainError
from core.models import (
    PlanChangeOperation,
    PlanChangeSet,
    PlanRevision,
    PlanRevisionProposal,
    SimulationFailure,
    SimulationRun,
    SimulationRunDisposition,
    SimulationSnapshot,
    SimulationSnapshotItem,
    SimulationTurn,
)
from simulation.archive import CONTROL_DATABASE_ALIAS, archive_simulation_run, verify_simulation_snapshot
from simulation.boundary import run_simulation_turn
from simulation.disposition import (
    FINISHED_RUN_STATUSES,
    UnresolvedSimulationRunError,
    abort_simulation_run,
    is_continuable_zero_start_observation_run,
    record_discarded_disposition,
    source_alias_for_world,
    unresolved_finished_runs,
)
from simulation.plan_application import apply_plan_change_set, validate_plan_change_set_operations
from simulation.snapshot_display import raw_plan_node_title_map, snapshot_item_title, source_model_label
from simulation.zero_start import run_zero_start_recruitment_simulation
from worlds.context import context_from_registry
from worlds.models import WorldRegistry
from worlds.state import reset_current_world, set_current_world


MAX_SYNC_SIMULATION_HOURS = 168


def parse_int_form_value(raw_value: str, field_label: str) -> int:
    try:
        return int(raw_value.strip())
    except (TypeError, ValueError):
        raise DomainError(f"{field_label}必须是整数。") from None


def validate_sync_simulation_hours(hours: int) -> None:
    if hours < 1:
        raise DomainError("虚拟小时数必须至少为 1。")
    if hours > MAX_SYNC_SIMULATION_HOURS:
        raise DomainError(
            f"仿真实验后台单次最多推进 {MAX_SYNC_SIMULATION_HOURS} 个虚拟小时；"
            "长时间仿真请分多次继续推进，后续改用后台任务。"
        )


def simulation_worlds():
    return (
        WorldRegistry.objects.using(CONTROL_DATABASE_ALIAS)
        .filter(world_type=WorldRegistry.WorldType.SIMULATION, status=WorldRegistry.Status.ACTIVE)
        .order_by("world_id")
    )


def selected_simulation_world(request) -> WorldRegistry | None:
    world_id = str(request.POST.get("world_id") or request.GET.get("world_id") or "simulation0001").strip()
    worlds = simulation_worlds()
    if world_id:
        world = worlds.filter(world_id=world_id).first()
        if world is not None:
            return world
    return worlds.first()


def lab_redirect(world: WorldRegistry | None = None):
    if world is None:
        return redirect("simulation-lab-page")
    return redirect(f"{reverse('simulation-lab-page')}?world_id={world.world_id}")


def lab_run_detail_redirect(run_id: str, world: WorldRegistry):
    return redirect(f"{reverse('simulation-lab-run-detail', args=[run_id])}?world_id={world.world_id}")


def lab_admin_context(request, **extra):
    context = admin.site.each_context(request)
    context.update(extra)
    return context


def actor_for_request(request) -> str:
    username = str(request.user.get_username() or "").strip()
    return username or f"user:{request.user.pk}"


def pretty_json(value) -> str:
    if value in (None, "", {}, []):
        return ""
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def metadata_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


@require_GET
def lab_index(request):
    world = selected_simulation_world(request)
    unresolved_runs = unresolved_finished_runs(world=world) if world is not None else []
    active_zero_start_run = active_zero_start_run_for_world(world) if world is not None else None
    return render(
        request,
        "simulation_lab/index.html",
        lab_admin_context(
            request,
            title="仿真实验后台",
            simulation_worlds=simulation_worlds(),
            selected_world=world,
            unresolved_runs=unresolved_runs,
            active_zero_start_run=active_zero_start_run,
            can_start_simulation=world is not None and not unresolved_runs,
            sync_simulation_max_hours=MAX_SYNC_SIMULATION_HOURS,
        ),
    )


def active_zero_start_run_for_world(world: WorldRegistry) -> SimulationRun | None:
    source_alias = source_alias_for_world(world)
    running_run = (
        SimulationRun.objects.using(source_alias)
        .filter(status=SimulationRun.Status.RUNNING, metadata__scenario="zero_start")
        .order_by("-started_at", "-run_id")
        .first()
    )
    if running_run is not None:
        return running_run
    candidate_runs = (
        SimulationRun.objects.using(source_alias)
        .filter(status=SimulationRun.Status.FAILED, metadata__scenario="zero_start")
        .order_by("-started_at", "-run_id")[:20]
    )
    for run in candidate_runs:
        if is_continuable_zero_start_observation_run(run):
            return run
    return None


@require_GET
def lab_run_detail(request, run_id: str):
    world = selected_simulation_world(request)
    if world is None:
        messages.error(request, "没有可用的仿真世界。")
        return lab_redirect()

    source_alias = source_alias_for_world(world)
    run = get_object_or_404(
        SimulationRun.objects.using(source_alias).select_related("plan_revision", "plan_revision__plan"),
        run_id=run_id,
    )
    show_raw_metadata = request.GET.get("show_raw_metadata") == "1"
    failure_rows = list(
        SimulationFailure.objects.using(source_alias)
        .filter(run=run)
        .select_related("plan_node")
        .order_by("detected_at", "failure_id")
    )
    turns_query = SimulationTurn.objects.using(source_alias).filter(run=run)
    total_turn_count = turns_query.count()
    latest_turns = list(turns_query.order_by("-turn_number")[:80])
    latest_turns.reverse()
    turns = simulation_turn_rows(
        latest_turns,
        include_metadata=show_raw_metadata,
    )
    current_startup_gate = latest_startup_gate(run=run, failures=failure_rows, turns=turns)
    failures = simulation_failure_rows(
        failure_rows,
        include_metadata=show_raw_metadata,
        run=run,
        current_startup_gate=current_startup_gate,
    )
    proposals = simulation_proposal_rows(
        PlanRevisionProposal.objects.using(source_alias)
        .filter(run=run)
        .select_related("source_failure", "plan_node")
        .order_by("created_at", "proposal_id"),
        include_metadata=show_raw_metadata,
        run=run,
        current_startup_gate=current_startup_gate,
    )
    change_sets = simulation_change_set_rows(
        PlanChangeSet.objects.using(source_alias)
        .filter(run=run)
        .select_related("plan_revision", "applied_revision")
        .order_by("created_at", "change_set_id"),
        source_alias=source_alias,
        run=run,
        current_startup_gate=current_startup_gate,
    )
    is_resolved = (
        SimulationRunDisposition.objects.using(CONTROL_DATABASE_ALIAS)
        .filter(source_world_id=world.world_id, source_run_id=run.run_id)
        .exists()
        or SimulationSnapshot.objects.using(CONTROL_DATABASE_ALIAS)
        .filter(source_world_id=world.world_id, source_run_id=run.run_id)
        .exists()
    )
    return render(
        request,
        "simulation_lab/run_detail.html",
        lab_admin_context(
            request,
            title=f"{run.run_id} - 仿真运行详情",
            world=world,
            source_alias=source_alias,
            run=run,
            failures=failures,
            turns=turns,
            proposals=proposals,
            change_sets=change_sets,
            run_review=simulation_run_review(
                run,
                failures,
                turns,
                proposals,
                change_sets,
                current_startup_gate=current_startup_gate,
                total_turn_count=total_turn_count,
            ),
            is_resolved=is_resolved,
            can_dispose=not is_resolved and run.status in FINISHED_RUN_STATUSES,
            can_abort=not is_resolved
            and (run.status == SimulationRun.Status.RUNNING or is_continuable_zero_start_observation_run(run)),
            show_raw_metadata=show_raw_metadata,
            run_metadata=pretty_json(run.metadata) if show_raw_metadata else "",
            visible_turn_count=len(turns),
            total_turn_count=total_turn_count,
            sync_simulation_max_hours=MAX_SYNC_SIMULATION_HOURS,
        ),
    )


def simulation_run_review(
    run: SimulationRun,
    failures: list[SimulationFailure],
    turns: list[SimulationTurn],
    proposals: list[PlanRevisionProposal],
    change_sets: list[PlanChangeSet],
    *,
    current_startup_gate: dict[str, object] | None = None,
    total_turn_count: int | None = None,
) -> dict[str, object]:
    """Build a human-readable review report from existing run facts."""

    metadata = metadata_dict(run.metadata)
    latest_gate = current_startup_gate or latest_startup_gate(run=run, failures=failures, turns=turns)
    missing_capabilities = list(latest_gate.get("missing_capabilities") or [])
    missing_document_signers = list(latest_gate.get("missing_document_signers") or [])
    capability_coverage = list(latest_gate.get("capability_coverage") or [])
    document_signer_coverage = list(latest_gate.get("document_signer_coverage") or [])
    applicable_change_sets = [change_set for change_set in change_sets if getattr(change_set, "can_apply", False)]
    blocked_change_sets = [change_set for change_set in change_sets if getattr(change_set, "validation_errors", [])]
    rejected_change_sets = [change_set for change_set in change_sets if change_set.status == PlanChangeSet.Status.REJECTED]
    applied_change_sets = [change_set for change_set in change_sets if change_set.status == PlanChangeSet.Status.APPLIED]
    system_interaction_errors = list(metadata.get("system_interaction_errors") or [])
    if metadata.get("system_interaction_failed") and not system_interaction_errors:
        system_interaction_errors.append("系统交互失败")
    resolved_intermediate_failures = [
        failure for failure in failures if getattr(failure, "is_intermediate_resolved", False)
    ]
    evidence_rows = simulation_review_evidence_rows(
        failures=failures,
        missing_capabilities=missing_capabilities,
        missing_document_signers=missing_document_signers,
        system_interaction_errors=system_interaction_errors,
    )
    return {
        "verdict": simulation_review_verdict(
            run=run,
            applicable_change_sets=applicable_change_sets,
            blocked_change_sets=blocked_change_sets,
            missing_capabilities=missing_capabilities,
            missing_document_signers=missing_document_signers,
            system_interaction_errors=system_interaction_errors,
            resolved_intermediate_failures=resolved_intermediate_failures,
        ),
        "decision_hint": simulation_review_decision_hint(
            run=run,
            applicable_change_sets=applicable_change_sets,
            blocked_change_sets=blocked_change_sets,
            system_interaction_errors=system_interaction_errors,
            resolved_intermediate_failures=resolved_intermediate_failures,
        ),
        "intermediate_resolution_note": simulation_intermediate_resolution_note(
            run=run,
            resolved_intermediate_failures=resolved_intermediate_failures,
            applicable_change_sets=applicable_change_sets,
        ),
        "stats": [
            {"label": "已推进虚拟小时", "value": metadata.get("completed_hours", metadata.get("current_hour", "-"))},
            {"label": "观察窗口小时", "value": metadata.get("observation_window_hours", metadata.get("max_turns", run.max_turns))},
            {"label": "主动报名人数", "value": metadata.get("registered_applicants", "-")},
            {"label": "已筛选报名", "value": metadata.get("screened_applicants", "-")},
            {"label": "候选成员", "value": metadata.get("candidate_members", "-")},
            {"label": "合作方报名", "value": metadata.get("partner_applications", "-")},
            {"label": "合格合作方", "value": metadata.get("qualified_partners", "-")},
            {"label": "能力缺口", "value": len(missing_capabilities)},
            {"label": "文件签署方缺口", "value": len(missing_document_signers)},
            {"label": "推进日志", "value": total_turn_count if total_turn_count is not None else len(turns)},
            {"label": "失败记录", "value": len(failures)},
            {"label": "已解除中途阻塞", "value": len(resolved_intermediate_failures)},
            {"label": "可采纳变更集", "value": len(applicable_change_sets)},
        ],
        "capability_rows": simulation_review_requirement_rows(capability_coverage),
        "document_rows": simulation_review_requirement_rows(document_signer_coverage),
        "evidence_rows": evidence_rows,
        "change_set_summary": {
            "total": len(change_sets),
            "applicable": len(applicable_change_sets),
            "blocked": len(blocked_change_sets),
            "applied": len(applied_change_sets),
            "rejected": len(rejected_change_sets),
        },
        "key_timeline": simulation_review_key_timeline(turns),
    }


def latest_startup_gate(
    *,
    run: SimulationRun,
    failures: list[SimulationFailure],
    turns: list[SimulationTurn],
) -> dict[str, object]:
    run_gate = metadata_dict(metadata_dict(run.metadata).get("startup_gate"))
    if run.status == SimulationRun.Status.COMPLETED and run_gate:
        return run_gate
    for turn in reversed(turns):
        gate = metadata_dict(metadata_dict(turn.metadata).get("startup_gate"))
        if gate:
            return gate
    if run_gate:
        return run_gate
    for failure in reversed(failures):
        metadata = metadata_dict(failure.metadata)
        if metadata.get("capability_coverage") or metadata.get("document_signer_coverage"):
            return {
                "startup_gate_satisfied": metadata.get("startup_gate_satisfied"),
                "capability_coverage": metadata.get("capability_coverage") or [],
                "document_signer_coverage": metadata.get("document_signer_coverage") or [],
                "missing_capabilities": metadata.get("missing_capabilities") or [],
                "missing_document_signers": metadata.get("missing_document_signers") or [],
            }
    return {}


def startup_gate_is_satisfied(gate: dict[str, object]) -> bool:
    """Return whether the latest startup gate has no open capability or signer gaps."""

    return bool(gate.get("startup_gate_satisfied")) and not (
        gate.get("missing_capabilities") or gate.get("missing_document_signers")
    )


def failure_resolved_by_later_progress(
    *,
    run: SimulationRun,
    current_startup_gate: dict[str, object],
    failure: SimulationFailure,
) -> bool:
    """Treat only responsibility-closure blockers as resolved by a later satisfied startup gate."""

    if run.status != SimulationRun.Status.COMPLETED:
        return False
    if not startup_gate_is_satisfied(current_startup_gate):
        return False
    if failure.failure_type != SimulationFailure.FailureType.RESPONSIBILITY_CLOSURE_MISSING:
        return False
    metadata = metadata_dict(failure.metadata)
    return bool(metadata.get("missing_capabilities") or metadata.get("missing_document_signers"))


def feedback_naturally_absorbed(
    *,
    run: SimulationRun,
    current_startup_gate: dict[str, object],
    source_failure: SimulationFailure | None,
) -> bool:
    """Return whether feedback came from a responsibility blocker that this run later cleared."""

    return bool(
        source_failure
        and failure_resolved_by_later_progress(
            run=run,
            current_startup_gate=current_startup_gate,
            failure=source_failure,
        )
    )


def simulation_review_verdict(
    *,
    run: SimulationRun,
    applicable_change_sets: list[PlanChangeSet],
    blocked_change_sets: list[PlanChangeSet],
    missing_capabilities: list,
    missing_document_signers: list,
    system_interaction_errors: list,
    resolved_intermediate_failures: list[SimulationFailure],
) -> str:
    if system_interaction_errors:
        return "系统交互失败：这轮主要暴露报名表单或保存链路问题，不宜直接作为业务结论。"
    if run.status == SimulationRun.Status.RUNNING:
        return "仍在运行：可以继续推进观察，不应直接归档或废弃。"
    if run.status == SimulationRun.Status.ABORTED:
        return "已中止：适合作为调试记录复查，通常不进入正式仿真历史。"
    if missing_capabilities or missing_document_signers:
        return "启动门槛未满足：本轮有复盘价值，应重点审阅能力矩阵和责任文件签署方缺口。"
    if run.status == SimulationRun.Status.COMPLETED:
        if blocked_change_sets:
            return "仿真完成：最终门槛已满足，但仍有结构异常的计划变更集需要处理。"
        if resolved_intermediate_failures and applicable_change_sets:
            return "仿真完成：中途阻塞已被后续推进解除，但相关计划变更集仍需决定是否吸收。"
        if resolved_intermediate_failures:
            return "仿真完成：中途阻塞已被后续推进解除，可归档为成功样本。"
        if applicable_change_sets:
            return "仿真完成：未发现当前阻断，但仍有可采纳经验需要审阅。"
        return "仿真完成：未发现阻断性失败，可归档为成功样本。"
    if applicable_change_sets:
        return "发现可采纳经验：可审阅变更集，决定是否作为下一轮计划基线。"
    if blocked_change_sets:
        return "变更集存在结构问题：先修正或弃用变更集，再决定是否归档本轮。"
    return "需要人工审阅：结合失败证据、推进日志和变更集再决定处置。"


def simulation_review_decision_hint(
    *,
    run: SimulationRun,
    applicable_change_sets: list[PlanChangeSet],
    blocked_change_sets: list[PlanChangeSet],
    system_interaction_errors: list,
    resolved_intermediate_failures: list[SimulationFailure],
) -> str:
    if system_interaction_errors:
        return "建议先修复系统交互问题；这轮如果只是验证失败，可废弃，若要保留问题证据则归档。"
    if run.status == SimulationRun.Status.RUNNING or is_continuable_zero_start_observation_run(run):
        return "建议继续推进观察；如果确认本轮参数或模型错误，再中止后废弃。"
    if applicable_change_sets:
        if run.status == SimulationRun.Status.COMPLETED and resolved_intermediate_failures:
            return "建议先决定这些中途阻塞产生的变更集是否仍要吸收到计划基线；若已被后续模型自然覆盖，可弃用并记录原因。"
        return "建议先审阅并采纳或弃用变更集；run 是否归档是另一件事，归档只代表保留历史。"
    if blocked_change_sets:
        return "建议先处理不可应用变更集；不要在看不懂变更来源时启动下一轮。"
    if run.status in FINISHED_RUN_STATUSES:
        return "如果本轮不是误运行，建议归档；只有误运行、参数误设或无历史价值时才废弃。"
    return "当前状态暂不适合最终处置。"


def simulation_intermediate_resolution_note(
    *,
    run: SimulationRun,
    resolved_intermediate_failures: list[SimulationFailure],
    applicable_change_sets: list[PlanChangeSet],
) -> str:
    """Explain why completed runs can still keep earlier failure records as history."""

    if run.status != SimulationRun.Status.COMPLETED or not resolved_intermediate_failures:
        return ""
    note = f"本轮共有 {len(resolved_intermediate_failures)} 条中途阻塞记录，后续推进已经补齐对应门槛。"
    if applicable_change_sets:
        note = f"{note} 这些阻塞仍产生了计划变更集，需要单独决定采纳或弃用。"
    return note


def simulation_review_requirement_rows(rows: list[dict]) -> list[dict[str, object]]:
    normalized = []
    for row in rows:
        covered_by = row.get("covered_by") or []
        normalized.append(
            {
                "code": row.get("code", ""),
                "name": row.get("name", ""),
                "required_count": row.get("required_count", 0),
                "covered_count": row.get("covered_count", 0),
                "missing_count": row.get("missing_count", 0),
                "covered_by": covered_by,
                "document_examples": row.get("document_examples") or [],
                "acceptable_signers": row.get("acceptable_signers") or [],
            }
        )
    return normalized


def simulation_review_evidence_rows(
    *,
    failures: list[SimulationFailure],
    missing_capabilities: list[dict],
    missing_document_signers: list[dict],
    system_interaction_errors: list,
) -> list[dict[str, str]]:
    rows = []
    for failure in failures:
        kind = "中途阻塞（已解除）" if getattr(failure, "is_intermediate_resolved", False) else "失败记录"
        detail = failure.description
        if getattr(failure, "is_intermediate_resolved", False):
            detail = f"{detail} 后续推进已补齐当前门槛，此记录作为历史过程证据保留。"
        rows.append(
            {
                "kind": kind,
                "title": failure.title,
                "detail": detail,
            }
        )
    for item in missing_capabilities:
        rows.append(
            {
                "kind": "能力缺口",
                "title": str(item.get("name") or item.get("code") or "-"),
                "detail": f"需要 {item.get('required_count', 0)}，已覆盖 {item.get('covered_count', 0)}。",
            }
        )
    for item in missing_document_signers:
        examples = "、".join(str(value) for value in item.get("document_examples", [])[:3])
        rows.append(
            {
                "kind": "责任文件签署方缺口",
                "title": str(item.get("name") or item.get("code") or "-"),
                "detail": f"需要可归档、可追责文件签署方。示例文件：{examples or '未列出'}。",
            }
        )
    for error in system_interaction_errors:
        rows.append({"kind": "系统交互错误", "title": "报名表单链路失败", "detail": str(error)})
    return rows


def simulation_review_key_timeline(turns: list[SimulationTurn]) -> list[SimulationTurn]:
    key_turns = [
        turn
        for turn in turns
        if getattr(turn, "applicant_applied_count", 0)
        or getattr(turn, "partner_applied_count", 0)
        or getattr(turn, "screened_count", 0)
        or getattr(turn, "partner_screened_count", 0)
        or getattr(turn, "missing_capability_count", 0)
        or getattr(turn, "missing_document_signer_count", 0)
        or getattr(turn, "pre_engineering_active", False)
    ]
    if not key_turns:
        key_turns = turns[:10]
    return key_turns[-20:]


def simulation_failure_rows(
    failures,
    *,
    include_metadata: bool = False,
    run: SimulationRun | None = None,
    current_startup_gate: dict[str, object] | None = None,
) -> list[SimulationFailure]:
    rows = list(failures)
    for failure in rows:
        metadata = metadata_dict(failure.metadata)
        failure.missing_responsibility_domains = metadata.get("missing_responsibility_domains") or []
        failure.missing_capabilities = metadata.get("missing_capabilities") or []
        failure.missing_document_signers = metadata.get("missing_document_signers") or []
        failure.cannot_continue_reasons = metadata.get("cannot_continue_reasons") or []
        failure.recommended_actions = metadata.get("recommended_actions") or []
        failure.is_intermediate_resolved = bool(
            run
            and current_startup_gate is not None
            and failure_resolved_by_later_progress(
                run=run,
                current_startup_gate=current_startup_gate,
                failure=failure,
            )
        )
        failure.current_effect_label = "中途阻塞，后续已解除" if failure.is_intermediate_resolved else "当前失败证据"
        failure.display_metadata = pretty_json(metadata) if include_metadata else ""
    return rows


def simulation_turn_rows(turns, *, include_metadata: bool = False) -> list[SimulationTurn]:
    rows = list(turns)
    for turn in rows:
        metadata = metadata_dict(turn.metadata)
        candidate_summary = metadata_dict(metadata.get("candidate_summary"))
        startup_gate = metadata_dict(metadata.get("startup_gate"))
        pre_engineering = metadata_dict(metadata.get("pre_engineering"))
        turn.simulation_hour = metadata.get("simulation_hour", "")
        turn.event_title = metadata.get("title", "")
        turn.applicant_applied_count = len(metadata.get("applicants_applied") or [])
        turn.partner_applied_count = len(metadata.get("partners_applied") or [])
        turn.screened_count = len(metadata.get("screening_results") or [])
        turn.partner_screened_count = len(metadata.get("partner_screening_results") or [])
        turn.registered_applicants = candidate_summary.get("registered_applicants", "")
        turn.candidate_members = candidate_summary.get("candidate_members", "")
        turn.partner_applications = candidate_summary.get("partner_applications", "")
        turn.qualified_partners = candidate_summary.get("qualified_partners", "")
        turn.missing_capability_count = len(startup_gate.get("missing_capabilities") or [])
        turn.missing_document_signer_count = len(startup_gate.get("missing_document_signers") or [])
        turn.pre_engineering_active = bool(pre_engineering)
        turn.pre_engineering_status = pre_engineering.get("status", "")
        turn.pre_engineering_completed_milestones = pre_engineering.get("completed_milestone_count", "")
        turn.pre_engineering_pending_milestones = pre_engineering.get("pending_milestone_count", "")
        turn.selected_site_code = pre_engineering.get("selected_site_code", "")
        turn.display_metadata = pretty_json(metadata) if include_metadata else ""
    return rows


def simulation_proposal_rows(
    proposals,
    *,
    include_metadata: bool = False,
    run: SimulationRun | None = None,
    current_startup_gate: dict[str, object] | None = None,
) -> list[PlanRevisionProposal]:
    rows = list(proposals)
    for proposal in rows:
        proposal.is_naturally_absorbed = bool(
            run
            and current_startup_gate is not None
            and feedback_naturally_absorbed(
                run=run,
                current_startup_gate=current_startup_gate,
                source_failure=proposal.source_failure,
            )
        )
        proposal.display_suggested_changes = pretty_json(proposal.suggested_changes)
        proposal.display_metadata = pretty_json(proposal.metadata) if include_metadata else ""
    return rows


def simulation_change_set_rows(
    change_sets,
    *,
    source_alias: str,
    run: SimulationRun | None = None,
    current_startup_gate: dict[str, object] | None = None,
) -> list[PlanChangeSet]:
    rows = list(change_sets)
    operations_by_change_set: dict[str, list[PlanChangeOperation]] = {}
    proposal_ids = [change_set.proposal_id for change_set in rows if change_set.proposal_id]
    proposals_by_id = (
        PlanRevisionProposal.objects.using(source_alias)
        .filter(proposal_id__in=proposal_ids)
        .select_related("source_failure")
        .in_bulk(field_name="proposal_id")
    )
    operations = (
        PlanChangeOperation.objects.using(source_alias)
        .filter(change_set_id__in=[change_set.change_set_id for change_set in rows])
        .order_by("change_set_id", "sequence", "operation_id")
    )
    for operation in operations:
        operation.display_old_value = pretty_json(operation.old_value)
        operation.display_new_value = pretty_json(operation.new_value)
        operation.display_metadata = pretty_json(operation.metadata)
        operations_by_change_set.setdefault(operation.change_set_id, []).append(operation)
    for change_set in rows:
        source_proposal = proposals_by_id.get(change_set.proposal_id)
        change_set.source_proposal = source_proposal
        change_set.missing_proposal = change_set.proposal_id and source_proposal is None
        change_set.display_metadata = pretty_json(change_set.metadata)
        change_set.display_operations = operations_by_change_set.get(change_set.change_set_id, [])
        change_set.is_naturally_absorbed = bool(
            run
            and current_startup_gate is not None
            and source_proposal
            and feedback_naturally_absorbed(
                run=run,
                current_startup_gate=current_startup_gate,
                source_failure=source_proposal.source_failure,
            )
        )
        change_set.is_next_baseline = (
            change_set.applied_revision_id
            and change_set.applied_revision
            and change_set.applied_revision.status == PlanRevision.Status.PUBLISHED
        )
        change_set.validation_errors = []
        if change_set.status != PlanChangeSet.Status.APPLIED:
            change_set.validation_errors = validate_plan_change_set_operations(
                change_set,
                using=source_alias,
                operations=change_set.display_operations,
            )
        if change_set.missing_proposal:
            change_set.validation_errors = [f"来源修订建议缺失：{change_set.proposal_id}", *change_set.validation_errors]
        change_set.validation_summary = "；".join(change_set.validation_errors[:3])
        change_set.can_apply = (
            (change_set.status != PlanChangeSet.Status.APPLIED or not change_set.is_next_baseline)
            and not change_set.validation_errors
        )
        change_set.can_reject = change_set.status not in {PlanChangeSet.Status.APPLIED, PlanChangeSet.Status.REJECTED}
        change_set.recommendation_label, change_set.recommendation_reason = simulation_change_set_recommendation(change_set)
    return rows


def simulation_change_set_recommendation(change_set: PlanChangeSet) -> tuple[str, str]:
    """Return an operator-facing recommendation for one plan change set."""

    if change_set.status == PlanChangeSet.Status.REJECTED:
        return "已弃用", "该变更集已经明确不吸收到计划基线，无需再次处理。"
    if change_set.status == PlanChangeSet.Status.APPLIED:
        if getattr(change_set, "is_next_baseline", False):
            return "已采纳", "该变更集已经发布为下一轮仿真基线，无需再次处理。"
        return "需要人工复查", "该变更集已生成计划版本，但尚未成为下一轮基线；请确认是否仍应作为当前基线。"
    if getattr(change_set, "missing_proposal", False):
        return "建议弃用", "来源修订建议已经缺失，无法可靠追溯问题来源；不建议采纳，只保留为异常记录。"
    validation_errors = list(getattr(change_set, "validation_errors", []) or [])
    if validation_errors:
        return "建议先修复或弃用", "该变更集结构校验未通过，直接采纳会污染下一轮计划基线。"
    if getattr(change_set, "is_naturally_absorbed", False):
        return (
            "建议采纳",
            "本轮后续推进自然补齐了这个中途阻塞，说明该前置阶段是真实经验；建议固化到下一轮仿真基线，避免重复踩同一个坑。",
        )
    if getattr(change_set, "can_apply", False):
        return "建议人工审阅后采纳", "该变更集结构有效，但尚未证明属于中途阻塞的必要修正；请结合变更操作决定是否吸收。"
    return "需要人工判断", "当前状态不足以自动给出采纳或弃用建议，请结合失败证据和变更操作审阅。"


@require_GET
def lab_snapshot_list(request):
    snapshots = SimulationSnapshot.objects.using(CONTROL_DATABASE_ALIAS).order_by("-archived_at", "snapshot_id")[:100]
    return render(
        request,
        "simulation_lab/snapshot_list.html",
        lab_admin_context(request, title="仿真快照", snapshots=snapshots),
    )


@require_GET
def lab_snapshot_detail(request, snapshot_id: str):
    snapshot = get_object_or_404(
        SimulationSnapshot.objects.using(CONTROL_DATABASE_ALIAS),
        snapshot_id=snapshot_id,
    )
    items = SimulationSnapshotItem.objects.using(CONTROL_DATABASE_ALIAS).filter(snapshot=snapshot)
    item_counts = items.values("item_type").annotate(total=Count("item_id")).order_by("item_type")
    raw_table_counts = [_raw_table_count_row(model, count) for model, count in sorted((snapshot.raw_table_counts or {}).items())]
    normalized_summary = snapshot.normalized_summary if isinstance(snapshot.normalized_summary, dict) else {}
    node_title_map = raw_plan_node_title_map(snapshot)
    item_rows = snapshot_item_rows(items.order_by("sort_order", "item_id")[:200], node_title_map=node_title_map)
    return render(
        request,
        "simulation_lab/snapshot_detail.html",
        lab_admin_context(
            request,
            title=f"{snapshot.snapshot_id} - 仿真快照",
            snapshot=snapshot,
            failures=normalized_summary.get("failures") or [],
            item_counts=item_counts,
            raw_table_counts=raw_table_counts,
            items=item_rows,
            summary_counts=normalized_summary.get("counts") or {},
        ),
    )


@require_POST
def lab_verify_snapshot(request, snapshot_id: str):
    try:
        result = verify_simulation_snapshot(snapshot_id)
    except SimulationSnapshot.DoesNotExist:
        messages.error(request, f"仿真快照不存在：{snapshot_id}")
        return redirect("simulation-lab-snapshot-list")

    for warning in result.warnings:
        messages.warning(request, warning)
    if result.ok:
        messages.success(
            request,
            f"快照校验通过：raw 模型 {result.raw_model_count} 个，标准化明细 {result.normalized_item_count} 条。",
        )
    else:
        first_errors = "；".join(result.errors[:3])
        if len(result.errors) > 3:
            first_errors = f"{first_errors}；另有 {len(result.errors) - 3} 个问题"
        messages.error(request, f"快照校验失败：{first_errors}")
    return redirect("simulation-lab-snapshot-detail", snapshot_id=snapshot_id)


def snapshot_item_rows(items, *, node_title_map: dict[str, str]) -> list[SimulationSnapshotItem]:
    rows = list(items)
    for item in rows:
        item.display_title = snapshot_item_title(item, node_title_map=node_title_map)
        item.display_source = source_model_label(item.source_model)
    return rows


def _raw_table_count_row(model: str, count: int) -> dict[str, object]:
    return {"model": model, "label": source_model_label(model), "count": count}


@require_POST
def lab_advance(request):
    try:
        run_simulation_turn(simulation_day=1)
    except DomainError as exc:
        messages.success(request, f"仿真写库边界自检通过：{exc}")
    return redirect("simulation-lab-page")


@require_POST
def lab_run_until_failure(request):
    world = selected_simulation_world(request)
    if world is None:
        messages.error(request, "没有可用的仿真世界。请先在 WorldRegistry 中创建 simulation world。")
        return lab_redirect()
    try:
        hours = parse_int_form_value(request.POST.get("hours", "168"), "虚拟小时数")
        validate_sync_simulation_hours(hours)
        if unresolved_finished_runs(world=world):
            raise UnresolvedSimulationRunError(
                f"{world.world_id} 存在已结束但未处置的仿真运行，请先归档或废弃后再启动下一轮。"
            )
        call_command("seed_world", world.world_id, "--template", "zero_start")
        context = context_from_registry(world)
        token = set_current_world(context)
        try:
            result = run_zero_start_recruitment_simulation(hours=hours, ensure_seed=False)
        finally:
            reset_current_world(token)
    except (CommandError, DomainError, UnresolvedSimulationRunError, ValueError) as exc:
        messages.error(request, f"零起点仿真未启动：{exc}")
    else:
        run = result["run"]
        failure = result.get("failure")
        proposal = result.get("proposal")
        if run.status == SimulationRun.Status.FAILED and failure:
            change_set = proposal.change_sets.order_by("-created_at").first() if proposal else None
            proposal_text = f"，已生成修订建议 {proposal.proposal_id}" if proposal else ""
            change_set_text = f" 和结构化变更集 {change_set.change_set_id}" if change_set else ""
            messages.warning(
                request,
                f"零起点仿真 {run.run_id} 在 {hours} 个虚拟小时后失败：{failure.title}{proposal_text}{change_set_text}。",
            )
        elif run.status == SimulationRun.Status.COMPLETED:
            messages.success(request, f"零起点仿真 {run.run_id} 已完成，当前计划未触发阻断性失败。")
        elif run.status == SimulationRun.Status.RUNNING and failure:
            proposal_text = f"，已生成修订建议 {proposal.proposal_id}" if proposal else ""
            messages.warning(
                request,
                f"零起点仿真 {run.run_id} 已推进 {hours} 个虚拟小时；启动门槛仍未满足，但可继续推进{proposal_text}。",
            )
        elif run.status == SimulationRun.Status.PAUSED:
            messages.warning(request, f"零起点仿真 {run.run_id} 达到最大推进步数后暂停。")
        else:
            messages.success(request, f"零起点仿真 {run.run_id} 已完成。")
    return lab_redirect(world)


@require_POST
def lab_archive_run(request, run_id: str):
    world = selected_simulation_world(request)
    if world is None:
        messages.error(request, "没有可用的仿真世界。")
        return lab_redirect()
    try:
        source_alias = source_alias_for_world(world)
        run = SimulationRun.objects.using(source_alias).get(run_id=run_id)
        if run.status not in FINISHED_RUN_STATUSES:
            raise DomainError(f"只有已结束的仿真运行才能归档：{run.run_id} ({run.status})")
        reason = str(request.POST.get("reason") or "通过仿真实验后台归档。").strip()
        result = archive_simulation_run(
            world=world,
            run_id=run.run_id,
            scenario=str(run.metadata.get("scenario") or "zero_start") if isinstance(run.metadata, dict) else "zero_start",
            purpose="归档本轮仿真实验结果，形成可追溯历史快照。",
            review_conclusion=reason,
            public_summary=run.failure_summary,
            decided_by=actor_for_request(request),
            disposition_reason=reason,
        )
    except (SimulationRun.DoesNotExist, DomainError, ValueError) as exc:
        messages.error(request, f"仿真运行归档失败：{exc}")
    else:
        action = "已归档" if result.created else "已存在归档"
        messages.success(request, f"{action}：{result.snapshot.snapshot_id} / {run.run_id}")
    return lab_redirect(world)


@require_POST
def lab_abort_run(request, run_id: str):
    world = selected_simulation_world(request)
    if world is None:
        messages.error(request, "没有可用的仿真世界。")
        return lab_redirect()
    try:
        reason = str(request.POST.get("reason") or "").strip()
        source_alias = source_alias_for_world(world)
        run = SimulationRun.objects.using(source_alias).get(run_id=run_id)
        context = context_from_registry(world)
        token = set_current_world(context)
        try:
            abort_simulation_run(
                run=run,
                reason=reason,
                decided_by=actor_for_request(request),
            )
        finally:
            reset_current_world(token)
    except SimulationRun.DoesNotExist:
        messages.error(request, f"仿真运行不存在：{run_id}")
    except (DomainError, ValueError) as exc:
        messages.error(request, f"仿真运行中止失败：{exc}")
    else:
        messages.warning(request, f"已中止本轮仿真：{run.run_id}")
    return lab_run_detail_redirect(run_id, world)


@require_POST
def lab_apply_change_set(request, run_id: str, change_set_id: str):
    world = selected_simulation_world(request)
    if world is None:
        messages.error(request, "没有可用的仿真世界。")
        return lab_redirect()
    try:
        source_alias = source_alias_for_world(world)
        change_set = (
            PlanChangeSet.objects.using(source_alias)
            .select_related("run", "plan_revision", "applied_revision")
            .get(change_set_id=change_set_id, run_id=run_id)
        )
        context = context_from_registry(world)
        token = set_current_world(context)
        try:
            revision = apply_plan_change_set(change_set, actor=actor_for_request(request), publish=True)
        finally:
            reset_current_world(token)
    except PlanChangeSet.DoesNotExist:
        messages.error(request, f"计划变更集不存在或不属于该仿真运行：{change_set_id}")
    except (DomainError, ValueError) as exc:
        messages.error(request, f"计划变更集应用失败：{exc}")
    else:
        messages.success(
            request,
            f"计划变更集 {change_set.change_set_id} 已采纳并设为下一轮基线 {revision.revision_code} ({revision.revision_id})。",
        )
    return lab_run_detail_redirect(run_id, world)


@require_POST
def lab_reject_change_set(request, run_id: str, change_set_id: str):
    world = selected_simulation_world(request)
    if world is None:
        messages.error(request, "没有可用的仿真世界。")
        return lab_redirect()
    try:
        source_alias = source_alias_for_world(world)
        change_set = (
            PlanChangeSet.objects.using(source_alias)
            .select_related("run", "plan_revision", "applied_revision")
            .get(change_set_id=change_set_id, run_id=run_id)
        )
        if change_set.status == PlanChangeSet.Status.APPLIED:
            raise DomainError("已应用的计划变更集不能弃用。")
        if change_set.status == PlanChangeSet.Status.REJECTED:
            raise DomainError("该计划变更集已经被弃用。")
        reason = str(request.POST.get("reason") or "通过仿真实验后台审阅后弃用。").strip()
        metadata = dict(change_set.metadata or {})
        rejected_at = timezone.now()
        metadata["rejection"] = {
            "rejected_by": actor_for_request(request),
            "rejected_at": rejected_at.isoformat(),
            "reason": reason,
        }
        change_set.status = PlanChangeSet.Status.REJECTED
        change_set.reviewed_at = rejected_at
        change_set.metadata = metadata
        change_set.save(using=source_alias, update_fields=["status", "reviewed_at", "metadata"])
    except PlanChangeSet.DoesNotExist:
        messages.error(request, f"计划变更集不存在或不属于该仿真运行：{change_set_id}")
    except (DomainError, ValueError) as exc:
        messages.error(request, f"计划变更集弃用失败：{exc}")
    else:
        messages.success(request, f"已弃用计划变更集 {change_set.change_set_id}。")
    return lab_run_detail_redirect(run_id, world)


@require_POST
def lab_discard_run(request, run_id: str):
    world = selected_simulation_world(request)
    if world is None:
        messages.error(request, "没有可用的仿真世界。")
        return lab_redirect()
    try:
        reason = str(request.POST.get("reason") or "").strip()
        source_alias = source_alias_for_world(world)
        run = SimulationRun.objects.using(source_alias).get(run_id=run_id)
        if run.status not in FINISHED_RUN_STATUSES:
            raise DomainError(f"只有已结束的仿真运行才能废弃：{run.run_id} ({run.status})")
        disposition = record_discarded_disposition(
            world=world,
            run=run,
            reason=reason,
            decided_by=actor_for_request(request),
        )
    except SimulationRun.DoesNotExist as exc:
        messages.error(request, f"仿真运行不存在：{run_id}")
    except (DomainError, ValueError) as exc:
        messages.error(request, f"仿真运行废弃失败：{exc}")
    else:
        messages.success(request, f"已记录废弃处置：{disposition.disposition_id} / {run.run_id}")
    return lab_redirect(world)
