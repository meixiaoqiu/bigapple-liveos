"""Hour-level zero-start application and startup-gate simulation.

Orchestration layer: run lifecycle, hourly loop, form submission, screening,
observation, feedback, and pre-engineering coordination.
"""

from __future__ import annotations

from django.utils import timezone

from core.db import atomic_for_model
from core.exceptions import DomainError
from core.models import (
    Event,
    Member,
    MemberApplication,
    PartnerApplication,
    PlanRevision,
    ProjectPlan,
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
from .ids import generate_simulation_run_id
from .projections import candidate_summary_for_run, startup_gate_summary_for_run
from .run_state import create_simulation_turn_and_event
from .zero_start_feedback import (
    create_zero_start_form_interaction_failure,
    create_zero_start_gate_failure,
    get_or_create_zero_start_feedback,
)
from .zero_start_form_submission import (
    submit_member_application_via_form,
    submit_partner_application_via_form,
)
from .zero_start_observations import (
    build_hour_payload,
    build_hour_summary,
    combined_next_actions,
    observation_window_summary,
    observation_window_title,
    startup_gate_blockers,
)
from .zero_start_pre_engineering import (
    pre_engineering_hour_summary,
    pre_engineering_state,
)
from .zero_start_screening import (
    member_application_for_run,
    partner_application_for_run,
    screen_member_application,
    screen_partner_application,
)
from .zero_start_strategy import (
    APPLICATION_STATUS_CANDIDATE,
    ApplicantSpec,
    PartnerSpec,
    applicant_specs_for_hours,
    partner_specs_for_hours,
    STARTUP_CAPABILITY_REQUIREMENTS,
    STARTUP_DOCUMENT_SIGNER_REQUIREMENTS,
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
    founder = _zero_start_founder(revision)
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
        applied = [s for s in applicant_specs if s.apply_hour == hour]
        screened = [s for s in applicant_specs if s.screen_hour == hour]
        partner_applied = [s for s in partner_specs if s.apply_hour == hour]
        partner_screened = [s for s in partner_specs if s.screen_hour == hour]
        for spec in applied:
            result = submit_member_application_via_form(
                driver=form_driver, world_id=world_id, run=run, spec=spec, hour=hour,
            )
            if not result.success:
                return create_zero_start_form_interaction_failure(
                    run=run, hour=hour, result=result, simulation_day=_simulation_day(hour),
                )
            applications_by_index[spec.index] = MemberApplication.objects.get(application_id=result.application_id)
        for spec in partner_applied:
            result = submit_partner_application_via_form(
                driver=form_driver, world_id=world_id, run=run, spec=spec, hour=hour,
            )
            if not result.success:
                return create_zero_start_form_interaction_failure(
                    run=run, hour=hour, result=result, simulation_day=_simulation_day(hour),
                )
            partner_applications_by_index[spec.index] = PartnerApplication.objects.get(application_id=result.application_id)
        screening_rows = []
        for spec in screened:
            application = applications_by_index.get(spec.index) or member_application_for_run(run=run, spec=spec)
            try:
                screening_rows.append(screen_member_application(application=application, spec=spec, screened_hour=hour))
            except DomainError as exc:
                return create_zero_start_form_interaction_failure(
                    run=run, hour=hour,
                    result=FormSubmissionResult(success=False, path="member_application_review", status_code=0, errors=[str(exc)]),
                    simulation_day=_simulation_day(hour),
                )
        partner_screening_rows = []
        for spec in partner_screened:
            application = partner_applications_by_index.get(spec.index) or partner_application_for_run(run=run, spec=spec)
            try:
                partner_screening_rows.append(
                    screen_partner_application(application=application, spec=spec, screened_hour=hour)
                )
            except DomainError as exc:
                return create_zero_start_form_interaction_failure(
                    run=run, hour=hour,
                    result=FormSubmissionResult(success=False, path="partner_application_review", status_code=0, errors=[str(exc)]),
                    simulation_day=_simulation_day(hour),
                )

        startup_gate = _startup_gate_summary(run)
        pre_engineering = pre_engineering_state(run=run, hour=hour, startup_gate=startup_gate)
        candidate_summary = candidate_summary_for_run(run, startup_gate_satisfied=bool(startup_gate["startup_gate_satisfied"]))
        hour_payload = build_hour_payload(
            run=run, hour=hour,
            applied=applied, partner_applied=partner_applied,
            screening_rows=screening_rows, partner_screening_rows=partner_screening_rows,
            candidate_summary=candidate_summary, startup_gate=startup_gate, pre_engineering=pre_engineering,
            simulation_day=_simulation_day(hour),
            driver_mode=HttpFormDriver.mode,
            candidate_status=APPLICATION_STATUS_CANDIDATE,
        )
        summary = build_hour_summary(
            hour=hour,
            applied=applied, partner_applied=partner_applied,
            screening_rows=screening_rows, partner_screening_rows=partner_screening_rows,
            candidate_summary=candidate_summary, startup_gate=startup_gate, pre_engineering=pre_engineering,
            pre_engineering_summary=pre_engineering_hour_summary(pre_engineering) if pre_engineering else "",
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
    pre_engineering = pre_engineering_state(run=run, hour=end_hour, startup_gate=gate)
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


def _startup_gate_summary(run: SimulationRun) -> dict[str, object]:
    return startup_gate_summary_for_run(
        run,
        founder_member_no=_founder_member_no_for_run(run),
        capability_requirements=STARTUP_CAPABILITY_REQUIREMENTS,
        responsibility_document_requirements=STARTUP_DOCUMENT_SIGNER_REQUIREMENTS,
    )


def _zero_start_founder(revision: PlanRevision) -> Member:
    founder_no = ""
    if isinstance(revision.created_by, dict):
        founder_no = str(revision.created_by.get("actor_id") or "").strip()
    if not founder_no and isinstance(revision.plan.owner, dict):
        founder_no = str(revision.plan.owner.get("actor_id") or "").strip()
    founder_no = founder_no or ZERO_START_FOUNDER_MEMBER_NO
    return Member.objects.get(member_no=founder_no)


def _founder_member_no_for_run(run: SimulationRun) -> str:
    founder_no = str((run.metadata or {}).get("founder_member_no") or "").strip()
    if founder_no:
        return founder_no
    return _zero_start_founder(run.plan_revision).member_no


def _simulation_day(hour: int) -> int:
    return hour // 24 + 1
