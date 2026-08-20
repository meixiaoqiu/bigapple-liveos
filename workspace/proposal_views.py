"""Workspace views for unified ApprovalProposal management."""

from __future__ import annotations

from django.contrib import messages
from django.db.models import Q
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from worlds.routing import world_redirect

from core.access import is_finance_reviewer, member_can_administer
from core.authorization_services import AuthorizationService
from core.exceptions import DomainError
from core.electorate_rule_services import (
    create_electorate_rule_template,
    electorate_eligibility_for_proposal,
    latest_published_rule_for_proposal_type,
    MANAGE_PROPOSAL_POLICIES_PERMISSION,
    publish_electorate_rule_version,
)
from core.models import ApprovalProposal, ApprovalDecision, ElectorateRuleVersion, Member, ProposalBallot, SupplierQuote
from core.proposal_services import (
    approve_proposal,
    execute_proposal,
    member_available_approval_roles,
    proposal_approved_roles,
    proposal_is_actionable_by,
    proposal_is_executable_by,
    proposal_missing_roles,
    proposal_required_roles,
    proposal_target_url,
    reject_proposal,
)
from core.unified_proposal_services import (
    activate_waiting_proposals_for_rule,
    cast_electorate_ballot,
    execute_electorate_proposal,
    finalize_electorate_proposal,
    proposal_tally,
)
from core.role_catalog import ROLE_DEFINITIONS
from live_os.access import page_forbidden

from .access import require_workspace_member


def _check_member(request: HttpRequest) -> Member | HttpResponseForbidden:
    # 统一提案的选民范围可以包含贡献者；是否可投票由冻结快照和
    # 当前资格共同决定，不能在页面入口提前收窄为守约者。
    return require_workspace_member(request)


def _governance_or_finance_or_forbidden(member: Member) -> bool:
    if member_can_administer(member):
        return False
    if is_finance_reviewer(member):
        return False
    return True


def _member_has_permission(member: Member, permission_code: str) -> bool:
    """为页面展示读取具体权限；授权后端异常时失败关闭。"""

    try:
        return AuthorizationService().member_has_permission(member, permission_code)
    except DomainError:
        return False


def _electorate_authorities(proposal: ApprovalProposal, member: Member) -> dict[str, bool]:
    """按提案适配器计算独立判定与执行能力。"""

    try:
        from core.proposal_adapters import proposal_adapter_for

        adapter = proposal_adapter_for(proposal.proposal_type)
    except DomainError:
        return {"can_resolve": False, "can_execute": False}
    return {
        "can_resolve": _member_has_permission(member, adapter.resolution_permission),
        "can_execute": _member_has_permission(member, adapter.execution_permission),
    }


def _electorate_proposal_is_visible(proposal: ApprovalProposal, member: Member) -> bool:
    """允许业务参与者及独立判定、执行能力持有人查看提案。"""

    if proposal.submitted_by_id == member.pk or proposal.elector_snapshots.filter(member=member).exists():
        return True
    authorities = _electorate_authorities(proposal, member)
    return authorities["can_resolve"] or authorities["can_execute"]


def _proposal_display(proposal: ApprovalProposal, member: Member) -> dict:
    """Build a template-safe dict for one proposal."""
    is_electorate = proposal.strategy_type == ApprovalProposal.StrategyType.ELECTORATE
    eligibility = None
    latest_ballot = None
    tally = None
    electorate_authorities = {"can_resolve": False, "can_execute": False}
    if is_electorate:
        electorate_authorities = _electorate_authorities(proposal, member)
        adapter_excluded_id = None
        try:
            from core.proposal_adapters import proposal_adapter_for
            adapter_excluded_id = proposal_adapter_for(proposal.proposal_type).excluded_member_id(proposal)
            eligibility = electorate_eligibility_for_proposal(
                proposal=proposal, member=member, excluded_member_id=adapter_excluded_id,
            )
            tally = proposal_tally(proposal)
        except DomainError:
            eligibility = {"allowed": False, "message": "当前无法完成授权资格检查，投票已失败关闭。"}
        latest_ballot = proposal.ballots.filter(voter=member).order_by("-revision").first()
    return {
        "proposal_id": proposal.proposal_id,
        "proposal_type": proposal.proposal_type,
        "proposal_type_label": proposal.get_proposal_type_display(),
        "title": proposal.title,
        "summary": proposal.summary,
        "status": proposal.status,
        "status_label": proposal.get_status_display(),
        "approval_tier": proposal.approval_tier,
        "approval_tier_label": proposal.get_approval_tier_display(),
        "required_roles": proposal_required_roles(proposal),
        "approved_roles": proposal_approved_roles(proposal),
        "missing_roles": proposal_missing_roles(proposal),
        "submitted_by_display": proposal.submitted_by.display_name or proposal.submitted_by.member_no,
        "submitted_at": proposal.submitted_at,
        "target_url": proposal_target_url(proposal),
        "is_actionable": proposal_is_actionable_by(member, proposal),
        "is_executable": (
            proposal.status == ApprovalProposal.Status.APPROVED
            and electorate_authorities["can_execute"]
            if is_electorate
            else proposal_is_executable_by(member, proposal)
        ),
        "available_roles": member_available_approval_roles(member, proposal),
        "is_electorate": is_electorate,
        "can_resolve_electorate": electorate_authorities["can_resolve"],
        "can_execute_electorate": electorate_authorities["can_execute"],
        "eligibility": eligibility,
        "latest_ballot": latest_ballot,
        "tally": tally,
        "voting_deadline": proposal.voting_deadline,
    }


