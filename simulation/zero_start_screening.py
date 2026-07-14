"""Zero-start simulation: screening metadata writers.

Writes simulation screening decisions to MemberApplication / PartnerApplication
metadata. Member screening does NOT mutate MemberApplication.status; partner
screening still updates PartnerApplication.status through the existing review
service. Does NOT import zero_start.py.
"""

from __future__ import annotations

from core.application_services import review_partner_application
from core.models import MemberApplication, PartnerApplication, SimulationRun
from .zero_start_strategy import (
    APPLICATION_STATUS_CANDIDATE,
    APPLICATION_STATUS_REJECTED,
    APPLICATION_STATUS_STANDBY,
    APPLICATION_STATUS_WITHDREW,
    ApplicantSpec,
    PartnerSpec,
    screening_decision,
)


def member_application_for_run(*, run: SimulationRun, spec: ApplicantSpec) -> MemberApplication:
    return MemberApplication.objects.get(metadata__external_ref=f"{run.run_id}:member:{spec.index}")


def partner_application_for_run(*, run: SimulationRun, spec: PartnerSpec) -> PartnerApplication:
    return PartnerApplication.objects.get(metadata__external_ref=f"{run.run_id}:partner:{spec.index}")


def screen_member_application(
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


def screen_partner_application(
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
