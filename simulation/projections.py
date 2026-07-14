"""Simulation projection layer: candidate pool, startup-gate, and screening queries.

This module separates the *read model* for zero-start simulations from the
simulation engine itself.  The engine (``zero_start.py``) is responsible for
driving virtual subjects through real forms and writing screening metadata.
This module is responsible for *interpreting* that metadata -- assembling
candidate summaries, startup-gate member lists, capability/signer coverage
matrices, and partner snapshots -- without scattering ORM queries across the
main simulation loop.

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


def qualified_document_signer_partners_for_run(run: SimulationRun) -> list[PartnerApplication]:
    """Return all QUALIFIED partner applications for *run* that can issue
    responsibility documents.
    """
    return list(
        PartnerApplication.objects.filter(
            metadata__simulation_run_id=run.run_id,
            status=PartnerApplication.Status.QUALIFIED,
            can_issue_responsibility_documents=True,
        ).order_by("application_id")
    )


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
    document_signer_partners = qualified_document_signer_partners_for_run(run)
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


# member / partner snapshots (shared read-model helpers)


def member_skills(member: Member) -> dict[str, int]:
    """Return the skills dict from *member*'s profile, suitable for
    capability-coverage matching.
    """
    return {str(k): int(v or 0) for k, v in (member.profile.get("skills") or {}).items()}


def member_snapshot(member: Member) -> dict[str, object]:
    return {
        "member_no": member.member_no,
        "display_name": member.display_name or member.member_no,
        "skills": member.profile.get("skills") or {},
    }


def partner_snapshot(application: PartnerApplication) -> dict[str, object]:
    return {
        "application_id": application.application_id,
        "organization_name": application.organization_name,
        "responsibility_document_domains": application.responsibility_document_domains,
    }


# startup-gate coverage and summary


def skills_match_requirement(skills: dict[str, int], requirement: dict[str, object]) -> bool:
    aliases = [str(a) for a in requirement["skill_aliases"]]
    return any(int(skills.get(a, 0) or 0) >= 50 for a in aliases)


def capability_coverage_for_members(
    members: list[Member],
    capability_requirements: tuple[dict[str, object], ...],
) -> list[dict[str, object]]:
    """Return one coverage row per capability requirement.

    Each row includes the requirement code/name/min_count, the list of
    member snapshots that satisfy it, and the computed missing_count.
    """
    rows: list[dict[str, object]] = []
    for requirement in capability_requirements:
        covered = [
            member_snapshot(m)
            for m in members
            if skills_match_requirement(member_skills(m), requirement)
        ]
        required = int(requirement["min_count"])
        rows.append({
            "code": requirement["code"],
            "name": requirement["name"],
            "required_count": required,
            "covered_count": len(covered),
            "missing_count": max(required - len(covered), 0),
            "need_written_document": False,
            "covered_by": covered,
        })
    return rows


def document_signer_coverage_for_partners(
    members: list[Member],
    partner_applications: list[PartnerApplication],
    responsibility_document_requirements: tuple[dict[str, object], ...],
) -> list[dict[str, object]]:
    """Return one coverage row per responsibility-document requirement.

    Each row checks member ``document_authority_domains`` and partner
    ``responsibility_document_domains`` for the requirement code.
    """
    rows: list[dict[str, object]] = []
    for requirement in responsibility_document_requirements:
        code = str(requirement["code"])
        covered: list[dict[str, object]] = [
            member_snapshot(m)
            for m in members
            if code in (m.profile.get("document_authority_domains") or [])
        ]
        covered.extend(
            partner_snapshot(a)
            for a in partner_applications
            if code in (a.responsibility_document_domains or [])
        )
        rows.append({
            "code": code,
            "name": requirement["name"],
            "required_count": 1,
            "covered_count": len(covered),
            "missing_count": max(1 - len(covered), 0),
            "need_written_document": True,
            "document_examples": requirement["document_examples"],
            "acceptable_signers": requirement["acceptable_signers"],
            "covered_by": covered,
        })
    return rows


def startup_gate_summary_for_run(
    run: SimulationRun,
    *,
    founder_member_no: str,
    capability_requirements: tuple[dict[str, object], ...],
    responsibility_document_requirements: tuple[dict[str, object], ...],
) -> dict[str, object]:
    """Assemble the startup-gate summary for *run*.

    Returns a dict structurally identical to the old
    ``_startup_gate_summary`` so downstream payloads and assertions
    are unaffected:

    - startup_gate_satisfied
    - capability_coverage
    - document_signer_coverage
    - missing_capabilities
    - missing_document_signers
    """
    members = candidate_members_for_run(run, founder_member_no=founder_member_no)
    partner_applications = qualified_document_signer_partners_for_run(run)
    capability_coverage = capability_coverage_for_members(members, capability_requirements)
    document_signer_coverage = document_signer_coverage_for_partners(
        members, partner_applications, responsibility_document_requirements
    )
    missing_capabilities = [r for r in capability_coverage if r["missing_count"] > 0]
    missing_document_signers = [r for r in document_signer_coverage if r["missing_count"] > 0]
    satisfied = not missing_capabilities and not missing_document_signers
    return {
        "project_phase": "ready_to_start" if satisfied else "preparation",
        "startup_gate_satisfied": satisfied,
        "capability_coverage": capability_coverage,
        "document_signer_coverage": document_signer_coverage,
        "missing_capabilities": missing_capabilities,
        "missing_document_signers": missing_document_signers,
    }
