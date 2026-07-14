"""Zero-start simulation: failure feedback and plan-revision proposals.

Writes SimulationFailure, PlanRevisionProposal, PlanChangeSet, and
PlanChangeOperation records.  Does NOT import ``zero_start.py``.
"""

from __future__ import annotations

from django.utils import timezone

from core.models import (
    Event,
    PlanChangeOperation,
    PlanChangeSet,
    PlanNode,
    PlanRequirement,
    PlanRevision,
    PlanRevisionProposal,
    SimulationFailure,
    SimulationRun,
)
from .form_drivers import FormSubmissionResult
from .ids import (
    generate_plan_change_operation_id,
    generate_plan_change_set_id,
    generate_plan_revision_proposal_id,
    generate_simulation_failure_id,
)
from .run_state import create_simulation_turn_and_event
from .zero_start_strategy import (
    APPLICATION_STATUS_CANDIDATE,
    APPLICATION_STATUS_REGISTERED,
    APPLICATION_STATUS_REJECTED,
    APPLICATION_STATUS_STANDBY,
    APPLICATION_STATUS_WITHDREW,
    STARTUP_CAPABILITY_REQUIREMENTS,
    STARTUP_DOCUMENT_SIGNER_REQUIREMENTS,
)


def create_zero_start_form_interaction_failure(
    *,
    run: SimulationRun,
    hour: int,
    result: FormSubmissionResult,
    simulation_day: int,
) -> dict[str, object]:
    """Create a fatal failure when a virtual subject cannot submit a real
    application form.  Marks the run as FAILED and writes a turn event.

    Returns the same dict shape that the orchestration loop expects:
    ``{"run", "failure", "proposal", "change_set"}``.
    """
    now = timezone.now()
    failure = SimulationFailure.objects.create(
        failure_id=generate_simulation_failure_id(),
        run=run,
        plan_node=None,
        failure_type=SimulationFailure.FailureType.EXECUTION_ISSUE,
        severity=SimulationFailure.Severity.CRITICAL,
        title="零起点仿真表单交互失败",
        description=(
            "虚拟主体通过真实报名入口提交数据时失败。"
            "这说明当前系统入口、表单字段、校验或保存链路无法支撑本轮仿真。"
        ),
        simulation_day=simulation_day,
        detected_at=now,
        metadata={
            "scenario": "zero_start",
            "simulation_hour": hour,
            "path": result.path,
            "status_code": result.status_code,
            "errors": result.errors,
            "failure_kind": "system_form_interaction_failed",
        },
    )
    run.status = SimulationRun.Status.FAILED
    run.ended_at = now
    run.failure_summary = failure.title
    run.metadata = {
        **run.metadata,
        "completed_hours": hour,
        "failure_id": failure.failure_id,
        "system_interaction_failed": True,
        "system_interaction_errors": result.errors,
    }
    run.save(update_fields=["status", "ended_at", "failure_summary", "metadata"])
    create_simulation_turn_and_event(
        run=run,
        title="真实报名表单交互失败",
        summary="虚拟主体访问或提交真实报名页面失败，本轮仿真停止。",
        simulation_day=simulation_day,
        severity=Event.Severity.CRITICAL,
        event_type=Event.EventType.RANDOM_INCIDENT,
        payload={
            "scenario": "zero_start",
            "simulation_hour": hour,
            "failure_id": failure.failure_id,
            "path": result.path,
            "status_code": result.status_code,
            "errors": result.errors,
        },
    )
    return {"run": run, "failure": failure, "proposal": None, "change_set": None}


