"""Hour-level zero-start application and startup-gate simulation."""

from __future__ import annotations

from django.utils import timezone

from core.application_services import review_partner_application
from core.db import atomic_for_model
from core.exceptions import DomainError
from core.models import (
    Event,
    Member,
    MemberApplication,
    PlanRevision,
    ProjectPlan,
    PartnerApplication,
    SimulationRun,
    SimulationRunDisposition,
    SimulationSnapshot,
)
from live_os.demo_seed.zero_start import (
    ZERO_START_FOUNDER_MEMBER_NO,
    ZERO_START_PLAN_ID,
    ZERO_START_REVISION_ID,
    seed_zero_start,
)
from worlds.state import get_current_world

from .disposition import CONTROL_DATABASE_ALIAS, is_continuable_zero_start_observation_run
from .form_drivers import FormSubmissionResult, HttpFormDriver
from .zero_start_feedback import (
    create_zero_start_form_interaction_failure,
    create_zero_start_gate_failure,
    get_or_create_zero_start_feedback,
)
from .ids import (
    generate_simulation_run_id,
)
from .projections import (
    candidate_summary_for_run,
    partner_snapshot,
    startup_gate_summary_for_run,
)
from .run_state import create_simulation_turn_and_event
from .zero_start_observations import (
    build_hour_payload,
    combined_next_actions,
    observation_window_summary,
    observation_window_title,
    pre_engineering_blockers,
    startup_gate_blockers,
)
from .zero_start_strategy import (
    APPLICATION_STATUS_CANDIDATE,
    APPLICATION_STATUS_REGISTERED,
    APPLICATION_STATUS_REJECTED,
    APPLICATION_STATUS_STANDBY,
    APPLICATION_STATUS_WITHDREW,
    ApplicantSpec,
    PartnerSpec,
    applicant_specs_for_hours,
    partner_specs_for_hours,
    screening_decision,
    STARTUP_CAPABILITY_REQUIREMENTS,
    STARTUP_DOCUMENT_SIGNER_REQUIREMENTS,
)

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


def run_zero_start_recruitment_simulation(*, hours: int = 168, ensure_seed: bool = True) -> dict[str, object]:
    """Run the first zero-start slice from one founder through application screening.

    The slice starts from project self-media exposure and explicit applications.
    It separates two startup gates: members with practical capabilities, and
    document signers who can issue written, accountable project documents.
    """

    if hours <= 0:
        raise ValueError("hours must be greater than 0.")
    if ensure_seed:
        seed_zero_start()
    revision = _zero_start_revision()
    existing_run = _continuable_zero_start_run()
    return _run_zero_start(revision=revision, hours=hours, run=existing_run)


def _zero_start_revision() -> PlanRevision:
    plan = ProjectPlan.objects.get(plan_id=ZERO_START_PLAN_ID)
    revision = (
        plan.revisions.filter(status=PlanRevision.Status.PUBLISHED)
        .order_by("-published_at", "-created_at", "revision_code")
        .first()
    )
    if revision is not None:
        return revision
    return PlanRevision.objects.get(revision_id=ZERO_START_REVISION_ID)


def _continuable_zero_start_run() -> SimulationRun | None:
    resolved_run_ids = _resolved_zero_start_run_ids()
    running_run = (
        SimulationRun.objects.filter(status=SimulationRun.Status.RUNNING, metadata__scenario="zero_start")
        .order_by("-started_at", "-run_id")
        .first()
    )
    if running_run is not None:
        return running_run
    candidate_runs = (
        SimulationRun.objects.filter(status=SimulationRun.Status.FAILED, metadata__scenario="zero_start")
        .order_by("-started_at", "-run_id")[:20]
    )
    for run in candidate_runs:
        if run.run_id not in resolved_run_ids and is_continuable_zero_start_observation_run(run):
            return run
    return None


