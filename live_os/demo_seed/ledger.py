"""Credit ledger demo seed data."""

from __future__ import annotations

from datetime import timedelta

from core.models import LedgerEntry, Ruleset

from .helpers import actor, ensure_ledger_entry_system_event, upsert


def seed_ledger(*, now, mark, ruleset: Ruleset, members: dict, tasks: dict) -> dict[str, LedgerEntry]:
    admin_member = members["admin"]
    member_1 = members["member_1"]
    member_3 = members["member_3"]
    task_done = tasks["task_done"]
    task_rejected = tasks["task_rejected"]
    task_reversed = tasks["task_reversed"]
    ledger_done = ensure_ledger_entry_system_event(mark(
        upsert(
            LedgerEntry,
            {"ledger_entry_id": "ledger-0001"},
            {
                "member": member_1,
                "amount": 20,
                "entry_type": LedgerEntry.EntryType.CONTRIBUTION,
                "reason": "公共厨房清理任务验收通过",
                "related_task": task_done,
                "related_event_id": "event-task-0002",
                "rule_version": ruleset.version,
                "created_at": now + timedelta(hours=2),
                "created_by": actor(admin_member.member_no, "开荒队治理成员"),
                "reviewer": actor(admin_member.member_no, "开荒队治理成员"),
                "status": LedgerEntry.Status.POSTED,
                "reverses_entry": None,
                "metadata": {"seed": True},
            },
        )
    ))
    ledger_reversed = ensure_ledger_entry_system_event(mark(
        upsert(
            LedgerEntry,
            {"ledger_entry_id": "ledger-0002"},
            {
                "member": member_1,
                "amount": 18,
                "entry_type": LedgerEntry.EntryType.CONTRIBUTION,
                "reason": "采购清洁用品批次登记验收通过，后续发现重复入账",
                "related_task": task_reversed,
                "related_event_id": "event-ledger-0003",
                "rule_version": ruleset.version,
                "created_at": now + timedelta(hours=12),
                "created_by": actor(admin_member.member_no, "开荒队治理成员"),
                "reviewer": actor(admin_member.member_no, "开荒队治理成员"),
                "status": LedgerEntry.Status.REVERSED,
                "reverses_entry": None,
                "metadata": {"seed": True, "note": "演示被冲正的原始流水"},
            },
        )
    ))
    ensure_ledger_entry_system_event(mark(
        upsert(
            LedgerEntry,
            {"ledger_entry_id": "ledger-0003"},
            {
                "member": member_1,
                "amount": -18,
                "entry_type": LedgerEntry.EntryType.REVERSAL,
                "reason": "冲正重复采购登记积分",
                "related_task": task_reversed,
                "related_event_id": "event-ledger-0003",
                "rule_version": ruleset.version,
                "created_at": now + timedelta(hours=12, minutes=30),
                "created_by": actor(admin_member.member_no, "开荒队治理成员"),
                "reviewer": actor(admin_member.member_no, "开荒队治理成员"),
                "status": LedgerEntry.Status.POSTED,
                "reverses_entry": ledger_reversed,
                "metadata": {"seed": True},
            },
        )
    ))
    ledger_penalty = ensure_ledger_entry_system_event(mark(
        upsert(
            LedgerEntry,
            {"ledger_entry_id": "ledger-0004"},
            {
                "member": member_3,
                "amount": -5,
                "entry_type": LedgerEntry.EntryType.PENALTY,
                "reason": "供水管线维修未完成压力测试，待复核是否扣减",
                "related_task": task_rejected,
                "related_event_id": "event-task-0004",
                "rule_version": ruleset.version,
                "created_at": now + timedelta(hours=5, minutes=5),
                "created_by": actor(admin_member.member_no, "开荒队治理成员"),
                "reviewer": actor(admin_member.member_no, "开荒队治理成员"),
                "status": LedgerEntry.Status.PENDING_REVIEW,
                "reverses_entry": None,
                "metadata": {"seed": True, "note": "演示待复核扣减流水"},
            },
        )
    ))
    return {
        "ledger_done": ledger_done,
        "ledger_reversed": ledger_reversed,
        "ledger_penalty": ledger_penalty,
    }
