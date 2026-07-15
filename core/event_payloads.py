"""Public ledger payload builders for the unified event ledger (v2).

All builders return a dict with ``schema`` == ``PUBLIC_LEDGER_SCHEMA``.
Private information is recorded as *private_commitments* entries,
never as raw values in the public payload.
"""

from __future__ import annotations

from typing import Any

from .event_ledger import PUBLIC_LEDGER_SCHEMA
from .models import Dispute, LedgerEntry, Member, Proposal, ProposalVote, Resource, RoleAssignment, SystemEvent, Task


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


def dispute_event_payload(
    dispute: Dispute,
    *,
    action: str,
    actor: dict[str, Any] | None = None,
    previous_status: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    claimant_label = _public_member_label(
        _member_label(dispute.claimant_member), dispute.claimant_member.member_no
    ) if dispute.claimant_member_id else ""
    return _public_event_payload(
        subject_type="dispute",
        subject_ref=_public_ref("dispute", dispute.dispute_id),
        subject_label=dispute.dispute_type,
        action=action,
        stage=dispute.status,
        summary=f"申诉 {dispute.get_dispute_type_display()}（{claimant_label}）{action}。",
        public_facts={
            "dispute_type": dispute.dispute_type,
            "status": dispute.status,
            "claimant_label": claimant_label,
        },
        private_commitments=[
            _private("claimant_member_no", reason="申诉人编号属于隐私"),
            _private("claimant_member_id", reason="申诉人内部ID"),
            _private("respondent_member_no", reason="被申诉人编号属于隐私"),
            _private("respondent_member_id", reason="被申诉人内部ID"),
            _private("related_task_id", reason="关联任务内部ID"),
            _private("related_ledger_entry_id", reason="关联账本内部ID"),
            _private("facts", reason="详细事实不公开"),
            _private("evidence_refs", reason="证据引用不公开"),
            _private("handler", reason="处理人标识"),
            _private("reviewer", reason="审核人标识"),
            _private("resolution_raw", present=bool(dispute.resolution), reason="处理结果原文不公开"),
            _private("actor", present=bool(actor), reason="操作人属于隐私"),
            _private("metadata", present=bool(dispute.metadata), reason="元数据"),
        ],
    )


def proposal_payload(proposal: Proposal) -> dict[str, Any]:
    proposer_label = _public_member_label(
        _member_label(proposal.proposer_member), proposal.proposer_member.member_no
    ) if proposal.proposer_member_id else ""
    ref = _public_ref("proposal", proposal.proposal_no) if proposal.proposal_no else _public_ref(
        "proposal", proposal.proposal_type, proposal.title
    )
    return _public_event_payload(
        subject_type="proposal",
        subject_ref=ref,
        subject_label=proposal.proposal_type,
        action=proposal.status,
        stage=proposal.status,
        summary=f"提案 {proposal.proposal_no or '无编号'}「{proposal.title}」{proposal.get_status_display()}。",
        public_facts={
            "proposal_no": proposal.proposal_no or "",
            "proposal_type": proposal.proposal_type,
            "title": proposal.title,
            "status": proposal.status,
            "proposer_label": proposer_label,
            "pass_ratio": proposal.pass_ratio,
            "quorum_count": proposal.quorum_count,
        },
        private_commitments=[
            _private("proposal_id", reason="提案内部ID"),
            _private("proposer_member_no", reason="提案人编号属于隐私"),
            _private("proposer_member_id", reason="提案人内部ID"),
            _private("proposer_role_assignment_id", reason="提案人角色任命内部ID"),
            _private("organization_id", reason="组织内部ID"),
            _private("payload", present=bool(proposal.payload_json), reason="提案payload不公开"),
            _private("result", present=bool(proposal.result_json), reason="投票结果详情不公开"),
        ],
    )


def proposal_vote_payload(vote: ProposalVote, *, previous_choice: str | None = None) -> dict[str, Any]:
    proposal = vote.proposal
    voter_label = _public_member_label(
        _member_label(vote.voter_member), vote.voter_member.member_no
    )
    ref = _public_ref("proposal", proposal.proposal_no) if proposal.proposal_no else _public_ref(
        "proposal", proposal.proposal_type, proposal.title
    )
    return _public_event_payload(
        subject_type="proposal_vote",
        subject_ref=ref,
        subject_label=proposal.proposal_type,
        action=vote.choice,
        stage=proposal.status,
        summary=f"提案 {proposal.proposal_no or '无编号'} 收到投票：{vote.get_choice_display()}（{voter_label}）。",
        public_facts={
            "proposal_no": proposal.proposal_no or "",
            "proposal_type": proposal.proposal_type,
            "title": proposal.title,
            "choice": vote.choice,
            "voter_label": voter_label,
        },
        private_commitments=[
            _private("proposal_id", reason="提案内部ID"),
            _private("voter_member_no", reason="投票人编号属于隐私"),
            _private("voter_member_id", reason="投票人内部ID"),
            _private("voter_role_assignment_id", reason="投票人角色任命内部ID"),
        ],
    )


def proposal_execution_payload(proposal: Proposal, *, action_type: str, execution_status: str) -> dict[str, Any]:
    base = proposal_payload(proposal)
    public_facts = dict(base["public_facts"])
    public_facts["execution_action_type"] = action_type
    public_facts["execution_status"] = execution_status
    private_commitments = list(base["private_commitments"])
    private_commitments.append(_private("execution_result", present=True, reason="执行结果包含内部对象ID"))
    return _public_event_payload(
        subject_type="proposal_execution",
        subject_ref=base["subject"]["ref"],
        subject_label=proposal.proposal_type,
        action="executed",
        stage=proposal.status,
        summary=f"提案 {proposal.proposal_no} 执行完成：{action_type}。",
        public_facts=public_facts,
        private_commitments=private_commitments,
    )


# Public aliases for backward-compatible imports.
iso_or_none = _iso
member_display_name = _member_label
public_member_label = _public_member_label
