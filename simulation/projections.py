"""Simulation projection layer: candidate pool, startup-gate, and screening queries.

This module separates the *read model* for zero-start simulations from the
simulation engine itself.  The engine (``zero_start.py``) is responsible for
driving virtual subjects through real forms and writing screening metadata.
This module is responsible for *interpreting* that metadata -- assembling
candidate summaries, startup-gate member lists, and capability/signer
matrices -- without scattering ORM queries across the main simulation loop.

Future changes to application schemas or admission semantics should be
absorbed here rather than in the engine.
"""

from __future__ import annotations

from core.models import Member, MemberApplication, PartnerApplication, SimulationRun

# screening-status constants
# These are the values written to MemberApplication.metadata.screening_status
# by zero_start._screen_member_application.  They are NOT authoritative
# MemberApplication.status values.

SCREENING_REGISTERED = "registered"
SCREENING_CANDIDATE = "candidate"
SCREENING_STANDBY = "standby"
SCREENING_REJECTED = "rejected"
SCREENING_WITHDREW = "withdrew"

_SCREENING_APPLIED = {SCREENING_CANDIDATE, SCREENING_STANDBY, SCREENING_REJECTED, SCREENING_WITHDREW}


# per-application helpers


def screening_status_for(application: MemberApplication) -> str:
    """Return the simulation screening status for *application*.

    Falls back to ``SCREENING_REGISTERED`` when no screening metadata exists.
    """
    return str((application.metadata or {}).get("screening_status") or SCREENING_REGISTERED)


def is_screening_candidate(application: MemberApplication) -> bool:
    return screening_status_for(application) == SCREENING_CANDIDATE


def is_screening_standby(application: MemberApplication) -> bool:
    return screening_status_for(application) == SCREENING_STANDBY


def is_screened(application: MemberApplication) -> bool:
    return screening_status_for(application) in _SCREENING_APPLIED


# queryset helpers


def member_applications_for_run(run: SimulationRun):
    return MemberApplication.objects.filter(metadata__simulation_run_id=run.run_id)


def partner_applications_for_run(run: SimulationRun):
    return PartnerApplication.objects.filter(metadata__simulation_run_id=run.run_id)


def candidate_applications_for_run(run: SimulationRun):
    return member_applications_for_run(run).filter(
        metadata__screening_status=SCREENING_CANDIDATE
    )


def candidate_members_for_run(run: SimulationRun, *, founder_member_no: str | None = None) -> list[Member]:
    """Return the candidate members for *run*: all linked members whose
    application has ``screening_status=candidate``.

    When *founder_member_no* is provided the founder is placed at the
    front of the list so the startup-gate capability/signer matrices
    always include the founder.  Without it only the candidates are
    returned.

    Applications without a ``linked_member`` are silently skipped so a
    missing FK does not crash the startup-gate pipeline.
    """
    founder = (
        Member.objects.filter(member_no=founder_member_no).first()
        if founder_member_no
        else None
    )
    applicant_qs = Member.objects.filter(
        member_applications__metadata__simulation_run_id=run.run_id,
        member_applications__metadata__screening_status=SCREENING_CANDIDATE,
    ).order_by("member_no")
    result: list[Member] = []
    if founder:
        result.append(founder)
    result.extend(applicant_qs)
    return result


# summaries


def candidate_summary_for_run(
    run: SimulationRun,
    *,
    startup_gate_satisfied: bool = False,
) -> dict[str, int | bool]:
    """Return per-category screening counts for *run*.

    The caller should pass a startup gate result that has already been
    computed by the scenario driver so this summary does not trigger
    gate evaluation itself.
    """
    applicants = member_applications_for_run(run)
    partners = partner_applications_for_run(run)
    document_signer_partners = _qualified_document_signer_partners_for_run(run)
    return {
        "registered_applicants": applicants.count(),
        "candidate_members": applicants.filter(
            metadata__screening_status=SCREENING_CANDIDATE
        ).count(),
        "standby_applicants": applicants.filter(
            metadata__screening_status=SCREENING_STANDBY
        ).count(),
        "rejected_applicants": applicants.filter(
            metadata__screening_status=SCREENING_REJECTED
        ).count(),
        "withdrawn_applicants": applicants.filter(
            metadata__screening_status=SCREENING_WITHDREW
        ).count(),
        "screened_applicants": applicants.exclude(
            metadata__screening_status=None
        ).count(),
        "partner_applications": partners.count(),
        "qualified_partners": partners.filter(
            status=PartnerApplication.Status.QUALIFIED
        ).count(),
        "standby_partners": partners.filter(
            status=PartnerApplication.Status.STANDBY
        ).count(),
        "responsibility_document_signer_partners": len(document_signer_partners),
        "startup_gate_satisfied": startup_gate_satisfied,
    }


def _qualified_document_signer_partners_for_run(run: SimulationRun) -> list[PartnerApplication]:
    return list(
        PartnerApplication.objects.filter(
            metadata__simulation_run_id=run.run_id,
            status=PartnerApplication.Status.QUALIFIED,
            can_issue_responsibility_documents=True,
        ).order_by("application_id")
    )