def _resolved_zero_start_run_ids() -> set[str]:
    world_id = _current_world_id()
    if not world_id:
        return set()
    disposed_run_ids = set(
        SimulationRunDisposition.objects.using(CONTROL_DATABASE_ALIAS)
        .filter(source_world_id=world_id)
        .values_list("source_run_id", flat=True)
    )
    archived_run_ids = set(
        SimulationSnapshot.objects.using(CONTROL_DATABASE_ALIAS)
        .filter(source_world_id=world_id)
        .values_list("source_run_id", flat=True)
    )
    return disposed_run_ids | archived_run_ids


@atomic_for_model(SimulationRun)
def _run_zero_start(*, revision: PlanRevision, hours: int, run: SimulationRun | None = None) -> dict[str, object]:
    now = timezone.now()
    founder = Member.objects.get(member_no=ZERO_START_FOUNDER_MEMBER_NO)
    if run is None:
        run = SimulationRun.objects.create(
            run_id=generate_simulation_run_id(),
            plan_revision=revision,
            status=SimulationRun.Status.RUNNING,
            current_day=1,
            max_turns=hours,
            started_at=now,
            ended_at=None,
            failure_summary="",
            metadata={
                "scenario": "zero_start",
                "clock_unit": "hour",
                "current_hour": -1,
                "project_phase": "preparation",
                "founder_member_no": founder.member_no,
                "initial_members": 1,
                "registered_applicants": 0,
                "candidate_members": 0,
                "screened_applicants": 0,
                "partner_applications": 0,
                "startup_gate_satisfied": False,
                "startup_capability_requirements": list(STARTUP_CAPABILITY_REQUIREMENTS),
                "startup_document_signer_requirements": list(STARTUP_DOCUMENT_SIGNER_REQUIREMENTS),
            },
        )
    else:
        run.status = SimulationRun.Status.RUNNING
        run.ended_at = None
        run.max_turns = _metadata_int(run.metadata, "current_hour", -1) + 1 + hours
        run.save(update_fields=["status", "ended_at", "max_turns"])

    world_id = _current_world_id()
    form_driver = HttpFormDriver()
    start_hour = _metadata_int(run.metadata, "current_hour", -1) + 1
    end_hour = start_hour + hours
    applicant_specs = applicant_specs_for_hours(end_hour)
    partner_specs = partner_specs_for_hours(end_hour)
    applications_by_index: dict[int, MemberApplication] = {}
    partner_applications_by_index: dict[int, PartnerApplication] = {}
    for hour in range(start_hour, end_hour):
        applied = [spec for spec in applicant_specs if spec.apply_hour == hour]
        screened = [spec for spec in applicant_specs if spec.screen_hour == hour]
        partner_applied = [spec for spec in partner_specs if spec.apply_hour == hour]
        partner_screened = [spec for spec in partner_specs if spec.screen_hour == hour]
        for spec in applied:
            result = _submit_member_application_via_form(
                driver=form_driver,
                world_id=world_id,
                run=run,
                spec=spec,
                hour=hour,
            )
            if not result.success:
                return create_zero_start_form_interaction_failure(
                    run=run, hour=hour, result=result, simulation_day=_simulation_day(hour),
                )
            applications_by_index[spec.index] = MemberApplication.objects.get(application_id=result.application_id)
        for spec in partner_applied:
            result = _submit_partner_application_via_form(
                driver=form_driver,
                world_id=world_id,
                run=run,
                spec=spec,
                hour=hour,
            )
            if not result.success:
                return create_zero_start_form_interaction_failure(
                    run=run, hour=hour, result=result, simulation_day=_simulation_day(hour),
                )
            partner_applications_by_index[spec.index] = PartnerApplication.objects.get(application_id=result.application_id)
        screening_rows = []
        for spec in screened:
            application = applications_by_index.get(spec.index) or _member_application_for_run(run=run, spec=spec)
            try:
                screening_rows.append(_screen_member_application(application=application, spec=spec, screened_hour=hour))
            except DomainError as exc:
                return create_zero_start_form_interaction_failure(
                    run=run,
                    hour=hour,
                    result=FormSubmissionResult(
                        success=False,
                        path="member_application_review",
                        status_code=0,
                        errors=[str(exc)],
                    ),
                    simulation_day=_simulation_day(hour),
                )
        partner_screening_rows = []
        for spec in partner_screened:
            application = partner_applications_by_index.get(spec.index) or _partner_application_for_run(run=run, spec=spec)
            try:
                partner_screening_rows.append(
                    _screen_partner_application(application=application, spec=spec, screened_hour=hour)
                )
            except DomainError as exc:
                return create_zero_start_form_interaction_failure(
                    run=run,
                    hour=hour,
                    result=FormSubmissionResult(
                        success=False,
                        path="partner_application_review",
                        status_code=0,
                        errors=[str(exc)],
                    ),
                    simulation_day=_simulation_day(hour),
                )

        startup_gate = _startup_gate_summary(run)
        pre_engineering = _pre_engineering_state(run=run, hour=hour, startup_gate=startup_gate)
        candidate_summary = candidate_summary_for_run(run, startup_gate_satisfied=bool(startup_gate["startup_gate_satisfied"]))
        hour_payload = build_hour_payload(
            run=run,
            hour=hour,
            applied=applied,
            partner_applied=partner_applied,
            screening_rows=screening_rows,
            partner_screening_rows=partner_screening_rows,
            candidate_summary=candidate_summary,
            startup_gate=startup_gate,
            pre_engineering=pre_engineering,
            simulation_day=_simulation_day(hour),
            driver_mode=HttpFormDriver.mode,
            candidate_status=APPLICATION_STATUS_CANDIDATE,
        )
        summary = _hour_summary(
            hour=hour,
            applied=applied,
            partner_applied=partner_applied,
            screening_rows=screening_rows,
            partner_screening_rows=partner_screening_rows,
            candidate_summary=candidate_summary,
            startup_gate=startup_gate,
            pre_engineering=pre_engineering,
        )
        create_simulation_turn_and_event(
            run=run,
            title=f"零起点第 {hour} 小时",
            summary=summary,
            simulation_day=_simulation_day(hour),
            severity=Event.Severity.INFO,
            event_type=Event.EventType.SIMULATION_DAY,
            payload=hour_payload,
        )
        run.current_day = _simulation_day(hour)
        run.metadata = {
            **run.metadata,
            "current_hour": hour,
            "startup_gate": startup_gate,
            "project_phase": pre_engineering.get("project_phase", startup_gate.get("project_phase", "preparation")),
            **candidate_summary,
        }
        if pre_engineering:
            run.metadata = {
                **run.metadata,
                "pre_engineering_started_hour": pre_engineering["started_hour"],
                "pre_engineering": pre_engineering,
            }
        run.save(update_fields=["current_day", "metadata"])

    gate = _startup_gate_summary(run)
    pre_engineering = _pre_engineering_state(run=run, hour=end_hour, startup_gate=gate)
    failure = None
    proposal = None
    change_set = None
    pre_engineering_complete = bool(pre_engineering.get("completed"))
    if gate["startup_gate_satisfied"] and pre_engineering_complete:
        run.status = SimulationRun.Status.COMPLETED
        run.ended_at = timezone.now()
        run.failure_summary = ""
    elif gate["startup_gate_satisfied"]:
        run.status = SimulationRun.Status.RUNNING
        run.ended_at = None
        run.failure_summary = "启动门槛已满足，工程前置流程仍在推进。"
    else:
        gate = _startup_gate_summary(run)
        failure = create_zero_start_gate_failure(
            run=run, detected_hour=end_hour, gate=gate,
            simulation_day=_simulation_day(end_hour),
        )
        proposal, change_set = get_or_create_zero_start_feedback(run=run, failure=failure)
        run.status = SimulationRun.Status.RUNNING
        run.ended_at = None
        run.failure_summary = "启动门槛未满足，继续筹备和招募。"
    run.metadata = {
        **run.metadata,
        "completed_hours": end_hour,
        "observation_window_hours": hours,
        "can_continue": not (gate["startup_gate_satisfied"] and pre_engineering_complete),
        "failure_id": failure.failure_id if failure else "",
        "proposal_id": proposal.proposal_id if proposal else "",
        "change_set_id": change_set.change_set_id if change_set else "",
        "startup_gate_satisfied": gate["startup_gate_satisfied"],
        "startup_gate": gate,
        "project_phase": pre_engineering.get("project_phase", gate.get("project_phase", "preparation")),
    }
    if pre_engineering:
        run.metadata = {
            **run.metadata,
            "pre_engineering_started_hour": pre_engineering["started_hour"],
            "pre_engineering": pre_engineering,
        }
    run.save(update_fields=["status", "ended_at", "failure_summary", "metadata"])
    create_simulation_turn_and_event(
        run=run,
        title=observation_window_title(gate=gate, pre_engineering=pre_engineering),
        summary=observation_window_summary(gate=gate, pre_engineering=pre_engineering),
        simulation_day=_simulation_day(end_hour),
        severity=Event.Severity.INFO if (gate["startup_gate_satisfied"] and pre_engineering_complete) else Event.Severity.WARNING,
        event_type=Event.EventType.SIMULATION_DAY,
        payload={
            "scenario": "zero_start",
            "simulation_hour": end_hour,
            "failure_id": failure.failure_id if failure else "",
            "can_continue": not (gate["startup_gate_satisfied"] and pre_engineering_complete),
            "startup_gate": gate,
            "pre_engineering": pre_engineering,
            "candidate_summary": candidate_summary_for_run(run, startup_gate_satisfied=bool(gate["startup_gate_satisfied"])),
            "blockers": startup_gate_blockers(gate),
            "next_actions": combined_next_actions(gate, pre_engineering),
        },
    )
    return {"run": run, "failure": failure, "proposal": proposal, "change_set": change_set}