@require_GET
def proposal_list(request: HttpRequest) -> HttpResponse:
    member = _check_member(request)
    if isinstance(member, HttpResponseForbidden):
        return member
    all_proposals = list(
        ApprovalProposal.objects.select_related("submitted_by")
        .order_by("-submitted_at")
    )

    # Partition
    awaiting_action = [
        p for p in all_proposals
        if p.status == ApprovalProposal.Status.SUBMITTED
        and proposal_is_actionable_by(member, p)
    ]
    # 固定审批与 electorate 使用不同执行端点；旧待执行区块只能接收
    # 非 electorate 提案，避免同一提案同时出现新旧两个执行按钮。
    awaiting_execute = [
        p for p in all_proposals
        if p.status == ApprovalProposal.Status.APPROVED
        and p.strategy_type != ApprovalProposal.StrategyType.ELECTORATE
        and proposal_is_executable_by(member, p)
    ]
    visible = [
        p for p in all_proposals
        if p.strategy_type == ApprovalProposal.StrategyType.ELECTORATE
        and _electorate_proposal_is_visible(p, member)
        or p.strategy_type != ApprovalProposal.StrategyType.ELECTORATE
        and not _governance_or_finance_or_forbidden(member)
    ]
    recent = visible[:20]
    electorate_awaiting_execute = [
        p for p in recent
        if p.status == ApprovalProposal.Status.APPROVED
        and p.strategy_type == ApprovalProposal.StrategyType.ELECTORATE
        and _electorate_authorities(p, member)["can_execute"]
    ]

    dispatched = [
        _proposal_display(p, member) for p in awaiting_action
    ]
    executable = [
        _proposal_display(p, member) for p in awaiting_execute
    ]
    recent_displays = [
        _proposal_display(p, member) for p in recent
    ]

    return render(
        request,
        "workspace/proposal_list.html",
        {
            "member": member,
            "pending_count": len(awaiting_action),
            "execute_count": len(awaiting_execute) + len(electorate_awaiting_execute),
            "dispatched": dispatched,
            "executable": executable,
            "recent": recent_displays,
            "can_manage_proposal_policies": _member_has_permission(
                member, MANAGE_PROPOSAL_POLICIES_PERMISSION,
            ),
            "is_finance": is_finance_reviewer(member),
        },
    )


@require_http_methods(["GET", "POST"])
def member_admission_policy(request: HttpRequest) -> HttpResponse:
    member = _check_member(request)
    if isinstance(member, HttpResponseForbidden):
        return member
    if not _member_has_permission(member, MANAGE_PROPOSAL_POLICIES_PERMISSION):
        return page_forbidden("需要提案政策维护权限。")
    if request.method == "POST":
        role_codes = [value for value in request.POST.getlist("role_codes") if value]
        include_contributors = request.POST.get("include_contributors") == "on"
        selectors = [{"role_code": value} for value in role_codes]
        if include_contributors:
            selectors.append({"participation_status": "contributor"})
        if not selectors:
            messages.error(request, "请至少选择一种选民范围。")
        else:
            selector = selectors[0] if len(selectors) == 1 else {"any": selectors}
            try:
                template = create_electorate_rule_template(
                    proposal_type=ApprovalProposal.ProposalType.MEMBER_APPLICATION,
                    rule_code="member-admission",
                    name="守约者准入",
                    created_by=member,
                )
                version = publish_electorate_rule_version(
                    template=template,
                    selector_config=selector,
                    approve_threshold=int(request.POST.get("approve_threshold", "1")),
                    reject_threshold=int(request.POST.get("reject_threshold", "1")),
                    minimum_participation=int(request.POST.get("minimum_participation", "1")),
                    voting_duration_hours=int(request.POST.get("voting_duration_hours", "168")),
                    unresolved_outcome=request.POST.get("unresolved_outcome", "expired"),
                    published_by=member,
                )
                activated = activate_waiting_proposals_for_rule(rule_version=version)
                messages.success(request, f"准入政策第 {version.version} 版已发布，并激活 {activated} 项等待报名。")
                return world_redirect(request, "workspace-member-admission-policy")
            except (DomainError, ValueError) as exc:
                messages.error(request, f"政策发布失败：{exc}")
    current = latest_published_rule_for_proposal_type(ApprovalProposal.ProposalType.MEMBER_APPLICATION)
    return render(request, "workspace/member_admission_policy.html", {
        "member": member,
        "current_rule": current,
        "role_options": [
            {"code": item.code, "label": item.display_name}
            for item in ROLE_DEFINITIONS
            if item.electorate_selectable
        ],
    })


