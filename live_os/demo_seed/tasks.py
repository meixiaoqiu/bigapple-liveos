"""Task demo seed data."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from core.models import Ruleset, Task

from .helpers import actor, upsert


def seed_tasks(*, now, mark, ruleset: Ruleset, plan_nodes: dict, members: dict) -> dict[str, Task]:
    member_1 = members["member_1"]
    member_2 = members["member_2"]
    member_3 = members["member_3"]
    task_open = mark(
        upsert(
            Task,
            {"task_id": "task-0001"},
            {
                "title": "准备今日午餐",
                "task_type": Task.TaskType.COOKING,
                "status": Task.Status.OPEN,
                "standard_hours": Decimal("3.50"),
                "base_points": 30,
                "role_coefficient": Decimal("1.200"),
                "physical_load": Decimal("45"),
                "dirty_level": Decimal("30"),
                "psychological_load": Decimal("35"),
                "urgency": Decimal("70"),
                "can_be_delayed": False,
                "requires_review": True,
                "failure_consequence": Task.FailureConsequence.HIGH,
                "assignee_member": None,
                "plan_node": plan_nodes["B1"],
                "rule_version": ruleset.version,
                "created_at": now,
                "due_at": now + timedelta(hours=4),
                "submitted_at": None,
                "reviewed_at": None,
                "metadata": {"seed": True, "simulation_day": 1},
            },
        )
    )
    task_done = mark(
        upsert(
            Task,
            {"task_id": "task-0002"},
            {
                "title": "清理公共厨房",
                "task_type": Task.TaskType.PUBLIC_CLEANING,
                "status": Task.Status.ACCEPTED,
                "standard_hours": Decimal("2.00"),
                "base_points": 20,
                "role_coefficient": Decimal("1.000"),
                "physical_load": Decimal("55"),
                "dirty_level": Decimal("76"),
                "psychological_load": Decimal("42"),
                "urgency": Decimal("64"),
                "can_be_delayed": False,
                "requires_review": True,
                "failure_consequence": Task.FailureConsequence.MEDIUM,
                "assignee_member": member_1,
                "plan_node": plan_nodes["B5"],
                "rule_version": ruleset.version,
                "created_at": now,
                "due_at": now + timedelta(hours=2),
                "submitted_at": now + timedelta(hours=1),
                "reviewed_at": now + timedelta(hours=2),
                "metadata": {"seed": True, "simulation_day": 1, "labor_note": "已完成厨房台面和地面清理。"},
            },
        )
    )
    mark(
        upsert(
            Task,
            {"task_id": "task-0003"},
            {
                "title": "整理临时仓库货架",
                "task_type": Task.TaskType.WAREHOUSE,
                "status": Task.Status.PENDING_REVIEW,
                "standard_hours": Decimal("2.50"),
                "base_points": 24,
                "role_coefficient": Decimal("1.100"),
                "physical_load": Decimal("62"),
                "dirty_level": Decimal("48"),
                "psychological_load": Decimal("30"),
                "urgency": Decimal("58"),
                "can_be_delayed": True,
                "requires_review": True,
                "failure_consequence": Task.FailureConsequence.MEDIUM,
                "assignee_member": member_2,
                "plan_node": plan_nodes["B6"],
                "rule_version": ruleset.version,
                "created_at": now,
                "due_at": now + timedelta(hours=8),
                "submitted_at": now + timedelta(hours=6),
                "reviewed_at": None,
                "metadata": {"seed": True, "simulation_day": 1, "labor_note": "已提交整理记录，等待验收。"},
            },
        )
    )
    task_rejected = mark(
        upsert(
            Task,
            {"task_id": "task-0004"},
            {
                "title": "维修临时供水管线",
                "task_type": Task.TaskType.REPAIR,
                "status": Task.Status.REJECTED,
                "standard_hours": Decimal("3.00"),
                "base_points": 32,
                "role_coefficient": Decimal("1.300"),
                "physical_load": Decimal("68"),
                "dirty_level": Decimal("52"),
                "psychological_load": Decimal("46"),
                "urgency": Decimal("82"),
                "can_be_delayed": False,
                "requires_review": True,
                "failure_consequence": Task.FailureConsequence.CRITICAL,
                "assignee_member": member_3,
                "plan_node": plan_nodes["B3"],
                "rule_version": ruleset.version,
                "created_at": now,
                "due_at": now + timedelta(hours=5),
                "submitted_at": now + timedelta(hours=4),
                "reviewed_at": now + timedelta(hours=5),
                "metadata": {
                    "seed": True,
                    "simulation_day": 2,
                    "labor_note": "已更换一段临时软管，但未完成压力测试。",
                    "review_reason": "证据不足且管线仍有渗漏，验收驳回。",
                },
            },
        )
    )
    task_disputed = mark(
        upsert(
            Task,
            {"task_id": "task-0005"},
            {
                "title": "夜间仓库盘点",
                "task_type": Task.TaskType.WAREHOUSE,
                "status": Task.Status.DISPUTED,
                "standard_hours": Decimal("2.00"),
                "base_points": 24,
                "role_coefficient": Decimal("1.100"),
                "physical_load": Decimal("40"),
                "dirty_level": Decimal("38"),
                "psychological_load": Decimal("65"),
                "urgency": Decimal("74"),
                "can_be_delayed": False,
                "requires_review": True,
                "failure_consequence": Task.FailureConsequence.HIGH,
                "assignee_member": member_2,
                "plan_node": plan_nodes["B6"],
                "rule_version": ruleset.version,
                "created_at": now,
                "due_at": now + timedelta(hours=10),
                "submitted_at": now + timedelta(hours=9),
                "reviewed_at": now + timedelta(hours=10),
                "metadata": {
                    "seed": True,
                    "simulation_day": 2,
                    "labor_note": "已提交盘点表，但药品库存差异需要复核。",
                    "review_reason": "药品数量存在 12 件差异，进入争议流程。",
                },
            },
        )
    )
    task_reversed = mark(
        upsert(
            Task,
            {"task_id": "task-0006"},
            {
                "title": "采购清洁用品批次登记",
                "task_type": Task.TaskType.PURCHASE,
                "status": Task.Status.REVERSED,
                "standard_hours": Decimal("1.50"),
                "base_points": 18,
                "role_coefficient": Decimal("1.000"),
                "physical_load": Decimal("20"),
                "dirty_level": Decimal("10"),
                "psychological_load": Decimal("45"),
                "urgency": Decimal("50"),
                "can_be_delayed": True,
                "requires_review": True,
                "failure_consequence": Task.FailureConsequence.LOW,
                "assignee_member": member_1,
                "plan_node": plan_nodes["B5"],
                "rule_version": ruleset.version,
                "created_at": now,
                "due_at": now + timedelta(hours=12),
                "submitted_at": now + timedelta(hours=11),
                "reviewed_at": now + timedelta(hours=12),
                "metadata": {
                    "seed": True,
                    "simulation_day": 2,
                    "labor_note": "采购登记与另一条记录重复。",
                    "review_reason": "原验收通过后发现重复入账，已冲正。",
                },
            },
        )
    )
    mark(
        upsert(
            Task,
            {"task_id": "task-0007"},
            {
                "title": "取消重复的仓库盘点任务",
                "task_type": Task.TaskType.WAREHOUSE,
                "status": Task.Status.CLOSED,
                "standard_hours": Decimal("1.00"),
                "base_points": 10,
                "role_coefficient": Decimal("1.000"),
                "physical_load": Decimal("30"),
                "dirty_level": Decimal("20"),
                "psychological_load": Decimal("25"),
                "urgency": Decimal("35"),
                "can_be_delayed": True,
                "requires_review": True,
                "failure_consequence": Task.FailureConsequence.LOW,
                "assignee_member": None,
                "plan_node": plan_nodes["B6"],
                "rule_version": ruleset.version,
                "created_at": now - timedelta(hours=3),
                "due_at": now + timedelta(hours=18),
                "submitted_at": None,
                "reviewed_at": None,
                "metadata": {
                    "seed": True,
                    "simulation_day": 1,
                    "closed_by": actor("member-admin-0001", "开荒队治理成员"),
                    "closed_at": (now - timedelta(hours=2)).isoformat(),
                    "close_reason": "与已有仓库盘点安排重复，运营侧关闭未开始任务。",
                },
            },
        )
    )
    return {
        "task_open": task_open,
        "task_done": task_done,
        "task_rejected": task_rejected,
        "task_disputed": task_disputed,
        "task_reversed": task_reversed,
    }