def _current_world_id() -> str:
    world = get_current_world()
    if world is None:
        return "simulation0001"
    return world.world_id


def _metadata_int(metadata: dict[str, object], key: str, default: int) -> int:
    try:
        return int(metadata.get(key, default))
    except (TypeError, ValueError):
        return default


def _availability_slots_for_spec(spec: ApplicantSpec) -> list[str]:
    if spec.availability_hours_per_week >= 30:
        return ["any_time"]
    if spec.availability_hours_per_week >= 8:
        return ["off_hours", "weekend"]
    return ["weekend"]


def _role_gap_for_spec(spec: ApplicantSpec) -> str:
    capability_names = " ".join(spec.capability_scores.keys())
    if any(keyword in capability_names for keyword in ("文档", "表格", "光伏", "结构")):
        return "developer_ai_engineer"
    if any(keyword in capability_names for keyword in ("搬运", "现场", "安全", "采购")):
        return "service_resident"
    return "community_contributor"


def _motivation_reasons_for_spec(spec: ApplicantSpec) -> list[str]:
    if spec.availability_hours_per_week >= 30:
        return ["build_community"]
    capability_names = " ".join(spec.capability_scores.keys())
    if any(keyword in capability_names for keyword in ("文档", "表格", "光伏", "结构")):
        return ["remote_system_work", "learn_and_practice"]
    if spec.availability_hours_per_week <= 2:
        return ["safe_stable_place"]
    return ["build_community", "other"]


