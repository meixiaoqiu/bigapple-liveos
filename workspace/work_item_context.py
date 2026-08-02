"""Read-only work-item projections for the workspace dashboard.

Collects pending actions across procurement, proposals, receipt,
payment and challenges — producing a flat list of ``work_items``
with type, status, priority and target URLs.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone as dj_timezone
from django.db.models import Exists, OuterRef, Q, Subquery

from core.access import is_finance_reviewer, member_can_maintain
from core.models import (
    ApprovalDecision,
    ApprovalProposal,
    Dispute,
    Member,
    ProcurementChallenge,
    SupplierQuote,
    Task,
)

MATTER_DISPLAY_LIMIT = 20


def _approval_exists(*, role: str, decision: str | None = None, approver_id: int | None = None):
    queryset = ApprovalDecision.objects.filter(proposal_id=OuterRef("pk"), role=role)
    if decision is not None:
        queryset = queryset.filter(decision=decision)
    if approver_id is not None:
        queryset = queryset.filter(approver_id=approver_id)
    return Exists(queryset)


def _actionable_proposal_queryset(member: Member, *, is_gov: bool, is_fin: bool):
    """Return current member's actionable proposals, filtered in SQL."""

    queryset = ApprovalProposal.objects.filter(status=ApprovalProposal.Status.SUBMITTED).annotate(
        approved_governance=_approval_exists(
            role="governance", decision=ApprovalDecision.Decision.APPROVED,
        ),
        approved_finance=_approval_exists(
            role="finance", decision=ApprovalDecision.Decision.APPROVED,
        ),
        approved_second_governance=_approval_exists(
            role="second_governance", decision=ApprovalDecision.Decision.APPROVED,
        ),
        acted_governance=_approval_exists(role="governance", approver_id=member.pk),
        acted_finance=_approval_exists(role="finance", approver_id=member.pk),
        acted_second_governance=_approval_exists(role="second_governance", approver_id=member.pk),
    )
    eligible = Q(pk__in=[])
    procurement = ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE
    payment = ApprovalProposal.ProposalType.PROCUREMENT_PAYMENT
    if is_gov:
        eligible |= Q(
            proposal_type=procurement, approval_tier=ApprovalProposal.Tier.SINGLE,
            approved_governance=False, approved_finance=False, acted_governance=False,
        )
        eligible |= Q(
            proposal_type=procurement, approval_tier=ApprovalProposal.Tier.STANDARD,
            approved_governance=False, acted_governance=False,
        )
        eligible |= Q(
            proposal_type=procurement, approval_tier=ApprovalProposal.Tier.MAJOR,
            approved_governance=False, acted_governance=False,
        ) | Q(
            proposal_type=procurement, approval_tier=ApprovalProposal.Tier.MAJOR,
            approved_second_governance=False, acted_second_governance=False,
        )
        eligible |= (
            ~Q(proposal_type__in=[procurement, payment])
            & Q(approved_governance=False, acted_governance=False)
        )
    if is_fin:
        eligible |= Q(
            proposal_type=procurement, approval_tier=ApprovalProposal.Tier.SINGLE,
            approved_governance=False, approved_finance=False, acted_finance=False,
        )
        eligible |= Q(
            proposal_type=procurement,
            approval_tier__in=[ApprovalProposal.Tier.STANDARD, ApprovalProposal.Tier.MAJOR],
            approved_finance=False, acted_finance=False,
        )
        eligible |= Q(proposal_type=payment, approved_finance=False, acted_finance=False)
    return queryset.filter(eligible).select_related("submitted_by").order_by(
        "-submitted_at", "proposal_id"
    )


