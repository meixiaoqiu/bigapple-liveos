from __future__ import annotations

from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.member_roles import ROLE_CONTRIBUTOR
from core.models import Event, LedgerEntry, Member, Resource, ResourceTransaction, SystemEvent, Task
from core.exceptions import DomainError
from core.resource_services import record_resource_adjustment
from core.service_utils import actor_ref
from core.tasks.member_workflow import claim_task, submit_labor
from core.tasks.review import review_task
from core.tests.helpers import create_governance_admin_member, create_member


class ServiceConcurrencyGuardTests(TestCase):
    """Guard against stale model instances overwriting newer authority state."""

    def setUp(self) -> None:
        now = timezone.now()
        self.member = create_member(
            member_no="mem-0001",
            role_name=ROLE_CONTRIBUTOR,
            status=Member.Status.ADMITTED,
            batch_id="batch-opening",
            joined_simulation_day=1,
            credit_floor=-100,
            profile={"display_name": "成员一号"},
            created_at=now,
        )
        self.other_member = create_member(
            member_no="mem-0002",
            role_name=ROLE_CONTRIBUTOR,
            status=Member.Status.ADMITTED,
            batch_id="batch-opening",
            joined_simulation_day=1,
            credit_floor=-100,
            profile={"display_name": "成员二号"},
            created_at=now,
        )
        self.reviewer = create_governance_admin_member(
            member_no="member-admin-0001",
            status=Member.Status.ACTIVE,
            batch_id="batch-opening",
            joined_simulation_day=1,
            credit_floor=-500,
            profile={"display_name": "开荒队治理成员"},
            created_at=now,
        )

    def create_task(self, *, task_id: str, status: str = Task.Status.OPEN, assignee: Member | None = None) -> Task:
        return Task.objects.create(
            task_id=task_id,
            title=f"测试任务 {task_id}",
            task_type=Task.TaskType.PUBLIC_CLEANING,
            status=status,
            standard_hours=Decimal("2.00"),
            base_points=20,
            role_coefficient=Decimal("1.000"),
            can_be_delayed=True,
            requires_review=True,
            failure_consequence=Task.FailureConsequence.MEDIUM,
            assignee_member=assignee,
            rule_version="ruleset-v0.1.0",
            created_at=timezone.now(),
            metadata={"simulation_day": 1},
        )

    def test_claim_task_reloads_current_state_before_writing(self) -> None:
        task = self.create_task(task_id="task-open-0001")
        stale_task = Task.objects.get(task_id=task.task_id)
        Task.objects.filter(task_id=task.task_id).update(
            status=Task.Status.CLAIMED,
            assignee_member=self.other_member,
        )

        with self.assertRaisesRegex(DomainError, "Only open tasks"):
            claim_task(task=stale_task, member=self.member)

        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.CLAIMED)
        self.assertEqual(task.assignee_member_id, self.other_member.pk)

    def test_submit_labor_reloads_current_assignment_before_writing(self) -> None:
        task = self.create_task(task_id="task-claimed-0001", status=Task.Status.CLAIMED, assignee=self.member)
        stale_task = Task.objects.get(task_id=task.task_id)
        Task.objects.filter(task_id=task.task_id).update(assignee_member=self.other_member)

        with self.assertRaisesRegex(DomainError, "Only the assigned member"):
            submit_labor(task=stale_task, member=self.member, labor_note="已完成。", evidence_refs=[])

        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.CLAIMED)
        self.assertEqual(task.assignee_member_id, self.other_member.pk)

    def test_review_task_reloads_current_status_before_writing(self) -> None:
        task = self.create_task(task_id="task-review-0001", status=Task.Status.PENDING_REVIEW, assignee=self.member)
        stale_task = Task.objects.get(task_id=task.task_id)
        Task.objects.filter(task_id=task.task_id).update(status=Task.Status.ACCEPTED)

        with self.assertRaisesRegex(DomainError, "Only tasks pending review"):
            review_task(task=stale_task, reviewer=actor_ref(self.reviewer), accepted=True, reason="验收通过。")

        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.ACCEPTED)
        self.assertEqual(Event.objects.count(), 0)
        self.assertEqual(LedgerEntry.objects.count(), 0)

    def test_resource_adjustment_reloads_current_stock_before_calculating(self) -> None:
        resource = Resource.objects.create(
            resource_id="res-tools",
            resource_type=Resource.ResourceType.TOOLS,
            unit=Resource.Unit.COUNT,
            current_stock=Decimal("10"),
            daily_consumption_estimate=Decimal("1"),
            replenishment_method=Resource.ReplenishmentMethod.PURCHASE,
            loss_rate=Decimal("0.02000"),
            warning_threshold=Decimal("3"),
            shortage_impact={},
            updated_at=timezone.now(),
            rule_version="ruleset-v0.1.0",
        )
        stale_resource = Resource.objects.get(resource_id=resource.resource_id)
        Resource.objects.filter(resource_id=resource.resource_id).update(current_stock=Decimal("5"))

        adjusted_resource, event = record_resource_adjustment(
            resource=stale_resource,
            delta=Decimal("3"),
            operator=actor_ref(self.reviewer),
            reason="补充工具。",
            replenishment_method=Resource.ReplenishmentMethod.DONATION,
            simulation_day=1,
        )

        self.assertEqual(adjusted_resource.current_stock, Decimal("8"))
        self.assertEqual(event.payload["old_stock"], "5.000")
        self.assertEqual(event.payload["new_stock"], "8.000")
        transaction = ResourceTransaction.objects.get(resource=resource)
        self.assertEqual(transaction.stock_before, Decimal("5.000"))
        self.assertEqual(transaction.stock_after, Decimal("8.000"))

    def test_review_task_uses_unified_event_sequence(self) -> None:
        first_task = self.create_task(task_id="task-review-0001", status=Task.Status.PENDING_REVIEW, assignee=self.member)
        second_task = self.create_task(
            task_id="task-review-0002",
            status=Task.Status.PENDING_REVIEW,
            assignee=self.other_member,
        )

        _first_reviewed_task, first_entries = review_task(
            task=first_task,
            reviewer=actor_ref(self.reviewer),
            accepted=True,
            reason="第一次验收。",
        )
        _second_reviewed_task, second_entries = review_task(
            task=second_task,
            reviewer=actor_ref(self.reviewer),
            accepted=True,
            reason="第二次验收。",
        )

        self.assertIsNotNone(first_entries[0].system_event)
        self.assertIsNotNone(second_entries[0].system_event)
        self.assertLess(first_entries[0].system_event.seq, second_entries[0].system_event.seq)
        self.assertEqual(
            list(
                SystemEvent.objects.filter(aggregate_type__in=["Task", "LedgerEntry"])
                .order_by("seq")
                .values_list("event_type", flat=True)
            ),
            [
                SystemEvent.EventType.TASK_REVIEWED,
                SystemEvent.EventType.CREDIT_EARNED,
                SystemEvent.EventType.TASK_REVIEWED,
                SystemEvent.EventType.CREDIT_EARNED,
            ],
        )