def _submit_member_application_via_form(
    *,
    driver: HttpFormDriver,
    world_id: str,
    run: SimulationRun,
    spec: ApplicantSpec,
    hour: int,
) -> FormSubmissionResult:
    applicant_username = f"applicant-{run.run_id[-6:]}-{spec.index:03d}"
    return driver.submit_member_application(
        world_id=world_id,
        run_id=run.run_id,
        simulation_hour=hour,
        external_ref=f"{run.run_id}:member:{spec.index}",
        data={
            "username": applicant_username,
            "password1": f"simulation-{run.run_id[-6:]}-{spec.index:03d}",
            "password2": f"simulation-{run.run_id[-6:]}-{spec.index:03d}",
            "applicant_name": spec.display_name,
            "contact": f"applicant-{spec.index:03d}@simulation.test",
            "motivation": spec.motivation,
            "availability_hours_per_week": spec.availability_hours_per_week,
            "role_gap": _role_gap_for_spec(spec),
            "availability_slots": _availability_slots_for_spec(spec),
            "motivation_reasons": _motivation_reasons_for_spec(spec),
            "motivation_other_text": spec.motivation,
            "capabilities_text": "\n".join(f"{name}:{score}" for name, score in spec.capability_scores.items()),
            "requested_member_no": applicant_username,
            "confirm_submit": "on",
        },
    )