def _governance_worksets(
    member: Member, *, is_gov: bool, is_fin: bool,
) -> tuple[
    list[ApprovalProposal], list[ApprovalProposal], list[SupplierQuote],
    list[SupplierQuote], dict[str, int],
]:
    """Load each actionable source with its own database predicate and ordering."""

    actionable_queryset = _actionable_proposal_queryset(member, is_gov=is_gov, is_fin=is_fin)
    executable_queryset = ApprovalProposal.objects.filter(
        status=ApprovalProposal.Status.APPROVED,
    ).select_related("submitted_by").order_by(
        "-resolved_at", "-submitted_at", "proposal_id"
    )

    acceptance = ApprovalProposal.objects.filter(
        target_type="supplier_quote",
        target_id=OuterRef("quote_id"),
        proposal_type=ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE,
    )
    latest_acceptance_status = Subquery(
        acceptance.order_by("-submitted_at").values("status")[:1]
    )
    receipt_queryset = SupplierQuote.objects.filter(
        decision_status=SupplierQuote.DecisionStatus.ACCEPTED,
        receipt_status=SupplierQuote.ReceiptStatus.PENDING,
    ).annotate(
        latest_acceptance_status=latest_acceptance_status,
    ).filter(
        Q(latest_acceptance_status__isnull=True)
        | Q(latest_acceptance_status=ApprovalProposal.Status.EXECUTED)
    ).select_related("resource", "submitted_by").order_by(
        "-created_at", "quote_id"
    )
    payment_queryset = SupplierQuote.objects.filter(
        decision_status=SupplierQuote.DecisionStatus.ACCEPTED,
        receipt_status=SupplierQuote.ReceiptStatus.ACCEPTED,
        payment_status=SupplierQuote.PaymentStatus.PENDING,
    ).select_related("resource", "submitted_by").order_by(
        "-created_at", "quote_id"
    )

    stats = {
        "approval_count": actionable_queryset.count(),
        "execute_count": executable_queryset.count(),
        "receipt_count": receipt_queryset.count(),
        "payment_count": payment_queryset.count(),
        "approval_overdue_count": actionable_queryset.filter(
            submitted_at__lt=dj_timezone.now() - timedelta(hours=OVERDUE_APPROVAL_HOURS)
        ).count(),
        "execute_overdue_count": executable_queryset.filter(
            resolved_at__lt=dj_timezone.now() - timedelta(hours=OVERDUE_EXECUTE_HOURS)
        ).count(),
        "receipt_overdue_count": receipt_queryset.filter(
            Q(updated_at__lt=dj_timezone.now() - timedelta(hours=OVERDUE_RECEIPT_HOURS))
            | Q(
                updated_at__isnull=True,
                created_at__lt=dj_timezone.now() - timedelta(hours=OVERDUE_RECEIPT_HOURS),
            )
        ).count(),
        "payment_overdue_count": payment_queryset.filter(
            Q(updated_at__lt=dj_timezone.now() - timedelta(hours=OVERDUE_PAYMENT_HOURS))
            | Q(
                updated_at__isnull=True,
                created_at__lt=dj_timezone.now() - timedelta(hours=OVERDUE_PAYMENT_HOURS),
            )
        ).count(),
    }
    return (
        list(actionable_queryset[:MATTER_DISPLAY_LIMIT]),
        list(executable_queryset[:MATTER_DISPLAY_LIMIT]),
        list(receipt_queryset[:MATTER_DISPLAY_LIMIT]),
        list(payment_queryset[:MATTER_DISPLAY_LIMIT]),
        stats,
    )

# ── overdue thresholds (hours) ──────────────────────────────────────

OVERDUE_APPROVAL_HOURS = 24
OVERDUE_EXECUTE_HOURS = 12
OVERDUE_RECEIPT_HOURS = 48
OVERDUE_PAYMENT_HOURS = 72


def _hours_since(dt_value) -> float:
    """Return hours elapsed since *dt_value* (timezone-aware)."""
    if dt_value is None:
        return 0
    now = dj_timezone.now()
    delta = now - dt_value
    return delta.total_seconds() / 3600


def _priority_for_proposal(p: ApprovalProposal) -> str:
    if p.approval_tier == ApprovalProposal.Tier.MAJOR:
        return "critical"
    if p.approval_tier == ApprovalProposal.Tier.STANDARD:
        return "high"
    return "normal"


def _priority_for_type(item_type: str) -> str:
    return "normal"


def _matter(*, matter_id: str, matter_type: str, type_label: str, title: str,
            status: str, status_label: str, responsible: str,
            current_handler: str, action_label: str, target_url: str,
            updated_at, priority: str = "normal", is_overdue: bool = False) -> dict:
    """Return the stable, presentation-only shape consumed by Workspace."""

    return {
        "id": matter_id,
        "type": matter_type,
        "type_label": type_label,
        "title": title,
        "status": status,
        "status_label": status_label,
        "responsible": responsible or "暂未明确",
        "current_handler": current_handler or "暂未明确",
        "action_label": action_label,
        "target_url": target_url,
        "updated_at": updated_at,
        "priority": priority,
        "is_overdue": is_overdue,
    }


def _actor_label(value, fallback: str = "暂未明确") -> str:
    if not isinstance(value, dict):
        return fallback
    return str(value.get("member_no") or value.get("actor_id") or value.get("name") or fallback)


