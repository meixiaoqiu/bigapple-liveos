"""Public ledger payload builders for the unified event ledger (v2).

All builders return a dict with ``schema`` == ``PUBLIC_LEDGER_SCHEMA``.
Private information is recorded as *private_commitments* entries,
never as raw values in the public payload.
"""

from __future__ import annotations

from typing import Any

from .event_ledger import PUBLIC_LEDGER_SCHEMA
from .models import (
    ApprovalProposal,
    LedgerEntry,
    Member,
    Resource,
    RoleAssignment,
    SupplierQuote,
    SystemEvent,
    Task,
)


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _member_label(member: Member | None) -> str:
    """Raw display name — only for generating de-identified labels, never directly in public payload."""
    if member is None:
        return ""
    return str(member.display_name or member.profile.get("display_name") or member.member_no)


def _public_member_label(name: str, member_no: str = "") -> str:
    """De-identified public label."""
    label = (str(name or "").strip() or str(member_no or "").strip() or "新成员")
    if len(label) <= 1:
        return "*"
    if len(label) == 2:
        return label[0] + "*"
    return label[0] + "**" + label[-1]


def _public_ref(*parts: object) -> str:
    """Build a stable, non-PK public reference string."""
    cleaned = [str(p).strip().replace(" ", "-") for p in parts if str(p or "").strip()]
    return ":".join(cleaned) or "unknown"


# ---------------------------------------------------------------------------
# private-commitment helpers
# ---------------------------------------------------------------------------

def _private(name: str, *, present: bool = True, reason: str = "") -> dict[str, Any]:
    c: dict[str, Any] = {"name": name, "present": present}
    if reason:
        c["reason"] = reason
    return c


# ---------------------------------------------------------------------------
# schema wrapper
# ---------------------------------------------------------------------------

