"""Observer event demo seed data."""

from __future__ import annotations

from datetime import timedelta

from core.models import Event

from .helpers import upsert


def seed_events(*, now, mark, members: dict, tasks: dict) -> None:
    admin_member = members["admin"]
    member_1 = members["member_1"]
    member_2 = members["member_2"]
    member_3 = members["member_3"]
    task_done = tasks["task_done"]
    task_rejected = tasks["task_rejected"]
    task_disputed = tasks["task_disputed"]
    task_reversed = tasks["task_reversed"]
    mark(
        upsert(
            Event,
            {"event_id": "event-day-0001"},
            {
                "event_type": Event.EventType.SIMULATION_DAY,
                "simulation_day": 1,
                "severity": Event.Severity.INFO,
                "title": "001 号据点第 1 天开始",
                "summary": "100 名开荒队成员进入据点，开始建立食堂、仓库和任务秩序。",
                "involved_member_ids": ["mem-0001", "mem-0002"],
                "related_task": None,
                "related_dispute_id": "",
                "occurred_at": now,
                "generated_by": Event.GeneratedBy.LIVE_OS,
                "visibility": Event.Visibility.PUBLIC,
                "payload": {"seed": True, "formal_members": 100},
            },
        )
    )
    mark(
        upsert(
            Event,
            {"event_id": "event-task-0002"},
            {
                "event_type": Event.EventType.TASK,
                "simulation_day": 1,
                "severity": Event.Severity.INFO,
                "title": "公共厨房清理验收通过",
                "summary": "任务 task-0002 已通过验收，产生贡献积分流水。",
                "involved_member_ids": [member_1.member_no],
                "related_task": task_done,
                "related_dispute_id": "",
                "occurred_at": now + timedelta(hours=2),
                "generated_by": Event.GeneratedBy.LIVE_OS,
                "visibility": Event.Visibility.PUBLIC,
                "payload": {"seed": True, "points_awarded": 20},
            },
        )
    )
    mark(
        upsert(
            Event,
            {"event_id": "event-resource-0001"},
            {
                "event_type": Event.EventType.RESOURCE,
                "simulation_day": 2,
                "severity": Event.Severity.WARNING,
                "title": "药品库存低于预警线",
                "summary": "药品库存降至 18 件，低于 30 件预警线，需要采购或调拨。",
                "involved_member_ids": [admin_member.member_no],
                "related_task": task_disputed,
                "related_dispute_id": "dispute-0002",
                "occurred_at": now + timedelta(hours=10, minutes=15),
                "generated_by": Event.GeneratedBy.LIVE_OS,
                "visibility": Event.Visibility.PUBLIC,
                "payload": {
                    "seed": True,
                    "resource_id": "res-medicine",
                    "current_stock": 18,
                    "warning_threshold": 30,
                },
            },
        )
    )
    mark(
        upsert(
            Event,
            {"event_id": "event-task-0004"},
            {
                "event_type": Event.EventType.TASK,
                "simulation_day": 2,
                "severity": Event.Severity.WARNING,
                "title": "供水管线维修验收驳回",
                "summary": "任务 task-0004 因未完成压力测试被驳回，后续需要重新派工。",
                "involved_member_ids": [member_3.member_no],
                "related_task": task_rejected,
                "related_dispute_id": "",
                "occurred_at": now + timedelta(hours=5),
                "generated_by": Event.GeneratedBy.HUMAN_OPERATOR,
                "visibility": Event.Visibility.INTERNAL,
                "payload": {"seed": True, "review_reason": "管线仍有渗漏。"},
            },
        )
    )
    mark(
        upsert(
            Event,
            {"event_id": "event-task-0005"},
            {
                "event_type": Event.EventType.DISPUTE,
                "simulation_day": 2,
                "severity": Event.Severity.WARNING,
                "title": "仓库盘点进入争议流程",
                "summary": "任务 task-0005 药品库存差异进入申诉复核。",
                "involved_member_ids": [member_2.member_no, member_3.member_no],
                "related_task": task_disputed,
                "related_dispute_id": "dispute-0002",
                "occurred_at": now + timedelta(hours=10),
                "generated_by": Event.GeneratedBy.LIVE_OS,
                "visibility": Event.Visibility.PUBLIC,
                "payload": {"seed": True, "missing_count": 12},
            },
        )
    )
    mark(
        upsert(
            Event,
            {"event_id": "event-ledger-0003"},
            {
                "event_type": Event.EventType.LEDGER,
                "simulation_day": 2,
                "severity": Event.Severity.INFO,
                "title": "重复采购登记积分已冲正",
                "summary": "任务 task-0006 的重复积分流水已通过 reversal 流水冲正。",
                "involved_member_ids": [member_1.member_no],
                "related_task": task_reversed,
                "related_dispute_id": "",
                "occurred_at": now + timedelta(hours=12, minutes=30),
                "generated_by": Event.GeneratedBy.HUMAN_OPERATOR,
                "visibility": Event.Visibility.INTERNAL,
                "payload": {"seed": True, "reversed_amount": -18},
            },
        )
    )