def create_zero_start_gate_failure(
    *,
    run: SimulationRun,
    detected_hour: int,
    gate: dict[str, object],
    simulation_day: int,
    capability_requirements: tuple[dict[str, object], ...] | None = None,
    document_signer_requirements: tuple[dict[str, object], ...] | None = None,
) -> SimulationFailure:
    """Create the business failure when the startup gate is not satisfied.

    *gate* is the dict returned by
    :func:`simulation.projections.startup_gate_summary_for_run` and MUST
    contain the standard keys (startup_gate_satisfied, capability_coverage,
    missing_capabilities, etc.).
    """
    caps = capability_requirements or STARTUP_CAPABILITY_REQUIREMENTS
    docs = document_signer_requirements or STARTUP_DOCUMENT_SIGNER_REQUIREMENTS
    return SimulationFailure.objects.create(
        failure_id=generate_simulation_failure_id(),
        run=run,
        plan_node=None,
        failure_type=SimulationFailure.FailureType.RESPONSIBILITY_CLOSURE_MISSING,
        severity=SimulationFailure.Severity.CRITICAL,
        title="Z0 自媒体报名筛选后仍未达到启动门槛",
        description=(
            "本轮从一个发起人开始，自媒体曝光带来了一批明确想参加的报名者，"
            "但初始成员能力矩阵尚未补齐，结构、光伏、电气、施工和验收等文件签署方也未到位。"
            "项目仍处于筹备阶段，不能进入真实启动。"
        ),
        simulation_day=simulation_day,
        detected_at=timezone.now(),
        metadata={
            "scenario": "zero_start",
            "simulation_hour": detected_hour,
            "project_phase": "preparation",
            "startup_gate_satisfied": gate["startup_gate_satisfied"],
            "required_initial_capabilities": list(caps),
            "required_document_signers": list(docs),
            "capability_coverage": gate["capability_coverage"],
            "document_signer_coverage": gate["document_signer_coverage"],
            "missing_capabilities": gate["missing_capabilities"],
            "missing_document_signers": gate["missing_document_signers"],
            "cannot_continue_reasons": [
                "报名者想参加不等于项目已具备启动所需的稳定能力结构。",
                "做饭、文档、采购、后勤等能力可以由成员承担，但需要签字或出具文件的事项必须有对应签署方。",
                "结构、光伏、电气、施工安全、验收归档等文件责任尚未形成可追溯主体。",
            ],
            "recommended_actions": [
                "把自媒体报名、初筛、候选池和退出记录继续细化为小时级状态机。",
                "建立前 N 名成员能力矩阵，明确每种能力需要多少人到位。",
                "建立合作伙伴和文件签署方矩阵，明确哪些事项必须获得书面文件。",
                "所有启动前置门槛满足前，项目只能停留在筹备阶段。",
            ],
        },
    )


def plan_revision_has_zero_start_gate(revision: PlanRevision) -> bool:
    return PlanNode.objects.filter(revision=revision, code="Z0").exists()


def get_or_create_zero_start_feedback(
    *,
    run: SimulationRun,
    failure: SimulationFailure,
) -> tuple[PlanRevisionProposal | None, PlanChangeSet | None]:
    """Return existing or new feedback for a zero-start gate failure.

    If a DRAFT ``PlanChangeSet`` with the ``zero_start`` scenario and
    "启动门槛" title already exists for *run*, it is reused so
    consecutive observation windows do not generate duplicate feedback.
    """
    existing_change_set = (
        PlanChangeSet.objects.select_related("proposal")
        .filter(
            run=run,
            status=PlanChangeSet.Status.DRAFT,
            metadata__scenario="zero_start",
            title__contains="启动门槛",
        )
        .order_by("-created_at", "-change_set_id")
        .first()
    )
    if existing_change_set is not None:
        return existing_change_set.proposal, existing_change_set
    if plan_revision_has_zero_start_gate(run.plan_revision):
        return None, None
    return create_zero_start_feedback(run=run, failure=failure)