def build_member_matters(
    member: Member, *, is_gov: bool | None = None, is_fin: bool | None = None,
    actionable_proposals: list[ApprovalProposal] | None = None,
    executable_proposals: list[ApprovalProposal] | None = None,
    receipt_quotes: list[SupplierQuote] | None = None,
    payment_quotes: list[SupplierQuote] | None = None,
) -> dict:
    """Project existing domain objects into member-related Workspace matters."""

    action_required: list[dict] = []
    waiting: list[dict] = []
    recently_ended: list[dict] = []

    active_tasks = Task.objects.filter(
        assignee_member=member,
        status__in=[Task.Status.CLAIMED, Task.Status.IN_PROGRESS,
                    Task.Status.PENDING_REVIEW, Task.Status.DISPUTED],
    ).order_by("-created_at")[:10]
    for task in active_tasks:
        needs_member = task.status in {Task.Status.CLAIMED, Task.Status.IN_PROGRESS}
        target = action_required if needs_member else waiting
        target.append(_matter(
            matter_id=f"task:{task.task_id}", matter_type="task", type_label="任务",
            title=task.title, status=task.status, status_label=task.get_status_display(),
            responsible=member.member_no,
            current_handler=member.member_no if needs_member else "任务验收角色",
            action_label="提交劳动" if needs_member else "等待验收",
            target_url="/workspace/",
            updated_at=task.submitted_at or task.created_at,
            priority="high" if task.failure_consequence in {
                Task.FailureConsequence.HIGH, Task.FailureConsequence.CRITICAL
            } else "normal",
        ))

    ended_tasks = Task.objects.filter(
        assignee_member=member,
        status__in=[Task.Status.ACCEPTED, Task.Status.REJECTED,
                    Task.Status.CLOSED, Task.Status.REVERSED],
    ).order_by("-reviewed_at", "-created_at")[:5]
    for task in ended_tasks:
        recently_ended.append(_matter(
            matter_id=f"task:{task.task_id}", matter_type="task", type_label="任务",
            title=task.title, status=task.status, status_label=task.get_status_display(),
            responsible=member.member_no, current_handler="已结束",
            action_label="查看结果", target_url="/workspace/#task-history",
            updated_at=task.reviewed_at or task.created_at,
        ))

    disputes = Dispute.objects.filter(
        Q(claimant_member=member) | Q(respondent_member=member)
    ).select_related("claimant_member", "respondent_member").order_by("-submitted_at")[:10]
    ended_dispute_statuses = {Dispute.Status.RESOLVED, Dispute.Status.REJECTED, Dispute.Status.REVERSED}
    for dispute in disputes:
        ended = dispute.status in ended_dispute_statuses
        target = recently_ended if ended else waiting
        handler = "已结束" if ended else _actor_label(dispute.handler, "申诉处理角色")
        target.append(_matter(
            matter_id=f"dispute:{dispute.dispute_id}", matter_type="dispute", type_label="申诉",
            title=f"{dispute.get_dispute_type_display()} · {dispute.dispute_id}",
            status=dispute.status, status_label=dispute.get_status_display(),
            responsible=dispute.claimant_member.member_no, current_handler=handler,
            action_label="查看结果" if ended else "等待处理",
            target_url="/workspace/#dispute-status",
            updated_at=dispute.resolved_at or dispute.submitted_at,
        ))

    member_quotes = SupplierQuote.objects.filter(submitted_by=member).exclude(
        decision_status__in=[SupplierQuote.DecisionStatus.REJECTED,
                             SupplierQuote.DecisionStatus.WITHDRAWN,
                             SupplierQuote.DecisionStatus.FULFILLED,
                             SupplierQuote.DecisionStatus.CANCELLED],
    ).select_related("resource", "submitted_by").order_by("-created_at")[:10]
    for quote in member_quotes:
        waiting.append(_matter(
            matter_id=f"supplier-quote:{quote.quote_id}", matter_type="procurement",
            type_label="采购", title=f"{quote.resource.name or quote.resource_id} · {quote.quote_id}",
            status=quote.decision_status, status_label=quote.get_decision_status_display(),
            responsible=member.member_no, current_handler="采购/财务处理角色",
            action_label="等待处理", target_url="/workspace/procurement/",
            updated_at=quote.updated_at or quote.created_at,
        ))

    is_gov = member_can_maintain(member) if is_gov is None else is_gov
    is_fin = is_finance_reviewer(member) if is_fin is None else is_fin
    if is_gov or is_fin:
        if any(items is None for items in [
            actionable_proposals, executable_proposals, receipt_quotes, payment_quotes,
        ]):
            actionable_proposals, executable_proposals, receipt_quotes, payment_quotes, _ = (
                _governance_worksets(member, is_gov=is_gov, is_fin=is_fin)
            )

        proposal_matters: list[dict] = []
        for proposal in actionable_proposals:
            proposal_matters.append(_matter(
                matter_id=f"approval-proposal:{proposal.proposal_id}",
                matter_type="approval_proposal", type_label="审批提案", title=proposal.title,
                status=proposal.status, status_label=proposal.get_status_display(),
                responsible=proposal.submitted_by.member_no,
                current_handler="提案审批角色",
                action_label="处理审批",
                target_url="/workspace/proposals/", updated_at=proposal.updated_at or proposal.resolved_at or proposal.submitted_at,
                priority=_priority_for_proposal(proposal),
            ))
        for proposal in executable_proposals:
            proposal_matters.append(_matter(
                matter_id=f"approval-proposal:{proposal.proposal_id}",
                matter_type="approval_proposal", type_label="审批提案", title=proposal.title,
                status=proposal.status, status_label=proposal.get_status_display(),
                responsible=proposal.submitted_by.member_no,
                current_handler="提案执行角色", action_label="执行提案",
                target_url="/workspace/proposals/",
                updated_at=proposal.updated_at or proposal.resolved_at or proposal.submitted_at,
                priority=_priority_for_proposal(proposal),
            ))

        procurement_matters: list[dict] = []
        for quote in receipt_quotes:
            procurement_matters.append(_matter(
                matter_id=f"supplier-quote:{quote.quote_id}", matter_type="procurement",
                type_label="采购", title=f"{quote.resource.name or quote.resource_id} · {quote.quote_id}",
                status=f"{quote.receipt_status}:{quote.payment_status}",
                status_label=quote.get_receipt_status_display(),
                responsible=quote.submitted_by.member_no if quote.submitted_by else "供应方",
                current_handler="采购验收角色", action_label="验收供给",
                target_url="/workspace/procurement/?status=accepted",
                updated_at=quote.updated_at or quote.created_at,
            ))
        for quote in payment_quotes:
            procurement_matters.append(_matter(
                matter_id=f"supplier-quote:{quote.quote_id}", matter_type="procurement",
                type_label="采购", title=f"{quote.resource.name or quote.resource_id} · {quote.quote_id}",
                status=f"{quote.receipt_status}:{quote.payment_status}",
                status_label=quote.get_payment_status_display(),
                responsible=quote.submitted_by.member_no if quote.submitted_by else "供应方",
                current_handler="财务付款角色",
                action_label="处理付款" if quote.offer_type == SupplierQuote.OfferType.QUOTE else "确认完成",
                target_url="/workspace/procurement/?status=accepted",
                updated_at=quote.updated_at or quote.created_at,
            ))

        action_required.extend(proposal_matters)
        action_required.extend(procurement_matters)

    action_ids = {item["id"] for item in action_required}
    waiting = [item for item in waiting if item["id"] not in action_ids]
    sort_key = lambda item: item["updated_at"] or dj_timezone.now()
    action_required.sort(key=sort_key, reverse=True)
    waiting.sort(key=sort_key, reverse=True)
    recently_ended.sort(key=sort_key, reverse=True)
    return {
        "action_required": action_required[:MATTER_DISPLAY_LIMIT],
        "waiting": waiting[:MATTER_DISPLAY_LIMIT],
        "recently_ended": recently_ended[:10],
        "total_active": min(len(action_required), MATTER_DISPLAY_LIMIT) + min(len(waiting), MATTER_DISPLAY_LIMIT),
    }