def _submit_partner_application_via_form(
    *,
    driver: HttpFormDriver,
    world_id: str,
    run: SimulationRun,
    spec: PartnerSpec,
    hour: int,
) -> FormSubmissionResult:
    return driver.submit_partner_application(
        world_id=world_id,
        run_id=run.run_id,
        simulation_hour=hour,
        external_ref=f"{run.run_id}:partner:{spec.index}",
        data={
            "organization_name": spec.organization_name,
            "contact_name": spec.contact_name,
            "contact": f"partner-{spec.index:03d}@simulation.test",
            "service_domains_text": "\n".join(spec.service_domains),
            "can_issue_responsibility_documents": "on" if spec.can_issue_responsibility_documents else "",
            "responsibility_document_domains_text": "\n".join(spec.responsibility_document_domains),
            "qualification_summary": spec.qualification_summary,
            "quote_summary": spec.quote_summary,
            "service_area": spec.service_area,
            "delivery_cycle_days": spec.delivery_cycle_days if spec.delivery_cycle_days is not None else "",
            "constraints": spec.constraints,
        },
    )


def _member_application_for_run(*, run: SimulationRun, spec: ApplicantSpec) -> MemberApplication:
    return MemberApplication.objects.get(metadata__external_ref=f"{run.run_id}:member:{spec.index}")


def _partner_application_for_run(*, run: SimulationRun, spec: PartnerSpec) -> PartnerApplication:
    return PartnerApplication.objects.get(metadata__external_ref=f"{run.run_id}:partner:{spec.index}")


def _screen_member_application(
    *,
    application: MemberApplication,
    spec: ApplicantSpec,
    screened_hour: int,
) -> dict[str, object]:
    decision = screening_decision(spec=spec, screened_hour=screened_hour)
    if decision == APPLICATION_STATUS_CANDIDATE:
        note = "进入候选池：具备可用能力或较高到场时间，但不等于具备文件签署责任。"
    elif decision == APPLICATION_STATUS_STANDBY:
        note = "进入备用池：兴趣明确，但可用时间或能力匹配度不足。"
    elif decision == APPLICATION_STATUS_WITHDREW:
        note = "报名者在筛选截止前主动退出。"
    else:
        note = "项目方暂不接纳：当前能力和可用时间不足以进入候选池。"
    history = list(application.metadata.get("state_history") or [])
    history.append({"hour": screened_hour, "status": decision, "reason": note})
    # Simulation screening decisions are recorded in metadata only --
    # they do NOT mutate MemberApplication.status. The authoritative
    # application status is driven by the member_admission proposal
    # lifecycle (admission_voting → admitted / rejected).
    application.metadata = {
        **application.metadata,
        "batch_id": f"zero-start-{str(application.metadata.get('simulation_run_id', ''))[-6:]}",
        "application_status": decision,
        "screening_status": decision,
        "screened_hour": screened_hour,
        "screening_notes": note,
        "state_history": history,
        "review_note": note,
    }
    application.save(update_fields=["metadata"])
    if application.linked_member_id:
        member = application.linked_member
        member.metadata = {
            **member.metadata,
            "scenario": "zero_start",
            "simulation_run_id": application.metadata.get("simulation_run_id"),
            "applicant_index": spec.index,
            "applied_hour": spec.apply_hour,
            "application_source": "self_media",
            "application_status": decision,
            "screening_status": decision,
            "screened_hour": screened_hour,
            "screening_notes": note,
            "state_history": history,
        }
        member.save(update_fields=["metadata"])
    return {
        "application_id": application.application_id,
        "member_no": application.linked_member.member_no if application.linked_member_id else "",
        "display_name": application.applicant_name,
        "decision": decision,
        "availability_hours_per_week": spec.availability_hours_per_week,
        "capability_scores": spec.capability_scores,
        "document_authority_domains": list(spec.document_authority_domains),
    }


