"""Zero-start simulation: form-submission adapters.

Member applications are submitted through the real workspace form flow
(/register/ → /workspace/apply/).  Partner applications use a service
adapter because /apply/partner/ has been removed; the partner system
will be designed separately in a future iteration.
"""

from __future__ import annotations

from core.models import SimulationRun
from .form_drivers import FormSubmissionResult, HttpFormDriver
from .zero_start_strategy import ApplicantSpec, PartnerSpec


def availability_slots_for_spec(spec: ApplicantSpec) -> list[str]:
    if spec.availability_hours_per_week >= 30:
        return ["any_time"]
    if spec.availability_hours_per_week >= 8:
        return ["off_hours", "weekend"]
    return ["weekend"]


def role_gap_for_spec(spec: ApplicantSpec) -> str:
    capability_names = " ".join(spec.capability_scores.keys())
    if any(kw in capability_names for kw in ("文档", "表格", "光伏", "结构")):
        return "ai_engineer"
    if any(kw in capability_names for kw in ("搬运", "现场", "安全", "采购")):
        return "life_service"
    return "content_recorder"


def motivation_reasons_for_spec(spec: ApplicantSpec) -> list[str]:
    if spec.availability_hours_per_week >= 30:
        return ["build_community"]
    capability_names = " ".join(spec.capability_scores.keys())
    if any(kw in capability_names for kw in ("文档", "表格", "光伏", "结构")):
        return ["remote_system_work", "learn_and_practice"]
    if spec.availability_hours_per_week <= 2:
        return ["safe_stable_place"]
    return ["build_community", "other"]


def submit_member_application_via_form(
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
            "role_gap": role_gap_for_spec(spec),
            "availability_slots": availability_slots_for_spec(spec),
            "motivation_reasons": motivation_reasons_for_spec(spec),
            "motivation_other_text": spec.motivation,
            "capabilities_text": "\n".join(
                f"{name}:{score}" for name, score in spec.capability_scores.items()
            ),
            "requested_member_no": applicant_username,
            "confirm_submit": "on",
        },
    )


def submit_partner_application_via_form(
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