@require_POST
def electorate_proposal_vote(request: HttpRequest, proposal_id: str) -> HttpResponse:
    member = _check_member(request)
    if isinstance(member, HttpResponseForbidden):
        return member
    proposal = get_object_or_404(ApprovalProposal, proposal_id=proposal_id)
    try:
        cast_electorate_ballot(
            proposal=proposal,
            voter=member,
            choice=request.POST.get("choice", ""),
            reason=request.POST.get("reason", "").strip(),
        )
        messages.success(request, "实名票据已保存；再次投票会追加一份修订。")
    except DomainError as exc:
        messages.error(request, str(exc))
    return world_redirect(request, "workspace-approval-proposals")


@require_POST
def electorate_proposal_finalize(request: HttpRequest, proposal_id: str) -> HttpResponse:
    member = _check_member(request)
    if isinstance(member, HttpResponseForbidden):
        return member
    proposal = get_object_or_404(ApprovalProposal, proposal_id=proposal_id)
    try:
        finalize_electorate_proposal(proposal=proposal, actor=member)
        messages.success(request, "提案已按冻结政策完成判定。")
    except DomainError as exc:
        messages.error(request, str(exc))
    return world_redirect(request, "workspace-approval-proposals")


@require_POST
def electorate_proposal_execute(request: HttpRequest, proposal_id: str) -> HttpResponse:
    member = _check_member(request)
    if isinstance(member, HttpResponseForbidden):
        return member
    proposal = get_object_or_404(ApprovalProposal, proposal_id=proposal_id)
    try:
        record = execute_electorate_proposal(proposal=proposal, actor=member)
        if record.status == record.Status.SUCCEEDED:
            messages.success(request, "提案执行成功。")
        else:
            messages.error(request, "提案执行失败，未留下部分业务状态，可在修复条件后重试。")
    except DomainError as exc:
        messages.error(request, str(exc))
    return world_redirect(request, "workspace-approval-proposals")


@require_http_methods(["POST"])
def approval_proposal_approve(request: HttpRequest, proposal_id: str) -> HttpResponse:
    member = _check_member(request)
    if isinstance(member, HttpResponseForbidden):
        return member
    if _governance_or_finance_or_forbidden(member):
        return page_forbidden("仅管理员或财务职责成员可访问。")

    proposal = get_object_or_404(ApprovalProposal, proposal_id=proposal_id)
    available = member_available_approval_roles(member, proposal)

    if not available:
        messages.error(request, "你没有可用的审批角色，或已审批过该提案。")
        return world_redirect(request, "workspace-approval-proposals")

    role = available[0]
    reason = request.POST.get("reason", "").strip()

    try:
        approve_proposal(proposal=proposal, approved_by=member, role=role, reason=reason)
        missing = proposal_missing_roles(proposal)
        if missing:
            messages.success(request, f"提案 {proposal_id} {role} 审批通过，尚缺：{'、'.join(missing)}。")
        else:
            messages.success(request, f"提案 {proposal_id} 审批通过，可执行。")
    except DomainError as exc:
        messages.error(request, str(exc))

    return world_redirect(request, "workspace-approval-proposals")


@require_http_methods(["POST"])
def approval_proposal_reject(request: HttpRequest, proposal_id: str) -> HttpResponse:
    member = _check_member(request)
    if isinstance(member, HttpResponseForbidden):
        return member
    if _governance_or_finance_or_forbidden(member):
        return page_forbidden("仅管理员或财务职责成员可访问。")

    proposal = get_object_or_404(ApprovalProposal, proposal_id=proposal_id)
    available = member_available_approval_roles(member, proposal)

    if not available:
        messages.error(request, "你没有可用的审批角色。")
        return world_redirect(request, "workspace-approval-proposals")

    role = available[0]
    reason = request.POST.get("reason", "").strip()

    try:
        reject_proposal(proposal=proposal, rejected_by=member, role=role, reason=reason)
        messages.success(request, f"提案 {proposal_id} 已拒绝。")
    except DomainError as exc:
        messages.error(request, str(exc))

    return world_redirect(request, "workspace-approval-proposals")


@require_http_methods(["POST"])
def approval_proposal_execute(request: HttpRequest, proposal_id: str) -> HttpResponse:
    member = _check_member(request)
    if isinstance(member, HttpResponseForbidden):
        return member
    if _governance_or_finance_or_forbidden(member):
        return page_forbidden("仅管理员或财务职责成员可访问。")

    proposal = get_object_or_404(ApprovalProposal, proposal_id=proposal_id)

    try:
        execute_proposal(proposal=proposal, actor=member)
        messages.success(request, f"提案 {proposal_id} 已执行。")
    except DomainError as exc:
        messages.error(request, str(exc))

    return world_redirect(request, "workspace-approval-proposals")
