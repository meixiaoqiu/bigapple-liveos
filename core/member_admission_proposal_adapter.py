"""守约者准入对统一提案生命周期的业务适配器。"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from .exceptions import DomainError
from .member_roles import ROLE_COVENANTER, ensure_catalog_role
from .models import ApprovalProposal, Member, MemberApplication, ProposalResolution, RoleAssignment
from .proposal_adapters import ProposalTypeAdapter, register_proposal_adapter
from .role_assignment_services import create_role_assignment


MEMBER_ADMISSION_EXECUTION_PERMISSION = "governance.manage_people"
MEMBER_ADMISSION_RESOLUTION_PERMISSION = "governance.resolve_proposals"


def _application_for(proposal: ApprovalProposal) -> MemberApplication:
    if proposal.target_type != "member_application" or not proposal.target_id:
        raise DomainError("成员准入提案缺少有效报名来源。")
    try:
        return MemberApplication.objects.select_related("linked_member", "linked_member__user").get(
            application_id=proposal.target_id,
        )
    except MemberApplication.DoesNotExist as exc:
        raise DomainError("成员准入提案关联的报名不存在。") from exc


def _excluded_member_id(proposal: ApprovalProposal) -> object | None:
    application = _application_for(proposal)
    return application.linked_member_id


def _execute_member_admission(proposal: ApprovalProposal, actor: Member) -> dict:
    """通过角色任命服务授予一年期守约者资格并同步报名结果。"""

    application = _application_for(proposal)
    applicant = application.linked_member
    if applicant is None:
        raise DomainError("报名尚未绑定成员身份。")
    if applicant.pk == actor.pk:
        raise DomainError("申请人不能执行自己的准入提案。")
    if applicant.status in {Member.Status.SUSPENDED, Member.Status.EXITED}:
        raise DomainError("申请人当前状态不允许准入。")
    if applicant.user_id and not applicant.user.is_active:
        raise DomainError("申请人的登录账号已停用。")
    now = timezone.now()
    term_end = now + timedelta(days=365)
    covenanter_role = ensure_catalog_role(ROLE_COVENANTER)
    if RoleAssignment.objects.filter(
        member=applicant,
        role=covenanter_role,
        status=RoleAssignment.Status.ACTIVE,
        start_at__lt=term_end,
        end_at__gt=now,
    ).exists():
        raise DomainError("申请人已有有效或冲突的守约者任期。")
    assignment = create_role_assignment(
        member=applicant,
        role=covenanter_role,
        granted_by=actor,
        start_at=now,
        end_at=term_end,
        source_type=RoleAssignment.SourceType.PROPOSAL,
    )
    applicant.status = Member.Status.ADMITTED
    applicant.save(update_fields=["status"])
    application.status = MemberApplication.Status.ADMITTED
    application.decided_by = actor
    application.decided_at = now
    application.metadata = {
        **application.metadata,
        "proposal_outcome": "approved",
        "admission_role_assignment_id": assignment.pk,
    }
    application.save(update_fields=["status", "decided_by", "decided_at", "metadata"])
    return {
        "application_id": application.application_id,
        "role_assignment_id": assignment.pk,
        "role_code": "covenanter",
    }


def _sync_member_application_resolution(proposal: ApprovalProposal, actor: Member) -> None:
    """将拒绝或过期结果同步到报名；通过结果等待独立授权执行。"""

    resolution = ProposalResolution.objects.get(proposal=proposal)
    if resolution.outcome == ProposalResolution.Outcome.APPROVED:
        return
    application = _application_for(proposal)
    application.status = MemberApplication.Status.REJECTED
    application.decided_by = actor
    application.decided_at = resolution.decided_at
    application.metadata = {
        **application.metadata,
        "proposal_outcome": resolution.outcome,
        "proposal_resolution_reason": resolution.reason_code,
    }
    application.save(update_fields=["status", "decided_by", "decided_at", "metadata"])


register_proposal_adapter(ProposalTypeAdapter(
    proposal_type=ApprovalProposal.ProposalType.MEMBER_APPLICATION,
    strategy_type=ApprovalProposal.StrategyType.ELECTORATE,
    source_type="member_application",
    initiation_permission="",
    resolution_permission=MEMBER_ADMISSION_RESOLUTION_PERMISSION,
    execution_permission=MEMBER_ADMISSION_EXECUTION_PERMISSION,
    executor=_execute_member_admission,
    excluded_member_id_getter=_excluded_member_id,
    resolution_callback=_sync_member_application_resolution,
))
