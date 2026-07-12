"""Capacity assessment demo seed data."""

from __future__ import annotations

from datetime import timedelta

from core.models import CapacityAssessment, Ruleset

from .helpers import upsert


def seed_capacity(*, now, mark, ruleset: Ruleset) -> None:
    mark(
        upsert(
            CapacityAssessment,
            {"assessment_id": "capacity-0001"},
            {
                "simulation_day": 7,
                "current_formal_members": 100,
                "current_candidate_members": 900,
                "maximum_admissible_members": 130,
                "recommended_new_members": 20,
                "bottlenecks": ["canteen", "hygiene", "high_load_roles"],
                "risk_indicators": {
                    "beds_available": 42,
                    "canteen_load": 82,
                    "task_gap": 18,
                    "average_satisfaction": 61,
                    "average_fatigue": 67,
                    "open_disputes": 4,
                    "exit_risk_members": 9,
                },
                "reasons": [
                    "食堂承载接近风险阈值。",
                    "公共清洁任务已连续三天缺人。",
                ],
                "rule_version": ruleset.version,
                "created_at": now + timedelta(days=6),
                "metadata": {"seed": True},
            },
        )
    )
    mark(
        upsert(
            CapacityAssessment,
            {"assessment_id": "capacity-0002"},
            {
                "simulation_day": 10,
                "current_formal_members": 100,
                "current_candidate_members": 900,
                "maximum_admissible_members": 112,
                "recommended_new_members": 0,
                "bottlenecks": ["medicine", "repair_capacity", "open_disputes"],
                "risk_indicators": {
                    "beds_available": 42,
                    "medicine_stock": 18,
                    "repair_backlog": 7,
                    "task_gap": 26,
                    "average_satisfaction": 55,
                    "average_fatigue": 72,
                    "open_disputes": 2,
                    "exit_risk_members": 14,
                },
                "reasons": [
                    "药品库存低于预警线，暂停新增接纳。",
                    "维修类任务积压，关键基础设施存在风险。",
                    "仍有仓库盘点争议未关闭。",
                ],
                "rule_version": ruleset.version,
                "created_at": now + timedelta(days=9),
                "metadata": {"seed": True, "scenario": "resource_pressure"},
            },
        )
    )