def _public_event_payload(
    *,
    subject_type: str,
    subject_ref: str,
    subject_label: str,
    action: str,
    stage: str,
    summary: str,
    public_facts: dict[str, Any] | None = None,
    private_commitments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a v2 public ledger payload."""
    return {
        "schema": PUBLIC_LEDGER_SCHEMA,
        "subject": {
            "type": subject_type,
            "ref": subject_ref,
            "label": subject_label,
        },
        "action": action,
        "stage": stage,
        "summary": summary,
        "public_facts": dict(public_facts or {}),
        "private_commitments": list(private_commitments or []),
    }


def deliberator_exam_change_payload(
    *, subject_type: str, subject_ref: str, action: str, stage: str,
    summary: str, public_facts: dict[str, Any],
) -> dict[str, Any]:
    """Build answer-free public metadata for an exam bank or policy change."""
    return _public_event_payload(
        subject_type=subject_type,
        subject_ref=subject_ref,
        subject_label="执衡者资格考试配置",
        action=action,
        stage=stage,
        summary=summary,
        public_facts=public_facts,
        private_commitments=[_private("exam_content", reason="题目全文、选项、答案和解析不进入公开事件账本")],
    )


# =========================================================================
# Payload builders
# =========================================================================

def role_assignment_payload(assignment: RoleAssignment) -> dict[str, Any]:
    role = assignment.role
    public_label = _public_member_label(_member_label(assignment.member), assignment.member.member_no)
    return _public_event_payload(
        subject_type="role_assignment",
        subject_ref=_public_ref("role-assignment", role.name, public_label),
        subject_label=role.name,
        action="assigned" if assignment.status == assignment.Status.ACTIVE else "revoked",
        stage=assignment.status,
        summary=f"成员 {public_label} {assignment.get_status_display()} {role.name}。",
        public_facts={
            "member_label": public_label,
            "role_name": role.name,
            "organization_name": role.organization.name,
            "status": assignment.status,
            "source_type": assignment.source_type,
        },
        private_commitments=[
            _private("role_assignment_id", reason="角色任命内部ID"),
            _private("member_id", reason="成员内部ID"),
            _private("role_id", reason="角色内部ID"),
            _private("organization_id", reason="组织内部ID"),
            _private("granted_by_id", reason="任命者内部ID"),
            _private("revoked_by_id", reason="撤销者内部ID"),
        ],
    )


def actor_member_from_ref(actor_ref: dict[str, Any] | None) -> Member | None:
    if not actor_ref:
        return None
    actor_id = actor_ref.get("actor_id")
    if not actor_id:
        return None
    return Member.objects.filter(member_no=actor_id).first()


def ledger_entry_payload(entry: LedgerEntry) -> dict[str, Any]:
    public_label = _public_member_label(_member_label(entry.member), entry.member.member_no)
    return _public_event_payload(
        subject_type="ledger_entry",
        subject_ref=_public_ref("ledger-entry", entry.ledger_entry_id or entry.pk),
        subject_label=f"积分流水",
        action=entry.entry_type,
        stage=entry.status,
        summary=f"成员 {public_label} {entry.get_entry_type_display()} {entry.amount} 积分。",
        public_facts={
            "member_label": public_label,
            "amount": entry.amount,
            "entry_type": entry.entry_type,
            "status": entry.status,
            "rule_version": entry.rule_version,
        },
        private_commitments=[
            _private("member_no", reason="成员编号属于隐私"),
            _private("member_id", reason="成员内部ID"),
            _private("reason_raw", present=bool(entry.reason), reason="账本原因原文不公开"),
            _private("related_event_id", reason="关联事件ID属于内部"),
            _private("system_event_id", reason="关联系统事件内部ID"),
            _private("created_by", reason="创建者标识"),
            _private("reviewer", reason="审核者标识"),
        ],
    )


def ledger_entry_event_type(entry: LedgerEntry) -> str:
    if entry.entry_type == LedgerEntry.EntryType.REVERSAL or entry.reverses_entry_id:
        return SystemEvent.EventType.CREDIT_REVERSED
    if entry.entry_type in {LedgerEntry.EntryType.CONSUMPTION, LedgerEntry.EntryType.PENALTY} or entry.amount < 0:
        return SystemEvent.EventType.CREDIT_DEDUCTED
    if entry.entry_type in {LedgerEntry.EntryType.CORRECTION, LedgerEntry.EntryType.COMPENSATION}:
        return SystemEvent.EventType.CREDIT_ADJUSTED
    return SystemEvent.EventType.CREDIT_EARNED


def task_event_payload(
    task: Task,
    *,
    action: str,
    actor: dict[str, Any] | None = None,
    previous_status: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assignee_label = _public_member_label(
        _member_label(task.assignee_member), task.assignee_member.member_no
    ) if task.assignee_member_id else "未指派"
    facts: dict[str, Any] = {
        "title": task.title,
        "task_type": task.task_type,
        "status": task.status,
    }
    if task.assignee_member_id:
        facts["assignee_label"] = assignee_label
    if task.plan_node_id:
        facts["plan_node_id"] = task.plan_node_id
    private: list[dict[str, Any]] = [
        _private("assignee_member_no", reason="指派人成员编号属于隐私"),
        _private("assignee_member_id", reason="指派人内部ID"),
        _private("actor", present=bool(actor), reason="操作人属于隐私"),
        _private("metadata", present=bool(task.metadata), reason="元数据"),
    ]
    _TASK_EXTRA_PUBLIC_KEYS: frozenset[str] = frozenset(["action_type", "accepted"])
    if extra:
        for k, v in extra.items():
            if k in facts:
                continue
            if k in _TASK_EXTRA_PUBLIC_KEYS:
                facts[k] = v
            else:
                private.append(_private(k, present=True, reason="任务额外字段不公开"))
    return _public_event_payload(
        subject_type="task",
        subject_ref=_public_ref("task", task.task_id),
        subject_label=task.title,
        action=action,
        stage=task.status,
        summary=f"任务「{task.title}」{action}，当前状态 {task.get_status_display()}。",
        public_facts=facts,
        private_commitments=private,
    )


def resource_adjustment_payload(
    resource: Resource,
    *,
    actor: dict[str, Any] | None = None,
    old_stock,
    delta,
    reason: str,
    warning: bool,
    transaction_id: str = "",
) -> dict[str, Any]:
    name = resource.name or resource.resource_id or str(resource.pk)
    return _public_event_payload(
        subject_type="resource",
        subject_ref=_public_ref("resource", resource.resource_id),
        subject_label=name,
        action="adjusted",
        stage="adjusted",
        summary=f"资源「{name}」调整 {delta} {resource.unit}。",
        public_facts={
            "name": name,
            "resource_type": resource.resource_type,
            "unit": resource.unit,
            "delta": str(delta),
            "is_warning": warning,
            "transaction_id": transaction_id,
        },
        private_commitments=[
            _private("old_stock", reason="库存精确值"),
            _private("new_stock", reason="库存精确值"),
            _private("warning_threshold", reason="预警阈值"),
            _private("reason_raw", present=bool(reason), reason="调整原因不公开"),
            _private("actor", present=bool(actor), reason="操作人属于隐私"),
        ],
    )


def credential_grant_payload(grant) -> dict[str, Any]:
    template = grant.template
    recipient_label = _public_member_label(
        grant.member.display_name or "", grant.member.member_no or ""
    )
    return _public_event_payload(
        subject_type="credential_grant",
        subject_ref=f"credential:{template.code}:{grant.display_no or grant.serial_no or ''}",
        subject_label=f"{template.name} {grant.display_no or ''}",
        action="granted",
        stage=grant.status,
        summary=f"成员 {recipient_label} 获得凭证：{template.name} {grant.display_no or ''}。",
        public_facts={
            "template_code": template.code,
            "template_name": template.name,
            "credential_type": template.credential_type,
            "display_no": grant.display_no,
            "serial_no": grant.serial_no,
            "recipient_public_label": recipient_label,
            "source_type": grant.source_type,
        },
        private_commitments=[
            _private("member_id", reason="成员内部ID"),
            _private("grant_id", reason="凭证发放内部ID"),
        ],
    )


def expense_claim_payload(claim) -> dict[str, Any]:
    claimant_label = str(claim.claimant_member.display_name or claim.claimant_member.member_no)
    return _public_event_payload(
        subject_type="expense_claim",
        subject_ref=_public_ref("expense-claim", claim.claim_id),
        subject_label=claim.title,
        action="submitted",
        stage=claim.status,
        summary=f"报销申请《{claim.title}》{claim.amount} {claim.currency}",
        public_facts={
            "source": "finance",
            "claim_id": claim.claim_id,
            "title": claim.title,
            "amount": str(claim.amount),
            "currency": claim.currency,
            "category": claim.category,
            "category_label": claim.get_category_display(),
            "status": claim.status,
            "status_label": claim.get_status_display(),
            "claimant_public_name": claimant_label,
        },
        private_commitments=[
            _private("member_id", reason="申请人内部ID"),
        ],
    )


def finance_review_payload(review) -> dict[str, Any]:
    reviewer_label = str(review.reviewer_member.display_name or review.reviewer_member.member_no)
    reason = str(review.reason or "")[:200]
    return _public_event_payload(
        subject_type="finance_review",
        subject_ref=_public_ref("finance-review", review.review_id),
        subject_label=f"审核-{review.claim.claim_id}",
        action=review.decision,
        stage=review.decision,
        summary=f"报销审核：{review.get_decision_display()}",
        public_facts={
            "source": "finance",
            "claim_id": review.claim.claim_id,
            "title": review.claim.title,
            "amount": str(review.claim.amount),
            "currency": review.claim.currency,
            "decision": review.decision,
            "decision_label": review.get_decision_display(),
            "reason": reason,
            "reviewer_public_name": reviewer_label,
        },
        private_commitments=[
            _private("member_id", reason="审核人内部ID"),
        ],
    )


def finance_transaction_payload(txn) -> dict[str, Any]:
    payer_label = str(txn.recorded_by.display_name or txn.recorded_by.member_no) if txn.recorded_by_id else ""
    return _public_event_payload(
        subject_type="finance_transaction",
        subject_ref=_public_ref("finance-transaction", txn.transaction_id),
        subject_label=txn.summary,
        action="recorded",
        stage="recorded",
        summary=f"{txn.get_transaction_type_display()} {txn.amount} {txn.currency}",
        public_facts={
            "source": "finance",
            "transaction_id": txn.transaction_id,
            "claim_id": txn.claim.claim_id if txn.claim_id else "",
            "transaction_type": txn.transaction_type,
            "transaction_type_label": txn.get_transaction_type_display(),
            "amount": str(txn.amount),
            "currency": txn.currency,
            "direction": txn.direction,
            "summary": txn.summary,
            "payer_public_name": payer_label,
        },
        private_commitments=[],
    )


# ── procurement event payload builders ─────────────────────────────


def supplier_offer_payload(
    quote: SupplierQuote,
    *,
    action: str,
    actor: Member | None = None,
) -> dict[str, Any]:
    """Build a public-safe event payload for a SupplierQuote lifecycle action."""
    resource = quote.resource
    resource_name = resource.name or resource.resource_id
    submitted_by_label = (
        _public_member_label(quote.submitted_by.display_name or "", quote.submitted_by.member_no)
        if quote.submitted_by
        else ""
    )
    actor_label = (
        _public_member_label(actor.display_name or "", actor.member_no)
        if actor
        else ""
    )
    return _public_event_payload(
        subject_type="supplier_quote",
        subject_ref=_public_ref("supplier-quote", quote.quote_id),
        subject_label=f"报价 {quote.quote_id}",
        action=action,
        stage=quote.decision_status,
        summary=f"报价 {quote.quote_id}（{resource_name}）{action}。",
        public_facts={
            "quote_id": quote.quote_id,
            "resource_id": resource.resource_id,
            "resource_name": resource_name,
            "submitted_by_display": submitted_by_label,
            "actor_display": actor_label,
            "offer_type": quote.offer_type,
            "available_quantity": str(quote.available_quantity),
            "unit_price": str(quote.unit_price),
            "currency": quote.currency,
            "decision_status": quote.decision_status,
            "receipt_status": quote.receipt_status,
            "payment_status": quote.payment_status,
            "approval_tier": quote.approval_tier,
            "estimated_total_amount": str(quote.estimated_total_amount),
            "credential_id": quote.performance_credential_id or "",
        },
        private_commitments=[
            _private("metadata", present=bool(quote.metadata), reason="元数据"),
            _private("notes", present=bool(quote.notes), reason="内部备注"),
            _private("decision_reason", present=bool(quote.decision_reason), reason="决策理由"),
            _private("receipt_notes", present=bool(quote.receipt_notes), reason="验收备注"),
        ],
    )


def approval_proposal_payload(
    proposal: ApprovalProposal,
    *,
    action: str,
    actor: Member | None = None,
) -> dict[str, Any]:
    """Build a public-safe event payload for an ApprovalProposal action."""
    actor_label = _public_member_label(
        actor.display_name or "", actor.member_no,
    ) if actor else ""
    submitted_label = _public_member_label(
        proposal.submitted_by.display_name or "",
        proposal.submitted_by.member_no,
    )
    public_title = proposal.title
    public_summary = proposal.summary
    member_application = None
    if proposal.proposal_type == ApprovalProposal.ProposalType.MEMBER_APPLICATION:
        from .models import MemberApplication

        member_application = MemberApplication.objects.select_related("linked_member").filter(
            application_id=proposal.target_id,
        ).first()
        public_title = "守约者准入提案"
        public_summary = "社区正在按已发布政策决定一项守约者报名。"
    public_facts = {
        "approval_proposal_id": proposal.proposal_id,
        "ap_type": proposal.proposal_type,
        "ap_title": public_title,
        "ap_summary": public_summary,
        "ap_status": proposal.status,
        "ap_strategy_type": proposal.strategy_type,
        "ap_target_type": proposal.target_type,
        "ap_submitted_by_display": submitted_label,
        "ap_actor_display": actor_label,
    }
    if member_application is not None:
        public_facts.update({
            "application_id": member_application.application_id,
            "public_applicant_label": _public_member_label(
                member_application.applicant_name,
                member_application.linked_member.member_no if member_application.linked_member_id else "",
            ),
            "role_gap": member_application.role_gap,
        })
    if proposal.strategy_type == ApprovalProposal.StrategyType.ELECTORATE:
        from .unified_proposal_services import proposal_tally

        tally = proposal_tally(proposal)
        rule = proposal.electorate_rule_version
        public_facts.update({
            "ap_rule_code": rule.template_id if rule else "",
            "ap_rule_version": rule.version if rule else None,
            "ap_voting_deadline": _iso(proposal.voting_deadline),
            "ap_eligible_count": tally.eligible_count,
            "ap_participation_count": tally.participation_count,
            "ap_approve_count": tally.approve_count,
            "ap_reject_count": tally.reject_count,
            "ap_abstain_count": tally.abstain_count,
        })
    else:
        from .proposal_services import (
            proposal_approved_roles,
            proposal_missing_roles,
            proposal_required_roles,
        )

        public_facts.update({
            "ap_approval_tier": proposal.approval_tier,
            "ap_required_roles": proposal_required_roles(proposal),
            "ap_approved_roles": proposal_approved_roles(proposal),
            "ap_missing_roles": proposal_missing_roles(proposal),
        })
    return _public_event_payload(
        subject_type="approval_proposal",
        subject_ref=_public_ref("approval-proposal", proposal.proposal_id),
        subject_label=public_title,
        action=action,
        stage=proposal.status,
        summary=f"提案 {proposal.proposal_id}（{public_title}）{action}。",
        public_facts=public_facts,
        private_commitments=[
            _private("metadata", present=bool(proposal.metadata), reason="元数据"),
        ],
    )


def electorate_rule_payload(rule_version, *, actor: Member) -> dict[str, Any]:
    """构造不泄露内部选择器配置的规则发布事件。"""

    return _public_event_payload(
        subject_type="electorate_rule_version",
        subject_ref=_public_ref("electorate-rule", rule_version.rule_version_id),
        subject_label=rule_version.template.name,
        action="published",
        stage="published",
        summary=f"选民规则 {rule_version.template.name} 已发布新版本。",
        public_facts={
            "rule_code": rule_version.template_id,
            "rule_version": rule_version.version,
            "proposal_type": rule_version.template.proposal_type,
            "published_by_display": _public_member_label(actor.display_name or "", actor.member_no),
            "published_at": _iso(rule_version.published_at),
        },
        private_commitments=[
            _private("selector_config", present=True, reason="内部选民选择器配置"),
        ],
    )


# Public aliases for backward-compatible imports.
iso_or_none = _iso
member_display_name = _member_label
public_member_label = _public_member_label
