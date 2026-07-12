"""Member and role demo seed data."""

from __future__ import annotations

from core.governance_setup import ensure_governance_admin_role
from core.member_roles import (
    ROLE_BIG_APPLE_MEMBER,
    ROLE_CANDIDATE,
    ROLE_CONTRIBUTOR,
    ROLE_FORMAL_MEMBER,
    ROLE_GOVERNANCE_MEMBER,
    ensure_member_role,
    ensure_role_assignment,
)
from core.models import Member

from .helpers import upsert


def seed_members(*, now, mark) -> dict[str, Member]:
    governance_setup = ensure_governance_admin_role()
    admin_member = mark(
        upsert(
            Member,
            {"member_no": "member-admin-0001"},
            {
                "status": Member.Status.ACTIVE,
                "batch_id": "batch-opening",
                "joined_simulation_day": 1,
                "credit_floor": -500,
                "profile": {
                    "public_spirit": 90,
                    "rule_compliance": 92,
                    "skills": {"治理": 88, "安全": 74, "电工": 68, "给排水": 65, "卫生": 64},
                },
                "created_at": now,
                "metadata": {"seed": True, "note": "演示治理成员"},
            },
        )
    )
    member_1 = mark(
        upsert(
            Member,
            {"member_no": "mem-0001"},
            {
                "status": Member.Status.ADMITTED,
                "batch_id": "batch-opening",
                "joined_simulation_day": 1,
                "credit_floor": -300,
                "profile": {
                    "health": 82,
                    "stamina": 76,
                    "fatigue": 18,
                    "satisfaction": 64,
                    "fairness_sensitivity": 71,
                    "public_spirit": 68,
                    "rule_compliance": 74,
                    "exit_risk": 8,
                    "skills": {
                        "cooking": 62,
                        "cleaning": 55,
                        "厨房建设": 75,
                        "食品安全": 70,
                        "采购": 65,
                    },
                },
                "created_at": now,
                "metadata": {"seed": True, "note": "演示成员，已完成做饭任务"},
            },
        )
    )
    member_2 = mark(
        upsert(
            Member,
            {"member_no": "mem-0002"},
            {
                "status": Member.Status.ADMITTED,
                "batch_id": "batch-opening",
                "joined_simulation_day": 1,
                "credit_floor": -300,
                "profile": {
                    "health": 71,
                    "stamina": 58,
                    "fatigue": 64,
                    "satisfaction": 49,
                    "fairness_sensitivity": 88,
                    "public_spirit": 43,
                    "rule_compliance": 60,
                    "exit_risk": 22,
                    "skills": {"cleaning": 70, "warehouse": 41, "公共卫生": 68, "仓储": 54},
                },
                "created_at": now,
                "metadata": {"seed": True, "note": "演示成员，发起过申诉"},
            },
        )
    )
    member_3 = mark(
        upsert(
            Member,
            {"member_no": "mem-0003"},
            {
                "status": Member.Status.SUSPENDED,
                "batch_id": "batch-opening",
                "joined_simulation_day": 1,
                "credit_floor": -300,
                "profile": {
                    "health": 66,
                    "stamina": 44,
                    "fatigue": 78,
                    "satisfaction": 37,
                    "fairness_sensitivity": 82,
                    "public_spirit": 48,
                    "rule_compliance": 52,
                    "exit_risk": 35,
                    "skills": {
                        "repair": 73,
                        "warehouse": 58,
                        "维修": 73,
                        "仓储": 58,
                        "给排水": 70,
                        "电工": 65,
                        "安全": 62,
                    },
                },
                "created_at": now,
                "metadata": {"seed": True, "note": "演示被暂停成员，涉及异常任务和申诉"},
            },
        )
    )
    candidate_member = mark(
        upsert(
            Member,
            {"member_no": "candidate-0001"},
            {
                "status": Member.Status.PENDING_REVIEW,
                "batch_id": "batch-candidate",
                "joined_simulation_day": None,
                "credit_floor": -100,
                "profile": {"training": 45, "public_spirit": 61, "rule_compliance": 69},
                "created_at": now,
                "metadata": {"seed": True, "note": "演示预备成员"},
            },
        )
    )

    for member, role_name in (
        (admin_member, ROLE_GOVERNANCE_MEMBER),
        (member_1, ROLE_CONTRIBUTOR),
        (member_2, ROLE_CONTRIBUTOR),
        (member_3, ROLE_FORMAL_MEMBER),
        (candidate_member, ROLE_CANDIDATE),
    ):
        ensure_role_assignment(member, ensure_member_role(ROLE_BIG_APPLE_MEMBER))
        ensure_role_assignment(member, ensure_member_role(role_name))
    ensure_role_assignment(admin_member, governance_setup["role"])
    return {
        "admin": admin_member,
        "member_1": member_1,
        "member_2": member_2,
        "member_3": member_3,
        "candidate": candidate_member,
    }