def _screen_partner_application(
    *,
    application: PartnerApplication,
    spec: PartnerSpec,
    screened_hour: int,
) -> dict[str, object]:
    if spec.review_status == PartnerApplication.Status.QUALIFIED and spec.can_issue_responsibility_documents:
        note = "合作方已初筛为可合作：具备责任文件签署能力；后续仍需以具体合同和正式文件固化责任。"
    elif spec.review_status == PartnerApplication.Status.QUALIFIED:
        note = "合作方已初筛为可合作：可提供服务能力，但不承担责任文件签署。"
    else:
        note = "合作方已初筛进入线索池：可作为辅助能力或报价来源，不能直接视为关键责任文件到位。"
    review_partner_application(application=application, status=spec.review_status, review_note=note)
    application.refresh_from_db()
    history = list(application.metadata.get("state_history") or [])
    history.append({"hour": screened_hour, "status": spec.review_status, "reason": note})
    application.metadata = {
        **application.metadata,
        "application_status": spec.review_status,
        "screening_status": spec.review_status,
        "screened_hour": screened_hour,
        "screening_notes": note,
        "state_history": history,
    }
    application.save(update_fields=["metadata"])
    return {
        "application_id": application.application_id,
        "organization_name": application.organization_name,
        "decision": spec.review_status,
        "service_domains": list(spec.service_domains),
        "responsibility_document_domains": list(spec.responsibility_document_domains),
        "can_issue_responsibility_documents": spec.can_issue_responsibility_documents,
    }



def _hour_summary(
    *,
    hour: int,
    applied: list[ApplicantSpec],
    partner_applied: list[PartnerSpec],
    screening_rows: list[dict[str, object]],
    partner_screening_rows: list[dict[str, object]],
    candidate_summary: dict[str, int | bool],
    startup_gate: dict[str, object],
    pre_engineering: dict[str, object],
) -> str:
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
        phrases.append(
            "阶段复盘：报名数量不是启动条件，必须同时满足成员能力矩阵和文件签署方矩阵。"
        )
    if startup_gate["missing_capabilities"]:
        phrases.append(f"能力缺口：{startup_gate['missing_capabilities'][0]['name']}。")
    if startup_gate["missing_document_signers"]:
        phrases.append(f"文件责任缺口：{startup_gate['missing_document_signers'][0]['name']}。")
    if startup_gate["startup_gate_satisfied"]:
        phrases.append("启动门槛已经满足：成员能力矩阵和责任文件签署方矩阵均已覆盖。")
    if pre_engineering:
        phrases.append(_pre_engineering_hour_summary(pre_engineering))
    return " ".join(phrases)



