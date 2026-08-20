"""版本化选民策略使用的统一提案生命周期服务。"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from .authorization_services import AuthorizationService
from .electorate_rule_services import (
    electorate_eligibility_for_proposal,
    generate_elector_snapshot,
)
from .exceptions import DomainError
from .models import (
    ApprovalProposal,
    ElectorateRuleVersion,
    Member,
    ProposalBallot,
    ProposalExecutionRecord,
    ProposalResolution,
    SystemEvent,
)
from .proposal_adapters import proposal_adapter_for


@dataclass(frozen=True)
class ProposalTally:
    eligible_count: int
    participation_count: int
    approve_count: int
    reject_count: int
    abstain_count: int


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:16]}"


def _require_permission(member: Member, permission_code: str, message: str) -> None:
    if not permission_code:
        AuthorizationService().ensure_authorization_available(member)
        return
    if not AuthorizationService().member_has_permission(member, permission_code):
        raise DomainError(message)


def create_electorate_proposal(
    *,
    proposal_type: str,
    title: str,
    submitted_by: Member,
    dedupe_key: str,
    target_type: str,
    target_id: str,
    rule_version: ElectorateRuleVersion | None,
    summary: str = "",
    public_reason: str = "",
    metadata: dict | None = None,
) -> ApprovalProposal:
    """创建或复用选民策略提案；规则缺失时保持等待政策状态。"""

    adapter = proposal_adapter_for(proposal_type)
    if adapter.strategy_type != ApprovalProposal.StrategyType.ELECTORATE:
        raise DomainError("该提案类型没有登记选民策略适配器。")
    _require_permission(submitted_by, adapter.initiation_permission, "你无权发起该提案。")
    if not dedupe_key:
        raise DomainError("提案幂等键不能为空。")
    existing = ApprovalProposal.objects.filter(
        proposal_type=proposal_type,
        dedupe_key=dedupe_key,
    ).first()
    if existing is not None:
        return existing
    if rule_version is not None and rule_version.template.proposal_type != proposal_type:
        raise DomainError("选民规则版本不适用于该提案类型。")
    now = timezone.now()
    from .event_ledger import append_event
    from .event_payloads import approval_proposal_payload

    try:
        # 将创建和事件写入放在同一事务内，但在事务外捕获唯一约束竞争。
        # 这样败方回查时能看到已提交的赢家记录，不受旧事务快照影响。
        with transaction.atomic():
            proposal = ApprovalProposal.objects.create(
                proposal_id=_new_id("proposal"),
                proposal_type=proposal_type,
                title=title,
                summary=summary,
                public_reason=public_reason,
                status=(ApprovalProposal.Status.DRAFT if rule_version else ApprovalProposal.Status.AWAITING_POLICY),
                strategy_type=ApprovalProposal.StrategyType.ELECTORATE,
                target_type=target_type,
                target_id=target_id,
                dedupe_key=dedupe_key,
                submitted_by=submitted_by,
                submitted_at=now,
                electorate_rule_version=rule_version,
                metadata=dict(metadata or {}),
                created_at=now,
                updated_at=now,
            )
            append_event(
                event_type=SystemEvent.EventType.APPROVAL_PROPOSAL_SUBMITTED,
                aggregate_type="ApprovalProposal",
                aggregate_id=proposal.proposal_id,
                actor_member=submitted_by,
                payload_json=approval_proposal_payload(proposal, action="submitted", actor=submitted_by),
                occurred_at=now,
            )
    except IntegrityError:
        winner = ApprovalProposal.objects.filter(
            proposal_type=proposal_type,
            dedupe_key=dedupe_key,
        ).first()
        if winner is None:
            raise
        return winner
    return proposal


@transaction.atomic
def attach_rule_version(
    *, proposal: ApprovalProposal, rule_version: ElectorateRuleVersion,
) -> ApprovalProposal:
    """为等待政策的提案绑定适用版本；开始表决后不可替换。"""

    locked = ApprovalProposal.objects.select_for_update().get(pk=proposal.pk)
    if locked.status not in {ApprovalProposal.Status.AWAITING_POLICY, ApprovalProposal.Status.DRAFT}:
        raise DomainError("只有尚未开始表决的提案可以绑定选民规则。")
    if rule_version.template.proposal_type != locked.proposal_type:
        raise DomainError("选民规则版本不适用于该提案类型。")
    locked.electorate_rule_version = rule_version
    locked.status = ApprovalProposal.Status.DRAFT
    locked.updated_at = timezone.now()
    locked.save(update_fields=["electorate_rule_version", "status", "updated_at"])
    return locked


@transaction.atomic
def activate_waiting_proposals_for_rule(*, rule_version: ElectorateRuleVersion) -> int:
    """将同类型等待政策的提案绑定指定版本并开始表决。"""

    proposal_ids = list(
        ApprovalProposal.objects.select_for_update()
        .filter(
            proposal_type=rule_version.template.proposal_type,
            strategy_type=ApprovalProposal.StrategyType.ELECTORATE,
            status=ApprovalProposal.Status.AWAITING_POLICY,
        )
        .values_list("proposal_id", flat=True)
    )
    for proposal_id in proposal_ids:
        proposal = ApprovalProposal.objects.get(pk=proposal_id)
        proposal = attach_rule_version(proposal=proposal, rule_version=rule_version)
        start_electorate_voting(proposal=proposal)
    return len(proposal_ids)


@transaction.atomic
def start_electorate_voting(*, proposal: ApprovalProposal) -> ApprovalProposal:
    """冻结规则参数并生成选民快照，然后进入表决状态。"""

    locked = ApprovalProposal.objects.select_for_update().select_related(
        "electorate_rule_version", "electorate_rule_version__template",
    ).get(pk=proposal.pk)
    if locked.strategy_type != ApprovalProposal.StrategyType.ELECTORATE:
        raise DomainError("该提案不使用选民表决策略。")
    if locked.status == ApprovalProposal.Status.VOTING:
        return locked
    if locked.status != ApprovalProposal.Status.DRAFT:
        raise DomainError("只有草拟提案可以开始表决。")
    rule = locked.electorate_rule_version
    if rule is None:
        raise DomainError("提案尚未绑定已发布选民规则。")
    if rule.template.proposal_type != locked.proposal_type:
        raise DomainError("选民规则版本与提案类型不一致。")
    now = timezone.now()
    locked.frozen_approve_threshold = rule.approve_threshold
    locked.frozen_reject_threshold = rule.reject_threshold
    locked.frozen_minimum_participation = rule.minimum_participation
    locked.frozen_unresolved_outcome = rule.unresolved_outcome
    locked.voting_started_at = now
    locked.voting_deadline = now + timezone.timedelta(hours=rule.voting_duration_hours)
    locked.status = ApprovalProposal.Status.VOTING
    locked.updated_at = now
    locked.save(update_fields=[
        "frozen_approve_threshold", "frozen_reject_threshold", "frozen_minimum_participation",
        "frozen_unresolved_outcome", "voting_started_at", "voting_deadline", "status", "updated_at",
    ])
    adapter = proposal_adapter_for(locked.proposal_type)
    generate_elector_snapshot(
        proposal=locked,
        excluded_member_id=adapter.excluded_member_id(locked),
    )
    from .event_ledger import append_event
    from .event_payloads import approval_proposal_payload

    append_event(
        event_type=SystemEvent.EventType.PROPOSAL_VOTING_STARTED,
        aggregate_type="ApprovalProposal",
        aggregate_id=locked.proposal_id,
        actor_member=locked.submitted_by,
        payload_json=approval_proposal_payload(locked, action="voting_started", actor=locked.submitted_by),
        occurred_at=now,
    )
    return locked


def proposal_tally(proposal: ApprovalProposal) -> ProposalTally:
    """只按快照内且当前仍合格成员的最后一份票据计算票数。"""

    latest_revisions = dict(
        ProposalBallot.objects.filter(proposal=proposal)
        .values("voter_id")
        .annotate(latest=Max("revision"))
        .values_list("voter_id", "latest")
    )
    candidate_ballots = [
        ballot
        for ballot in ProposalBallot.objects.filter(
            proposal=proposal, voter_id__in=latest_revisions,
        ).select_related("voter")
        if ballot.revision == latest_revisions.get(ballot.voter_id)
    ]
    adapter = proposal_adapter_for(proposal.proposal_type)
    excluded_member_id = adapter.excluded_member_id(proposal)
    latest_ballots = [
        ballot
        for ballot in candidate_ballots
        if electorate_eligibility_for_proposal(
            proposal=proposal,
            member=ballot.voter,
            excluded_member_id=excluded_member_id,
        ).allowed
    ]
    return ProposalTally(
        eligible_count=proposal.elector_snapshots.count(),
        participation_count=len(latest_ballots),
        approve_count=sum(item.choice == ProposalBallot.Choice.APPROVE for item in latest_ballots),
        reject_count=sum(item.choice == ProposalBallot.Choice.REJECT for item in latest_ballots),
        abstain_count=sum(item.choice == ProposalBallot.Choice.ABSTAIN for item in latest_ballots),
    )


def _resolution_outcome(proposal: ApprovalProposal, tally: ProposalTally, *, at_time) -> tuple[str, str] | None:
    minimum = proposal.frozen_minimum_participation or 0
    if tally.participation_count >= minimum:
        if tally.approve_count >= (proposal.frozen_approve_threshold or 1):
            return ProposalResolution.Outcome.APPROVED, "approve_threshold_reached"
        if tally.reject_count >= (proposal.frozen_reject_threshold or 1):
            return ProposalResolution.Outcome.REJECTED, "reject_threshold_reached"
    if proposal.voting_deadline and at_time >= proposal.voting_deadline:
        if proposal.frozen_unresolved_outcome == "rejected":
            return ProposalResolution.Outcome.REJECTED, "deadline_unresolved_rejected"
        return ProposalResolution.Outcome.EXPIRED, "deadline_unresolved_expired"
    return None


def _resolve_locked_proposal(
    proposal: ApprovalProposal, *, at_time, actor: Member,
) -> ApprovalProposal:
    tally = proposal_tally(proposal)
    result = _resolution_outcome(proposal, tally, at_time=at_time)
    if result is None:
        return proposal
    outcome, reason_code = result
    evidence = {
        "eligible_count": tally.eligible_count,
        "participation_count": tally.participation_count,
        "approve_count": tally.approve_count,
        "reject_count": tally.reject_count,
        "abstain_count": tally.abstain_count,
        "approve_threshold": proposal.frozen_approve_threshold,
        "reject_threshold": proposal.frozen_reject_threshold,
        "minimum_participation": proposal.frozen_minimum_participation,
    }
    ProposalResolution.objects.create(
        proposal=proposal,
        outcome=outcome,
        reason_code=reason_code,
        evidence=evidence,
        decided_by=actor,
        decided_at=at_time,
    )
    proposal.status = {
        ProposalResolution.Outcome.APPROVED: ApprovalProposal.Status.APPROVED,
        ProposalResolution.Outcome.REJECTED: ApprovalProposal.Status.REJECTED,
        ProposalResolution.Outcome.EXPIRED: ApprovalProposal.Status.EXPIRED,
    }[outcome]
    proposal.resolved_at = at_time
    proposal.updated_at = at_time
    proposal.save(update_fields=["status", "resolved_at", "updated_at"])
    adapter = proposal_adapter_for(proposal.proposal_type)
    if adapter.resolution_callback is not None:
        adapter.resolution_callback(proposal, actor)
    from .event_ledger import append_event
    from .event_payloads import approval_proposal_payload

    event_type = {
        ProposalResolution.Outcome.APPROVED: SystemEvent.EventType.APPROVAL_PROPOSAL_APPROVED,
        ProposalResolution.Outcome.REJECTED: SystemEvent.EventType.APPROVAL_PROPOSAL_REJECTED,
        ProposalResolution.Outcome.EXPIRED: SystemEvent.EventType.PROPOSAL_EXPIRED,
    }[outcome]
    append_event(
        event_type=event_type,
        aggregate_type="ApprovalProposal",
        aggregate_id=proposal.proposal_id,
        actor_member=actor,
        payload_json=approval_proposal_payload(proposal, action=outcome, actor=actor),
        occurred_at=at_time,
    )
    return proposal


@transaction.atomic
def cast_electorate_ballot(
    *, proposal: ApprovalProposal, voter: Member, choice: str, reason: str = "",
) -> ApprovalProposal:
    """追加实名票据修订并按冻结参数尝试判定结果。"""

    locked = ApprovalProposal.objects.select_for_update().select_related("electorate_rule_version").get(pk=proposal.pk)
    if locked.status != ApprovalProposal.Status.VOTING:
        raise DomainError("当前提案不接受投票。")
    now = timezone.now()
    if locked.voting_deadline and now >= locked.voting_deadline:
        raise DomainError("提案已到截止时间，需由有权人员完成结果判定。")
    if choice not in {value for value, _ in ProposalBallot.Choice.choices}:
        raise DomainError("投票选项无效。")
    adapter = proposal_adapter_for(locked.proposal_type)
    eligibility = electorate_eligibility_for_proposal(
        proposal=locked,
        member=voter,
        excluded_member_id=adapter.excluded_member_id(locked),
    )
    if not eligibility.allowed:
        raise DomainError(eligibility.message)
    latest = (
        ProposalBallot.objects.filter(proposal=locked, voter=voter)
        .aggregate(value=Max("revision"))["value"]
        or 0
    )
    ProposalBallot.objects.create(
        ballot_id=_new_id("ballot"),
        proposal=locked,
        voter=voter,
        revision=latest + 1,
        choice=choice,
        reason=reason,
        submitted_at=now,
    )
    from .event_ledger import append_event
    from .event_payloads import approval_proposal_payload

    append_event(
        event_type=SystemEvent.EventType.PROPOSAL_BALLOT_CAST,
        aggregate_type="ApprovalProposal",
        aggregate_id=locked.proposal_id,
        actor_member=voter,
        payload_json=approval_proposal_payload(locked, action="ballot_cast", actor=voter),
        occurred_at=now,
    )
    return _resolve_locked_proposal(locked, at_time=now, actor=voter)


@transaction.atomic
def finalize_electorate_proposal(*, proposal: ApprovalProposal, actor: Member) -> ApprovalProposal:
    """由有权人员在截止后触发确定性判定，不允许人工选择结果。"""

    locked = ApprovalProposal.objects.select_for_update().get(pk=proposal.pk)
    adapter = proposal_adapter_for(locked.proposal_type)
    _require_permission(actor, adapter.resolution_permission, "你无权完成该提案的截止判定。")
    if locked.status != ApprovalProposal.Status.VOTING:
        return locked
    now = timezone.now()
    if not locked.voting_deadline or now < locked.voting_deadline:
        raise DomainError("提案尚未到达截止时间。")
    return _resolve_locked_proposal(locked, at_time=now, actor=actor)


def execute_electorate_proposal(*, proposal: ApprovalProposal, actor: Member) -> ProposalExecutionRecord:
    """通过登记适配器幂等执行已通过提案，并记录实名成功或失败结果。"""

    with transaction.atomic():
        locked = ApprovalProposal.objects.select_for_update().get(pk=proposal.pk)
        if locked.strategy_type != ApprovalProposal.StrategyType.ELECTORATE:
            raise DomainError("该提案不属于统一选民表决生命周期。")
        adapter = proposal_adapter_for(locked.proposal_type)
        _require_permission(actor, adapter.execution_permission, "你无权执行该提案。")
        resolution = ProposalResolution.objects.filter(proposal=locked).first()
        if resolution is None or resolution.outcome != ProposalResolution.Outcome.APPROVED:
            raise DomainError("该提案缺少已通过的确定性判定证据，不能执行。")
        existing = ProposalExecutionRecord.objects.filter(proposal=locked).first()
        if existing and existing.status == ProposalExecutionRecord.Status.SUCCEEDED:
            return existing
        if locked.status not in {ApprovalProposal.Status.APPROVED, ApprovalProposal.Status.EXECUTION_FAILED}:
            raise DomainError("只能执行已通过或等待重试的提案。")
        if existing is None:
            existing = ProposalExecutionRecord.objects.create(
                execution_id=_new_id("execution"),
                proposal=locked,
                idempotency_key=f"proposal:{locked.pk}",
                executed_by=actor,
                status=ProposalExecutionRecord.Status.RUNNING,
                started_at=timezone.now(),
            )
        else:
            existing.executed_by = actor
            existing.status = ProposalExecutionRecord.Status.RUNNING
            existing.public_error_code = ""
            existing.completed_at = None
            existing.save(update_fields=["executed_by", "status", "public_error_code", "completed_at"])
        try:
            with transaction.atomic():
                result = adapter.executor(locked, actor)
        except DomainError as exc:
            existing.status = ProposalExecutionRecord.Status.FAILED
            existing.public_error_code = "domain_precondition_failed"
            existing.result_data = {"message": str(exc)}
            existing.completed_at = timezone.now()
            existing.save(update_fields=["status", "public_error_code", "result_data", "completed_at"])
            locked.status = ApprovalProposal.Status.EXECUTION_FAILED
            locked.updated_at = timezone.now()
            locked.save(update_fields=["status", "updated_at"])
            from .event_ledger import append_event
            from .event_payloads import approval_proposal_payload

            append_event(
                event_type=SystemEvent.EventType.PROPOSAL_EXECUTION_FAILED,
                aggregate_type="ApprovalProposal",
                aggregate_id=locked.proposal_id,
                actor_member=actor,
                payload_json=approval_proposal_payload(locked, action="execution_failed", actor=actor),
                occurred_at=existing.completed_at,
            )
            return existing
        existing.status = ProposalExecutionRecord.Status.SUCCEEDED
        existing.result_data = result if isinstance(result, dict) else {}
        existing.completed_at = timezone.now()
        existing.save(update_fields=["status", "result_data", "completed_at"])
        locked.status = ApprovalProposal.Status.EXECUTED
        locked.executed_at = existing.completed_at
        locked.updated_at = existing.completed_at
        locked.save(update_fields=["status", "executed_at", "updated_at"])
        from .event_ledger import append_event
        from .event_payloads import approval_proposal_payload

        append_event(
            event_type=SystemEvent.EventType.APPROVAL_PROPOSAL_EXECUTED,
            aggregate_type="ApprovalProposal",
            aggregate_id=locked.proposal_id,
            actor_member=actor,
            payload_json=approval_proposal_payload(locked, action="executed", actor=actor),
            occurred_at=existing.completed_at,
        )
        return existing
