from __future__ import annotations

from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.event_ledger import verify_event_chain
from core.models import Dispute, SystemEvent, Task
from core.dispute_services import resolve_dispute, start_dispute_review, submit_dispute
from core.service_utils import actor_ref
from core.tasks.authoring import assign_task, close_task, create_task_draft, publish_task
from core.tasks.member_workflow import claim_task, submit_labor
from core.tasks.review import review_task
from core.tests.helpers import create_member


class BusinessEventLedgerTests(TestCase):
    """Task and dispute business actions should append to the unified hash ledger."""

    def setUp(self) -> None:
        self.operator = create_member(member_no="member-admin-0001")
        self.worker = create_member(member_no="mem-0001")
        self.operator_ref = actor_ref(self.operator)

    def assert_system_event_exists(self, *, event_type: str, aggregate_type: str, aggregate_id: str) -> None:
        self.assertTrue(
            SystemEvent.objects.filter(
                event_type=event_type,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
            ).exists()
        )

    def task_defaults(self) -> dict:
        return {
            "title": "测试任务",
            "task_type": Task.TaskType.PUBLIC_CLEANING,
            "standard_hours": Decimal("2.00"),
            "base_points": 20,
            "role_coefficient": Decimal("1.000"),
            "failure_consequence": Task.FailureConsequence.MEDIUM,
            "can_be_delayed": True,
            "requires_review": True,
            "rule_version": "ruleset-v0.1.0",
            "created_by": self.operator_ref,
        }

    def test_task_lifecycle_actions_append_system_events(self) -> None:
        task = create_task_draft(**self.task_defaults())
        self.assertEqual(task.source_type, Task.SourceType.DIRECT)
        publish_task(task=task, publisher=self.operator_ref)
        task.refresh_from_db()
        assign_task(task=task, member=self.worker, operator=self.operator_ref)
        task.refresh_from_db()
        submit_labor(task=task, member=self.worker, labor_note="已完成清洁", evidence_refs=["photo-001"])
        task.refresh_from_db()
        review_task(task=task, reviewer=self.operator_ref, accepted=False, reason="证据不足，退回重做")

        close_candidate = create_task_draft(**{**self.task_defaults(), "title": "可关闭草稿任务"})
        close_task(task=close_candidate, operator=self.operator_ref, reason="重复创建，关闭草稿")

        claim_candidate = Task.objects.create(
            task_id="task-open-claim-0001",
            title="可领取任务",
            task_type=Task.TaskType.PUBLIC_CLEANING,
            status=Task.Status.OPEN,
            standard_hours=2,
            base_points=20,
            role_coefficient=1,
            can_be_delayed=True,
            requires_review=True,
            failure_consequence=Task.FailureConsequence.MEDIUM,
            rule_version="ruleset-v0.1.0",
            created_at=timezone.now(),
        )
        claim_task(task=claim_candidate, member=self.worker)

        expected_events = {
            SystemEvent.EventType.TASK_CREATED,
            SystemEvent.EventType.TASK_PUBLISHED,
            SystemEvent.EventType.TASK_ASSIGNED,
            SystemEvent.EventType.TASK_SUBMITTED,
            SystemEvent.EventType.TASK_REVIEWED,
            SystemEvent.EventType.TASK_CLOSED,
            SystemEvent.EventType.TASK_CLAIMED,
        }
        actual_events = set(SystemEvent.objects.filter(aggregate_type="Task").values_list("event_type", flat=True))

        self.assertTrue(expected_events.issubset(actual_events))
        self.assert_system_event_exists(
            event_type=SystemEvent.EventType.TASK_REVIEWED,
            aggregate_type="Task",
            aggregate_id=task.pk,
        )
        created_event = SystemEvent.objects.get(
            event_type=SystemEvent.EventType.TASK_CREATED,
            aggregate_type="Task",
            aggregate_id=task.pk,
        )
        self.assertEqual(created_event.payload_json["public_facts"]["status"], Task.Status.DRAFT)
        self.assertTrue(verify_event_chain())

    def test_dispute_lifecycle_actions_append_system_events(self) -> None:
        task = Task.objects.create(
            task_id="task-dispute-0001",
            title="申诉关联任务",
            task_type=Task.TaskType.PUBLIC_CLEANING,
            status=Task.Status.REJECTED,
            assignee_member=self.worker,
            standard_hours=2,
            base_points=20,
            role_coefficient=1,
            can_be_delayed=True,
            requires_review=True,
            failure_consequence=Task.FailureConsequence.MEDIUM,
            rule_version="ruleset-v0.1.0",
            created_at=timezone.now(),
        )

        dispute = submit_dispute(
            claimant=self.worker,
            dispute_type=Dispute.DisputeType.TASK_REVIEW,
            facts="认为验收结论需要复核。",
            evidence_refs=["task-dispute-0001"],
            related_task=task,
        )
        start_dispute_review(dispute=dispute, handler=self.operator_ref, note="进入复核")
        dispute.refresh_from_db()
        resolve_dispute(dispute=dispute, reviewer=self.operator_ref, decision="resolved", resolution="申诉成立")

        expected_events = {
            SystemEvent.EventType.DISPUTE_CREATED,
            SystemEvent.EventType.DISPUTE_REVIEW_STARTED,
            SystemEvent.EventType.DISPUTE_RESOLVED,
        }
        actual_events = set(SystemEvent.objects.filter(aggregate_type="Dispute").values_list("event_type", flat=True))

        self.assertEqual(expected_events, actual_events)
        self.assert_system_event_exists(
            event_type=SystemEvent.EventType.DISPUTE_RESOLVED,
            aggregate_type="Dispute",
            aggregate_id=dispute.pk,
        )
        self.assertTrue(verify_event_chain())