def create_zero_start_feedback(
    *,
    run: SimulationRun,
    failure: SimulationFailure,
) -> tuple[PlanRevisionProposal, PlanChangeSet]:
    """Create the full feedback chain for a zero-start gate failure.

    Writes one ``PlanRevisionProposal``, one ``PlanChangeSet``, and
    all the capability + document-signer ``PlanChangeOperation`` rows.
    """
    now = timezone.now()
    revision = run.plan_revision
    caps = list(STARTUP_CAPABILITY_REQUIREMENTS)
    docs = list(STARTUP_DOCUMENT_SIGNER_REQUIREMENTS)
    proposal = PlanRevisionProposal.objects.create(
        proposal_id=generate_plan_revision_proposal_id(),
        run=run,
        source_failure=failure,
        plan_revision=revision,
        plan_node=None,
        proposal_type=PlanRevisionProposal.ProposalType.ADD_NODE,
        status=PlanRevisionProposal.Status.DRAFT,
        title="增加自媒体报名筛选与启动门槛矩阵",
        rationale=(
            "从零起点推演发现：主动报名不等于项目可以启动。"
            "后续计划必须先确认前 N 名成员能力矩阵，以及需要书面文件的合作伙伴和签署方矩阵。"
        ),
        suggested_changes={
            "add_stage": "Z0 自媒体报名筛选与启动门槛确认",
            "application_state_machine": [
                APPLICATION_STATUS_REGISTERED,
                APPLICATION_STATUS_CANDIDATE,
                APPLICATION_STATUS_STANDBY,
                APPLICATION_STATUS_REJECTED,
                APPLICATION_STATUS_WITHDREW,
            ],
            "required_screening_dimensions": [
                "参与动机",
                "可用时间",
                "到场可能性",
                "自述技能",
                "可验证经历",
                "项目是否接纳为候选人",
                "是否主动退出",
            ],
            "startup_capability_requirements": caps,
            "startup_document_signer_requirements": docs,
            "requirement_semantics": {
                "capability": "需要人或合作方具备实际能力，不要求签字盖章文件。",
                "document": "需要可归档、可追责、可作为决策依据的书面文件和签署方。",
            },
        },
        created_at=now,
        metadata={"scenario": "zero_start"},
    )
    change_set = PlanChangeSet.objects.create(
        change_set_id=generate_plan_change_set_id(),
        run=run,
        proposal=proposal,
        plan_revision=revision,
        status=PlanChangeSet.Status.DRAFT,
        title="零起点启动门槛结构化变更",
        summary="新增 Z0 前置阶段，先形成报名状态机、成员能力矩阵和文件签署方矩阵，再进入成员抵达、食宿或工程计划。",
        created_at=now,
        metadata={"scenario": "zero_start"},
    )
    operations: list[dict[str, object]] = [
        {
            "operation_type": PlanChangeOperation.OperationType.ADD_NODE,
            "target_model": "PlanNode",
            "target_id": "",
            "rationale": "新增 Z0 自媒体报名筛选与启动门槛确认阶段。",
            "new_value": {
                "code": "Z0",
                "title": "自媒体报名筛选与启动门槛确认",
                "node_type": PlanNode.NodeType.RECRUITMENT,
                "description": (
                    "从发起人自媒体曝光开始，记录主动报名、初筛、候选、拒绝和退出，"
                    "并确认成员能力矩阵和文件签署方矩阵。"
                ),
                "planned_duration_days": 7,
                "estimated_cost_expected": "0.00",
                "required_people_min": 1,
                "required_people_max": 3,
                "required_person_days": "14.00",
                "required_skills": ["发起", "沟通", "文档", "报名筛选", "启动门槛识别"],
                "completion_criteria": [
                    "形成报名者状态机记录。",
                    "输出前 N 名成员能力矩阵。",
                    "输出合作伙伴和文件签署方矩阵。",
                    "明确项目仍处于筹备阶段或满足启动门槛。",
                ],
                "metadata": {
                    "scenario": "zero_start",
                    "project_phase": "preparation",
                    "application_source": "self_media",
                },
            },
        },
    ]
    for requirement in caps:
        operations.append({
            "operation_type": PlanChangeOperation.OperationType.ADD_REQUIREMENT,
            "target_model": "PlanRequirement",
            "target_id": "",
            "rationale": f"启动前必须确认具备能力：{requirement['name']}。",
            "metadata": {"scenario": "zero_start", "requirement_kind": "capability"},
            "new_value": {
                "node_code": "Z0",
                "requirement_type": PlanRequirement.RequirementType.SKILL,
                "name": f"能力需求：{requirement['name']}",
                "quantity": requirement["min_count"],
                "unit": "人",
                "unit_cost": "0.00",
                "total_cost_estimate": "0.00",
                "is_must": True,
                "notes": "这是实际能力需求，不要求提供签字盖章文件。",
                "metadata": {
                    "scenario": "zero_start",
                    "requirement_kind": "capability",
                    "capability_code": requirement["code"],
                    "skill_aliases": requirement["skill_aliases"],
                    "need_written_document": False,
                },
            },
        })
    for requirement in docs:
        operations.append({
            "operation_type": PlanChangeOperation.OperationType.ADD_REQUIREMENT,
            "target_model": "PlanRequirement",
            "target_id": "",
            "rationale": f"启动前必须确认文件签署方：{requirement['name']}。",
            "metadata": {"scenario": "zero_start", "requirement_kind": "document"},
            "new_value": {
                "node_code": "Z0",
                "requirement_type": PlanRequirement.RequirementType.PERMIT,
                "name": f"文件责任：{requirement['name']}",
                "quantity": 1,
                "unit": "项",
                "unit_cost": "0.00",
                "total_cost_estimate": "0.00",
                "is_must": True,
                "notes": "这是文件责任需求，必须有可归档、可追责的书面文件和签署方。",
                "metadata": {
                    "scenario": "zero_start",
                    "requirement_kind": "document",
                    "document_code": requirement["code"],
                    "document_examples": requirement["document_examples"],
                    "acceptable_signers": requirement["acceptable_signers"],
                    "need_written_document": True,
                },
            },
        })
    for index, operation in enumerate(operations, start=1):
        PlanChangeOperation.objects.create(
            operation_id=generate_plan_change_operation_id(),
            change_set=change_set,
            sequence=index,
            operation_type=operation["operation_type"],
            target_model=operation["target_model"],
            target_id=operation["target_id"],
            target_field="",
            old_value={},
            new_value=operation["new_value"],
            rationale=operation["rationale"],
            is_required=True,
            metadata=operation.get("metadata", {"scenario": "zero_start"}),
        )
    return proposal, change_set
