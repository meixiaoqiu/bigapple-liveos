"""Read-only real-world snapshots used as simulation inputs."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db.models import Sum

from core.exceptions import DomainError
from core.member_roles import ROLE_CANDIDATE, member_role_filter
from core.models import CapacityAssessment, Member, PlanRevision, ProjectPlan, Resource


def decimal_from_metadata(value: object, default: str = "0") -> Decimal:
    """Read a Decimal from JSON metadata without trusting its stored type."""

    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def active_plan_revision() -> PlanRevision:
    """Return the current published plan revision used by observer simulations."""

    active_plan = ProjectPlan.objects.filter(status=ProjectPlan.Status.ACTIVE).order_by("plan_id").first()
    if active_plan is None:
        raise DomainError("缺少执行中的主线计划，无法启动自动模拟。")
    revision = (
        active_plan.revisions.filter(status=PlanRevision.Status.PUBLISHED)
        .order_by("-published_at", "-created_at", "revision_code")
        .first()
    )
    if revision is None:
        revision = active_plan.revisions.order_by("-created_at", "revision_code").first()
    if revision is None:
        raise DomainError("执行计划缺少计划版本，无法启动自动模拟。")
    return revision


def latest_capacity_snapshot() -> CapacityAssessment | None:
    return CapacityAssessment.objects.order_by("-simulation_day", "-created_at").first()


def simulation_start_day() -> int:
    latest = latest_capacity_snapshot()
    return latest.simulation_day if latest else 1


def simulation_available_budget() -> Decimal:
    total = (
        Resource.objects.filter(resource_type=Resource.ResourceType.CASH).aggregate(total=Sum("current_stock"))["total"]
        or Decimal("0")
    )
    return Decimal(total)


def simulation_available_people() -> int:
    latest = latest_capacity_snapshot()
    if latest:
        return latest.current_formal_members
    return (
        Member.objects.filter(status__in=[Member.Status.ADMITTED, Member.Status.ACTIVE])
        .exclude(member_role_filter(ROLE_CANDIDATE))
        .count()
    )


def normalize_skill(skill: object) -> str:
    return str(skill).strip().lower()


def simulation_available_skills() -> set[str]:
    """Collect current member skills from profile JSON for plan feasibility checks."""

    skills: set[str] = set()
    members = Member.objects.filter(status__in=[Member.Status.ADMITTED, Member.Status.ACTIVE])
    for member in members:
        profile_skills = member.profile.get("skills", {})
        if isinstance(profile_skills, dict):
            skills.update(normalize_skill(skill_name) for skill_name, value in profile_skills.items() if value)
        elif isinstance(profile_skills, list):
            skills.update(normalize_skill(skill_name) for skill_name in profile_skills)
        skill_tags = member.profile.get("skill_tags", [])
        if isinstance(skill_tags, list):
            skills.update(normalize_skill(skill_name) for skill_name in skill_tags)
    return {skill for skill in skills if skill}


def latest_fatigue_score() -> Decimal:
    latest = latest_capacity_snapshot()
    if latest:
        return decimal_from_metadata(latest.risk_indicators.get("average_fatigue"), default="0")
    fatigue_scores = [
        decimal_from_metadata(member.profile.get("fatigue"), default="0")
        for member in Member.objects.filter(status__in=[Member.Status.ADMITTED, Member.Status.ACTIVE])
    ]
    if not fatigue_scores:
        return Decimal("0")
    return sum(fatigue_scores, Decimal("0")) / Decimal(len(fatigue_scores))
