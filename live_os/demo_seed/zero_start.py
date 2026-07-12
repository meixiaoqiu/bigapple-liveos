"""Zero-start simulation seed data.

This template intentionally starts before a mature operation exists: one
founder, no candidate pool, and only a minimal plan baseline that a simulation
run can attach to.
"""

from __future__ import annotations

from django.utils import timezone

from core.member_roles import ROLE_BIG_APPLE_MEMBER, ROLE_GOVERNANCE_MEMBER, ensure_member_role, ensure_role_assignment
from core.models import Member, PlanRevision, ProjectPlan

from .helpers import actor, upsert


ZERO_START_PLAN_ID = "plan-zero-start"
ZERO_START_REVISION_ID = "plan-zero-start-rev-v0_0_1"
ZERO_START_FOUNDER_MEMBER_NO = "founder-0001"


def seed_zero_start(*, now=None) -> dict[str, object]:
    """Create the minimal baseline for a true zero-start simulation."""

    now = now or timezone.now()
    founder, _ = upsert(
        Member,
        {"member_no": ZERO_START_FOUNDER_MEMBER_NO},
        {
            "display_name": "大苹果发起人",
            "status": Member.Status.ACTIVE,
            "batch_id": "zero-start",
            "joined_simulation_day": 0,
            "credit_floor": -500,
            "profile": {
                "public_spirit": 95,
                "rule_compliance": 90,
                "availability_hours_per_week": 50,
                "skills": {"发起": 90, "沟通": 82, "文档": 76, "组织": 70},
            },
            "created_at": now,
            "metadata": {
                "seed": True,
                "template": "zero_start",
                "note": "零起点仿真只预置一个发起人。",
            },
        },
    )
    ensure_role_assignment(founder, ensure_member_role(ROLE_BIG_APPLE_MEMBER))
    ensure_role_assignment(founder, ensure_member_role(ROLE_GOVERNANCE_MEMBER))

    plan, _ = upsert(
        ProjectPlan,
        {"plan_id": ZERO_START_PLAN_ID},
        {
            "name": "大苹果零起点倡议",
            "status": ProjectPlan.Status.ACTIVE,
            "description": "从只有一个发起人开始，验证自媒体报名筛选、候选池、能力矩阵和文件签署方矩阵。",
            "target_location": "未确定",
            "owner": actor(founder.member_no, founder.display_name or founder.member_no, "virtual_member"),
            "created_at": now,
            "updated_at": now,
            "metadata": {"seed": True, "template": "zero_start"},
        },
    )
    revision_defaults = {
            "plan": plan,
            "revision_code": "v0.0.1-zero-start",
            "status": PlanRevision.Status.PUBLISHED,
            "title": "零起点仿真基线",
            "change_summary": "只定义发起目标，不预置完整成员池、资源、任务或成熟工程计划。",
            "created_at": now,
            "created_by": actor(founder.member_no, founder.display_name or founder.member_no, "virtual_member"),
            "published_at": now,
            "metadata": {"seed": True, "template": "zero_start"},
    }
    revision, created = PlanRevision.objects.get_or_create(
        revision_id=ZERO_START_REVISION_ID,
        defaults=revision_defaults,
    )
    if not created:
        update_fields = []
        static_updates = {
            "plan": plan,
            "revision_code": "v0.0.1-zero-start",
            "title": "零起点仿真基线",
            "change_summary": "只定义发起目标，不预置完整成员池、资源、任务或成熟工程计划。",
            "created_by": actor(founder.member_no, founder.display_name or founder.member_no, "virtual_member"),
            "metadata": {"seed": True, "template": "zero_start"},
        }
        for field, value in static_updates.items():
            if getattr(revision, field) != value:
                setattr(revision, field, value)
                update_fields.append(field)
        if not PlanRevision.objects.filter(plan=plan, status=PlanRevision.Status.PUBLISHED).exists():
            revision.status = PlanRevision.Status.PUBLISHED
            revision.published_at = revision.published_at or now
            update_fields.extend(["status", "published_at"])
        if update_fields:
            revision.save(update_fields=sorted(set(update_fields)))
    return {"founder": founder, "plan": plan, "revision": revision}