def _pre_engineering_state(
    *,
    run: SimulationRun,
    hour: int,
    startup_gate: dict[str, object],
) -> dict[str, object]:
    if not startup_gate.get("startup_gate_satisfied"):
        return {}
    started_hour = _metadata_int(run.metadata, "pre_engineering_started_hour", hour)
    elapsed_hours = max(hour - started_hour, 0)
    milestones = [
        _pre_engineering_milestone_row(run=run, milestone=milestone, elapsed_hours=elapsed_hours)
        for milestone in PRE_ENGINEERING_MILESTONES
    ]
    completed = all(bool(row["completed"]) for row in milestones)
    selected_site = _selected_site_candidate(elapsed_hours)
    return {
        "project_phase": "pre_engineering_completed" if completed else "pre_engineering",
        "status": "completed" if completed else "running",
        "completed": completed,
        "started_hour": started_hour,
        "elapsed_hours": elapsed_hours,
        "selected_site_code": selected_site["code"] if selected_site else "",
        "candidate_sites": _candidate_site_rows(elapsed_hours),
        "milestones": milestones,
        "completed_milestone_count": len([row for row in milestones if row["completed"]]),
        "pending_milestone_count": len([row for row in milestones if not row["completed"]]),
        "blockers": pre_engineering_blockers(milestones),
        "next_actions": _pre_engineering_next_actions(milestones),
    }


def _pre_engineering_milestone_row(
    *,
    run: SimulationRun,
    milestone: dict[str, object],
    elapsed_hours: int,
) -> dict[str, object]:
    completed = elapsed_hours >= int(milestone["complete_after_hours"])
    document_code = str(milestone.get("document_code") or "")
    signer = _document_signer_for_code(run=run, document_code=document_code) if document_code else {}
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


def _document_signer_for_code(*, run: SimulationRun, document_code: str) -> dict[str, object]:
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


def _candidate_site_rows(elapsed_hours: int) -> list[dict[str, object]]:
    rows = []
    grid_visible = elapsed_hours >= 24
    legal_visible = elapsed_hours >= 48
    for site in PRE_ENGINEERING_SITE_CANDIDATES:
        grid_status = str(site["grid_prescreen"]) if grid_visible else "pending"
        legal_status = str(site["legal_review"]) if legal_visible else "pending"
        shortlisted = grid_status in {"conditional_pass", "needs_follow_up"} and legal_status == "conditional_pass"
        rows.append(
            {
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
            }
        )
    return rows


def _selected_site_candidate(elapsed_hours: int) -> dict[str, object] | None:
    if elapsed_hours < 48:
        return None
    for row in _candidate_site_rows(elapsed_hours):
        if row["shortlisted"]:
            return row
    return None


def _pre_engineering_next_actions(milestones: list[dict[str, object]]) -> list[str]:
    for row in milestones:
        if not row["completed"]:
            return [f"继续推进：{row['name']}。"]
    return ["工程前置责任闭环已形成，可以进入采购、施工、调试和验收计划细化。"]


def _pre_engineering_hour_summary(pre_engineering: dict[str, object]) -> str:
    if pre_engineering.get("status") == "completed":
        selected_site = pre_engineering.get("selected_site_code") or "候选场地"
        return f"工程前置阶段完成：{selected_site} 已通过预筛、附条件租赁审查和责任文件闭环。"
    blockers = pre_engineering.get("blockers") or []
    if blockers:
        return f"工程前置阶段推进中，下一项未完成：{blockers[0]['name']}。"
    return "工程前置阶段推进中。"


def _startup_gate_summary(run: SimulationRun) -> dict[str, object]:
    return startup_gate_summary_for_run(
        run,
        founder_member_no=ZERO_START_FOUNDER_MEMBER_NO,
        capability_requirements=STARTUP_CAPABILITY_REQUIREMENTS,
        responsibility_document_requirements=STARTUP_DOCUMENT_SIGNER_REQUIREMENTS,
    )


def _simulation_day(hour: int) -> int:
    return hour // 24 + 1
