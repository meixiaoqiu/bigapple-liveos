"""提案选民规则、快照与当前资格查询。"""

from __future__ import annotations

import math

from django.core.exceptions import ValidationError

from core.electorate_rules import evaluate_condition_tree, rule_snapshot_for_proposal
from core.models import ElectorateRuleVersion, Member, Proposal


def calculate_required_approvals(voter_count: int, required_percent: int) -> int:
    if voter_count < 1:
        return 1
    normalized_percent = max(1, min(100, required_percent))
    if normalized_percent == 100:
        return voter_count
    return max(1, math.floor(voter_count * normalized_percent / 100) + 1)


def validate_electorate_rule_snapshot(snapshot: object) -> dict:
    """验证提案保存的规则快照，缺失或损坏时失败关闭。"""

    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("condition"), dict):
        raise ValidationError("提案缺少有效选民规则快照。")
    evaluate_condition_tree(snapshot["condition"])
    return snapshot


def eligible_voters_for_rule_snapshot(*, rule_snapshot: dict, at_time=None):
    """通过通用条件树计算当前选民。"""

    snapshot = validate_electorate_rule_snapshot(rule_snapshot)
    return evaluate_condition_tree(snapshot["condition"], at_time=at_time)


def member_is_currently_eligible_to_vote(*, member: Member, proposal: Proposal, at_time=None) -> bool:
    """按本提案固定的规则重新检查成员当前资格。"""

    return eligible_voters_for_rule_snapshot(
        rule_snapshot=proposal.electorate_rule_snapshot_json,
        at_time=at_time,
    ).filter(pk=member.pk).exists()


def eligible_voter_snapshot(*, rule_snapshot: dict, at_time=None) -> list[int]:
    """保存选民编号快照，用于门槛与审计而非授权旁路。"""

    return list(
        eligible_voters_for_rule_snapshot(rule_snapshot=rule_snapshot, at_time=at_time).values_list("pk", flat=True)
    )


def prepare_electorate_rule(
    *,
    proposal_type: str,
    rule_version: ElectorateRuleVersion,
    parameters: dict | None = None,
    at_time=None,
) -> tuple[dict, list[int]]:
    """固定规则版本与参数，并生成本次表决的初始选民快照。"""

    snapshot = rule_snapshot_for_proposal(
        proposal_type=proposal_type,
        rule_version=rule_version,
        parameters=parameters,
    )
    return snapshot, eligible_voter_snapshot(rule_snapshot=snapshot, at_time=at_time)
