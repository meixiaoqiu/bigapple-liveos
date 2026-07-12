"""Dispute demo seed data."""

from __future__ import annotations

from datetime import timedelta

from core.models import Dispute

from .helpers import actor, upsert


def seed_disputes(*, now, mark, members: dict, tasks: dict, ledgers: dict) -> None:
    admin_member = members["admin"]
    member_1 = members["member_1"]
    member_2 = members["member_2"]
    member_3 = members["member_3"]
    task_open = tasks["task_open"]
    task_done = tasks["task_done"]
    task_rejected = tasks["task_rejected"]
    task_disputed = tasks["task_disputed"]
    ledger_done = ledgers["ledger_done"]
    ledger_penalty = ledgers["ledger_penalty"]
    mark(
        upsert(
            Dispute,
            {"dispute_id": "dispute-0001"},
            {
                "dispute_type": Dispute.DisputeType.TASK_REVIEW,
                "status": Dispute.Status.SUBMITTED,
                "claimant_member": member_2,
                "respondent_member": admin_member,
                "related_task": task_open,
                "related_ledger_entry": None,
                "facts": "成员认为厨房支援任务分配不均，申请复核任务安排。",
                "evidence_refs": ["event-day-0001", "task-0001"],
                "handler": {},
                "reviewer": {},
                "resolution": "",
                "appeal_path": "standard-review-appeal",
                "submitted_at": now + timedelta(hours=3),
                "resolved_at": None,
                "metadata": {"seed": True},
            },
        )
    )
    mark(
        upsert(
            Dispute,
            {"dispute_id": "dispute-0002"},
            {
                "dispute_type": Dispute.DisputeType.WAREHOUSE_LOSS,
                "status": Dispute.Status.IN_REVIEW,
                "claimant_member": member_2,
                "respondent_member": member_3,
                "related_task": task_disputed,
                "related_ledger_entry": None,
                "facts": "仓库盘点中药品库存少 12 件，成员申请复核盘点责任和任务验收。",
                "evidence_refs": ["event-task-0005", "event-resource-0001", "task-0005"],
                "handler": actor(admin_member.member_no, "开荒队治理成员"),
                "reviewer": {},
                "resolution": "",
                "appeal_path": "warehouse-loss-review",
                "submitted_at": now + timedelta(hours=10),
                "resolved_at": None,
                "metadata": {"seed": True, "missing_count": 12},
            },
        )
    )
    mark(
        upsert(
            Dispute,
            {"dispute_id": "dispute-0003"},
            {
                "dispute_type": Dispute.DisputeType.POINTS_DEDUCTION,
                "status": Dispute.Status.RESOLVED,
                "claimant_member": member_3,
                "respondent_member": admin_member,
                "related_task": task_rejected,
                "related_ledger_entry": ledger_penalty,
                "facts": "成员对供水管线维修驳回后的待复核扣减提出异议。",
                "evidence_refs": ["event-task-0004", "ledger-0004"],
                "handler": actor(admin_member.member_no, "开荒队治理成员"),
                "reviewer": actor("member-admin-0002", "复核治理成员"),
                "resolution": "暂不入账扣减，要求重新派工并补充压力测试记录。",
                "appeal_path": "points-deduction-review",
                "submitted_at": now + timedelta(hours=6),
                "resolved_at": now + timedelta(hours=14),
                "metadata": {"seed": True, "outcome": "penalty_pending_review"},
            },
        )
    )
    mark(
        upsert(
            Dispute,
            {"dispute_id": "dispute-0004"},
            {
                "dispute_type": Dispute.DisputeType.TASK_REVIEW,
                "status": Dispute.Status.RESOLVED,
                "claimant_member": member_1,
                "respondent_member": admin_member,
                "related_task": task_done,
                "related_ledger_entry": ledger_done,
                "facts": "成员申请查看公共厨房清理任务的验收细则和积分计算过程。",
                "evidence_refs": ["event-task-0002", "ledger-0001"],
                "handler": actor(admin_member.member_no, "开荒队治理成员"),
                "reviewer": actor("member-admin-0002", "复核治理成员"),
                "resolution": "已确认验收通过和积分计算无误，补充公开验收说明。",
                "appeal_path": "standard-review-appeal",
                "submitted_at": now + timedelta(hours=3, minutes=30),
                "resolved_at": now + timedelta(hours=4),
                "metadata": {"seed": True, "scenario": "workspace_dispute_history"},
            },
        )
    )
