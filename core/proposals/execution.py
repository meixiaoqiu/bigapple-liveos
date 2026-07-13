"""Proposal execution services."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core.event_ledger import append_event
from core.event_payloads import proposal_payload
from core.models import Member, MemberApplication, Proposal, ProposalExecution, Role, RoleAssignment, SystemEvent
from core.role_assignment_services import create_role_assignment


def _parse_datetime_value(value: Any):
    if not value:
        return None
    if hasattr(value, "isoformat"):
        return value
    parsed = parse_datetime(str(value))
    if parsed is None:
        raise ValidationError(f"无效的时间值：{value}")
    return parsed


def execute_proposal(
    *,
    proposal: Proposal,
    executor_member: Member | None = None,
    executor_role_assignment: RoleAssignment | None = None,
    at_time=None,
) -> ProposalExecution:
    checked_at = at_time or timezone.now()
    proposal.refresh_from_db()
    if proposal.status == Proposal.Status.EXECUTED:
        existing = proposal.executions.filter(status=ProposalExecution.Status.SUCCEEDED).order_by("id").first()
        if existing is not None:
            return existing
    if proposal.status != Proposal.Status.PASSED:
        raise ValidationError("只有已通过的提案才能执行。")

    if proposal.proposal_type == Proposal.ProposalType.MEMBER_ADMISSION:
        action_type = ProposalExecution.ActionType.ADMIT_MEMBER_APPLICATION
    elif proposal.proposal_type == Proposal.ProposalType.ROLE_APPOINTMENT:
        action_type = ProposalExecution.ActionType.CREATE_ROLE_ASSIGNMENT
    else:
        action_type = ProposalExecution.ActionType.MANUAL

    existing = proposal.executions.filter(action_type=action_type, status=ProposalExecution.Status.SUCCEEDED).first()
    if existing is not None:
        return existing

    execution = ProposalExecution.objects.create(
        proposal=proposal,
        executor_member=executor_member,
        executor_role_assignment=executor_role_assignment,
        action_type=action_type,
        status=ProposalExecution.Status.PENDING,
        payload_json=proposal.payload_json,
    )
    try:
        if proposal.proposal_type == Proposal.ProposalType.MEMBER_ADMISSION:
            from core.application_services import admit_member_application_from_proposal

            payload = proposal.payload_json or {}
            application_id = payload.get("application_id")
            if not application_id:
                raise ValidationError("成员准入提案内容必须包含 application_id。")
            try:
                application = MemberApplication.objects.select_related("linked_member", "admission_proposal").get(
                    application_id=application_id
                )
            except ObjectDoesNotExist as exc:
                raise ValidationError(f"成员报名不存在：{application_id}") from exc
            admit_member_application_from_proposal(
                application=application,
                proposal=proposal,
                executor_member=executor_member,
                execution=execution,
                admitted_at=checked_at,
            )
            application.refresh_from_db()
            execution.result_json = {
                "application_id": application.application_id,
                "member_no": application.linked_member.member_no if application.linked_member_id else "",
                "status": application.status,
            }
        elif proposal.proposal_type == Proposal.ProposalType.ROLE_APPOINTMENT:
            payload = proposal.payload_json or {}
            target_member = Member.objects.get(pk=payload["target_member_id"])
            role = Role.objects.get(pk=payload["role_id"])
            start_at = _parse_datetime_value(payload.get("start_at")) or checked_at
            end_at = _parse_datetime_value(payload.get("end_at"))
            if end_at is None:
                raise ValidationError("角色任命提案内容必须包含结束时间。")
            assignment = create_role_assignment(
                member=target_member,
                role=role,
                granted_by=executor_member,
                start_at=start_at,
                end_at=end_at,
                source_type=RoleAssignment.SourceType.PROPOSAL,
                source_proposal=proposal,
                source_proposal_execution=execution,
            )
            execution.result_json = {
                "role_assignment_id": assignment.pk,
                "member_no": assignment.member.member_no,
                "role_id": assignment.role_id,
                "status": assignment.status,
                "source_type": assignment.source_type,
            }
        else:
            execution.result_json = {"manual": True}
        execution.status = ProposalExecution.Status.SUCCEEDED
        execution.executed_at = checked_at
        execution.save(update_fields=["status", "result_json", "executed_at", "updated_at"])
        proposal.status = Proposal.Status.EXECUTED
        proposal.executed_at = checked_at
        proposal.save(update_fields=["status", "executed_at", "updated_at"])
        append_event(
            event_type=SystemEvent.EventType.PROPOSAL_EXECUTED,
            aggregate_type="Proposal",
            aggregate_id=str(proposal.pk),
            actor_member=executor_member,
            actor_role_assignment=executor_role_assignment,
            payload_json={**proposal_payload(proposal), "execution": execution.result_json, "action_type": action_type},
            occurred_at=checked_at,
        )
    except Exception as exc:
        execution.status = ProposalExecution.Status.FAILED
        execution.error_message = str(exc)
        execution.executed_at = checked_at
        execution.save(update_fields=["status", "error_message", "executed_at", "updated_at"])
        raise
    return execution