def build_member_work_items(member: Member) -> dict:
    is_gov = member_can_maintain(member)
    is_fin = is_finance_reviewer(member)
    actionable_proposals: list[ApprovalProposal] = []
    executable_proposals: list[ApprovalProposal] = []
    receipt_quotes: list[SupplierQuote] = []
    payment_quotes: list[SupplierQuote] = []
    governance_stats = {
        "approval_count": 0, "execute_count": 0,
        "receipt_count": 0, "payment_count": 0,
        "approval_overdue_count": 0, "execute_overdue_count": 0,
        "receipt_overdue_count": 0, "payment_overdue_count": 0,
    }
    if is_gov or is_fin:
        (
            actionable_proposals, executable_proposals, receipt_quotes, payment_quotes,
            governance_stats,
        ) = (
            _governance_worksets(member, is_gov=is_gov, is_fin=is_fin)
        )

    items_approval: list[dict] = []
    items_execute: list[dict] = []
    items_receipt: list[dict] = []
    items_payment: list[dict] = []
    items_challenge: list[dict] = []
    total_overdue = sum(
        governance_stats[key] for key in [
            "approval_overdue_count", "execute_overdue_count",
            "receipt_overdue_count", "payment_overdue_count",
        ]
    )

    if is_gov or is_fin:
        # ── approval pending ──
        for p in actionable_proposals:
            overdue = _hours_since(p.submitted_at) > OVERDUE_APPROVAL_HOURS
            items_approval.append({
                "item_type": "approval",
                "priority": _priority_for_proposal(p),
                "title": p.title,
                "summary": f"提案 {p.proposal_id} · {p.get_proposal_type_display()} · {p.get_approval_tier_display()}",
                "target_url": "/workspace/proposals/",
                "is_overdue": overdue,
                "age_hours": int(_hours_since(p.submitted_at)),
                "created_at": p.submitted_at,
            })

        # ── execute pending ──
        for p in executable_proposals:
            overdue = _hours_since(p.resolved_at) > OVERDUE_EXECUTE_HOURS
            items_execute.append({
                "item_type": "execute",
                "priority": _priority_for_proposal(p),
                "title": p.title,
                "summary": f"提案 {p.proposal_id} · 可执行",
                "target_url": "/workspace/proposals/",
                "is_overdue": overdue,
                "age_hours": int(_hours_since(p.resolved_at)),
                "created_at": p.resolved_at,
            })

        # ── receipt pending ──
        for q in receipt_quotes:
            overdue = _hours_since(q.updated_at or q.created_at) > OVERDUE_RECEIPT_HOURS
            items_receipt.append({
                "item_type": "receipt",
                "priority": "normal",
                "title": f"验收：{q.resource.name or q.resource_id}",
                "summary": f"报价 {q.quote_id} · 数量 {q.available_quantity} · {q.get_offer_type_display()}",
                "target_url": "/workspace/procurement/?status=accepted",
                "is_overdue": overdue,
                "age_hours": int(_hours_since(q.updated_at or q.created_at)),
                "created_at": q.updated_at or q.created_at,
            })

        # ── payment pending ──
        for q in payment_quotes:
            overdue = _hours_since(q.updated_at or q.created_at) > OVERDUE_PAYMENT_HOURS
            items_payment.append({
                "item_type": "payment",
                "priority": "normal",
                "title": f"{'付款' if q.offer_type == SupplierQuote.OfferType.QUOTE else '捐赠完成'}：{q.resource.name or q.resource_id}",
                "summary": f"报价 {q.quote_id} · 金额 {q.estimated_total_amount} {q.currency}",
                "target_url": "/workspace/procurement/?status=accepted",
                "is_overdue": overdue,
                "age_hours": int(_hours_since(q.updated_at or q.created_at)),
                "created_at": q.updated_at or q.created_at,
            })

        # ── challenges pending ──
        challenges = list(
            ProcurementChallenge.objects.filter(status=ProcurementChallenge.Status.SUBMITTED)
            .select_related("quote__resource")
            .order_by("-created_at")
        )
        for ch in challenges:
            items_challenge.append({
                "item_type": "challenge",
                "priority": "normal",
                "title": f"质疑：{ch.get_challenge_type_display()}",
                "summary": f"报价 {ch.quote_id} · {ch.public_reason[:80]}",
                "target_url": "",
                "is_overdue": _hours_since(ch.created_at) > OVERDUE_APPROVAL_HOURS,
                "age_hours": int(_hours_since(ch.created_at)),
                "created_at": ch.created_at,
            })

    return {
        "approval_pending": items_approval,
        "execute_pending": items_execute,
        "receipt_pending": items_receipt,
        "payment_pending": items_payment,
        "challenge_pending": items_challenge,
        "approval_pending_count": governance_stats["approval_count"],
        "execute_pending_count": governance_stats["execute_count"],
        "receipt_pending_count": governance_stats["receipt_count"],
        "payment_pending_count": governance_stats["payment_count"],
        "total_pending": sum(
            governance_stats[key] for key in [
                "approval_count", "execute_count", "receipt_count", "payment_count",
            ]
        ) + len(items_challenge),
        "total_overdue": total_overdue,
        "matters": build_member_matters(
            member, is_gov=is_gov, is_fin=is_fin,
            actionable_proposals=actionable_proposals,
            executable_proposals=executable_proposals,
            receipt_quotes=receipt_quotes,
            payment_quotes=payment_quotes,
        ),
    }
