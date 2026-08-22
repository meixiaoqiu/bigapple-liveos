from __future__ import annotations

import json
from io import StringIO
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase
from django.utils import timezone

from core.credit_services import ensure_system_accounts, issue_credits_to_pool, lock_task_credit_budget
from core.member_roles import ROLE_COVENANTER
from core.openfga_client import OpenFGARequestError
from core.models import CapacityAssessment, Event, EventFeedback, LedgerEntry, Member, Resource, Task
from core.tests.helpers import create_administrator_member, create_member, login_as_member


def actor(actor_id: str = "member-admin-0001") -> dict[str, str]:
    return {
        "actor_id": actor_id,
        "actor_type": "human_member",
        "display_name": "开荒队管理员",
    }


class ApiWorkflowTests(TestCase):
    """覆盖成员通过 Live OS API 完成任务的第一条闭环。"""

    api_base = "/api/v0.1"

    def setUp(self) -> None:
        self.client = Client()
        now = timezone.now()
        self.member = create_member(
            member_no="mem-0001",
            role_name=ROLE_COVENANTER,
            status=Member.Status.ADMITTED,
            batch_id="batch-opening",
            joined_simulation_day=1,
            credit_floor=-300,
            profile={"satisfaction": 64, "fatigue": 18},
            created_at=now,
        )
        self.reviewer = create_administrator_member(
            member_no="member-admin-0001",
            status=Member.Status.ACTIVE,
            batch_id="batch-opening",
            joined_simulation_day=1,
            credit_floor=-500,
            profile={"public_spirit": 90},
            created_at=now,
        )
        self.task = Task.objects.create(
            task_id="task-0001",
            title="准备今日午餐",
            task_type=Task.TaskType.COOKING,
            status=Task.Status.OPEN,
            standard_minutes=210,
            base_points=30,
            role_coefficient=Decimal("1.200"),
            physical_load=Decimal("45"),
            dirty_level=Decimal("30"),
            psychological_load=Decimal("35"),
            urgency=Decimal("70"),
            can_be_delayed=False,
            requires_review=True,
            failure_consequence=Task.FailureConsequence.HIGH,
            rule_version="ruleset-v0.1.0",
            created_at=now,
            due_at=now + timedelta(hours=4),
            metadata={"simulation_day": 1},
        )
        # Step 2 budget: issue + lock so review_task can reward
        ensure_system_accounts()
        issue_credits_to_pool(
            amount=200, reason="API workflow test budget",
            initiated_by=self.reviewer, reviewed_by=self.reviewer,
        )
        lock_task_credit_budget(
            task=self.task, amount=200,
            reason="API workflow test lock",
        )

        CapacityAssessment.objects.create(
            assessment_id="capacity-0001",
            simulation_day=7,
            current_covenanters=100,
            current_contributors=900,
            maximum_admissible_members=130,
            recommended_new_members=20,
            bottlenecks=["canteen"],
            risk_indicators={
                "beds_available": 42,
                "canteen_load": 82,
                "task_gap": 18,
                "average_satisfaction": 61,
                "average_fatigue": 67,
                "active_feedbacks": 0,
                "exit_risk_members": 9,
            },
            reasons=["食堂承载接近风险阈值。"],
            rule_version="ruleset-v0.1.0",
            created_at=now,
            metadata={"operator_note": "internal capacity note"},
        )

    def post_json(self, path: str, payload: dict) -> tuple[int, dict]:
        response = self.client.post(
            path,
            data=json.dumps(payload),
            content_type="application/json",
        )
        return response.status_code, response.json()

    def api(self, path: str) -> str:
        return f"{self.api_base}{path}"

    def test_member_can_complete_task_through_api(self) -> None:
        response = self.client.get(self.api("/tasks"), {"status": Task.Status.OPEN})
        self.assertEqual(response.status_code, 200)
        public_task = response.json()[0]
        self.assertEqual(public_task["task_id"], self.task.task_id)
        self.assertNotIn("metadata", public_task)
        self.assertNotIn("assignee_member_no", public_task)

        login_as_member(self.client, self.member)
        status, payload = self.post_json(
            self.api(f"/tasks/{self.task.task_id}/claim"),
            {"member_no": self.member.member_no},
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], Task.Status.CLAIMED)
        self.assertEqual(payload["assignee_member_no"], self.member.member_no)

        status, payload = self.post_json(
            self.api(f"/tasks/{self.task.task_id}/submit-labor"),
            {
                "member_no": self.member.member_no,
                "labor_note": "已完成午餐准备。",
                "evidence_refs": ["photo-0001"],
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], Task.Status.PENDING_REVIEW)

        login_as_member(self.client, self.reviewer)
        status, payload = self.post_json(
            self.api(f"/tasks/{self.task.task_id}/review"),
            {
                "reviewer": {"actor_id": "forged-reviewer", "actor_type": "human_member"},
                "accepted": True,
                "reason": "午餐准备验收通过。",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["task"]["status"], Task.Status.ACCEPTED)
        self.assertEqual(len(payload["ledger_entries"]), 1)
        self.assertEqual(payload["ledger_entries"][0]["amount"], 36)
        self.assertEqual(payload["ledger_entries"][0]["reviewer"]["actor_id"], self.reviewer.member_no)

        self.assertEqual(LedgerEntry.objects.count(), 1)
        self.assertEqual(Event.objects.count(), 1)

        login_as_member(self.client, self.member)
        ledger_response = self.client.get(
            self.api("/ledger-entries"),
            {"member_no": self.member.member_no},
        )
        self.assertEqual(ledger_response.status_code, 200)
        self.assertEqual(ledger_response.json()[0]["related_task_id"], self.task.task_id)

        event_response = self.client.get(self.api("/events"), {"simulation_day": 1})
        self.assertEqual(event_response.status_code, 200)
        public_event = event_response.json()[0]
        self.assertEqual(public_event["event_type"], Event.EventType.TASK)
        self.assertNotIn("involved_member_ids", public_event)
        self.assertNotIn("payload", public_event)

        summary_response = self.client.get(self.api("/observer/summary"))
        self.assertEqual(summary_response.status_code, 200)
        summary = summary_response.json()
        self.assertEqual(summary["simulation_day"], 7)
        self.assertEqual(summary["covenanters"], 1)
        self.assertEqual(len(summary["events"]), 1)
        self.assertNotIn("payload", summary["events"][0])

    def test_root_api_routes_use_same_views(self) -> None:
        response = self.client.get(self.api("/tasks"), {"status": Task.Status.OPEN})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["task_id"], self.task.task_id)

        summary_response = self.client.get(self.api("/observer/summary"))
        self.assertEqual(summary_response.status_code, 200)
        self.assertEqual(summary_response.json()["simulation_day"], 7)

    def test_world_prefixed_api_route_is_removed(self) -> None:
        response = self.client.get("/world/realworld/api/v0.1/tasks", {"status": Task.Status.OPEN})
        self.assertEqual(response.status_code, 404)

    def test_completed_task_cannot_be_reviewed_twice(self) -> None:
        login_as_member(self.client, self.member)
        self.post_json(
            self.api(f"/tasks/{self.task.task_id}/claim"),
            {"member_no": self.member.member_no},
        )
        self.post_json(
            self.api(f"/tasks/{self.task.task_id}/submit-labor"),
            {"member_no": self.member.member_no, "labor_note": "已完成午餐准备。"},
        )
        login_as_member(self.client, self.reviewer)
        self.post_json(
            self.api(f"/tasks/{self.task.task_id}/review"),
            {"reviewer": actor(), "accepted": True, "reason": "验收通过。"},
        )

        status, payload = self.post_json(
            self.api(f"/tasks/{self.task.task_id}/review"),
            {"reviewer": actor(), "accepted": True, "reason": "重复验收。"},
        )
        self.assertEqual(status, 409)
        self.assertEqual(payload["code"], "state_conflict")
        self.assertEqual(LedgerEntry.objects.count(), 1)
        self.assertEqual(Event.objects.count(), 1)

    def test_write_api_requires_authenticated_principal(self) -> None:
        status, payload = self.post_json(
            self.api(f"/tasks/{self.task.task_id}/claim"),
            {"member_no": self.member.member_no},
        )
        self.assertEqual(status, 401)
        self.assertEqual(payload["code"], "authentication_required")

    def test_basic_member_cannot_claim_task_through_api(self) -> None:
        basic = create_member("api-basic-claim")
        login_as_member(self.client, basic)

        status, payload = self.post_json(
            self.api(f"/tasks/{self.task.task_id}/claim"),
            {"member_no": basic.member_no},
        )

        self.assertEqual(status, 403)
        self.assertEqual(payload["code"], "permission_denied")
        self.task.refresh_from_db()
        self.assertIsNone(self.task.assignee_member_id)

    def test_basic_member_cannot_read_own_ledger_through_api(self) -> None:
        basic = create_member("api-basic-ledger")
        login_as_member(self.client, basic)

        response = self.client.get(
            self.api("/ledger-entries"),
            {"member_no": basic.member_no},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "permission_denied")

    def test_full_workspace_api_fails_closed_when_openfga_unavailable(self) -> None:
        login_as_member(self.client, self.member)

        with self.settings(BIG_APPLE_AUTHORIZATION_BACKEND="openfga", OPENFGA_SIM_STORE_ID="store-test"):
            with patch("core.authorization_services.OpenFGAClient") as client_class:
                client_class.return_value.check.side_effect = OpenFGARequestError("OpenFGA check failed")
                status, payload = self.post_json(
                    self.api(f"/tasks/{self.task.task_id}/claim"),
                    {"member_no": self.member.member_no},
                )

        self.assertEqual(status, 403)
        self.assertEqual(payload["code"], "permission_denied")
        self.task.refresh_from_db()
        self.assertIsNone(self.task.assignee_member_id)

    def test_public_task_list_omits_member_and_execution_metadata(self) -> None:
        now = timezone.now()
        self.task.assignee_member = self.member
        self.task.status = Task.Status.PENDING_REVIEW
        self.task.submitted_at = now
        self.task.reviewed_at = now
        self.task.metadata = {"labor_note": "private note", "evidence_refs": ["photo-private"]}
        self.task.save(update_fields=["assignee_member", "status", "submitted_at", "reviewed_at", "metadata"])

        response = self.client.get(self.api("/tasks"), {"status": Task.Status.PENDING_REVIEW})

        self.assertEqual(response.status_code, 200)
        public_task = response.json()[0]
        self.assertEqual(public_task["task_id"], self.task.task_id)
        self.assertEqual(public_task["status"], Task.Status.PENDING_REVIEW)
        self.assertNotIn("assignee_member_no", public_task)
        self.assertNotIn("submitted_at", public_task)
        self.assertNotIn("reviewed_at", public_task)
        self.assertNotIn("metadata", public_task)

    def test_public_resources_omit_raw_metadata(self) -> None:
        now = timezone.now()
        Resource.objects.create(
            resource_id="res-public-0001",
            resource_type=Resource.ResourceType.MEDICINE,
            unit=Resource.Unit.COUNT,
            current_stock=Decimal("18"),
            daily_consumption_estimate=Decimal("6"),
            replenishment_method=Resource.ReplenishmentMethod.PURCHASE,
            loss_rate=Decimal("0.01000"),
            warning_threshold=Decimal("30"),
            shortage_impact={"health_risk_delta": 24},
            updated_at=now,
            rule_version="ruleset-v0.1.0",
            metadata={"last_operator_member_no": self.reviewer.member_no, "private_note": "internal"},
        )

        response = self.client.get(self.api("/resources"))

        self.assertEqual(response.status_code, 200)
        public_resource = response.json()[0]
        self.assertEqual(public_resource["resource_id"], "res-public-0001")
        self.assertEqual(public_resource["current_stock"], 18)
        self.assertNotIn("metadata", public_resource)

    def test_public_capacity_assessment_omits_raw_metadata(self) -> None:
        response = self.client.get(self.api("/capacity-assessments/latest"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["assessment_id"], "capacity-0001")
        self.assertNotIn("metadata", payload)

    def test_write_api_does_not_expose_member_no_existence_to_other_members(self) -> None:
        login_as_member(self.client, self.member)

        existing_status, existing_payload = self.post_json(
            self.api(f"/tasks/{self.task.task_id}/claim"),
            {"member_no": self.reviewer.member_no},
        )
        missing_status, missing_payload = self.post_json(
            self.api(f"/tasks/{self.task.task_id}/claim"),
            {"member_no": "member-does-not-exist"},
        )
        self.assertEqual(existing_status, 403)
        self.assertEqual(missing_status, 403)
        self.assertEqual(existing_payload["code"], "permission_denied")
        self.assertEqual(missing_payload["code"], "permission_denied")

    def test_public_human_operator_event_summary_uses_title_only(self) -> None:
        now = timezone.now()
        Event.objects.create(
            event_id="event-resource-public-0001",
            event_type=Event.EventType.RESOURCE,
            simulation_day=1,
            severity=Event.Severity.INFO,
            title="Resource stock adjusted",
            summary="Resource stock adjusted because of an internal operator note.",
            involved_member_ids=[self.reviewer.member_no],
            occurred_at=now,
            generated_by=Event.GeneratedBy.HUMAN_OPERATOR,
            visibility=Event.Visibility.PUBLIC,
            payload={"reason": "internal operator note", "operator": {"actor_id": self.reviewer.member_no}},
        )

        response = self.client.get(self.api("/events"), {"simulation_day": 1})

        self.assertEqual(response.status_code, 200)
        public_event = response.json()[0]
        self.assertEqual(public_event["summary"], "Resource stock adjusted")
        self.assertNotIn("internal operator note", public_event["summary"])
        self.assertNotIn("involved_member_ids", public_event)
        self.assertNotIn("payload", public_event)

    def test_create_event_feedback_api_server_manages_identity_and_status(self) -> None:
        login_as_member(self.client, self.member)
        target = Event.objects.create(event_id="event-feedback-api", event_type=Event.EventType.TASK, simulation_day=1, severity=Event.Severity.INFO, title="可反馈事件", summary="可反馈事件", occurred_at=timezone.now(), generated_by=Event.GeneratedBy.LIVE_OS, visibility=Event.Visibility.PUBLIC)

        status, payload = self.post_json(
            self.api("/event-feedbacks"),
            {
                "feedback_id": "feedback-forged", "related_event_id": target.event_id,
                "feedback_type": EventFeedback.FeedbackType.REVIEW,
                "status": EventFeedback.Status.CLOSED, "statement": "伪造状态测试。",
                "submitted_at": timezone.now().isoformat(),
            },
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["code"], "invalid_request")

        status, payload = self.post_json(
            self.api("/event-feedbacks"),
            {
                "related_event_id": target.event_id,
                "feedback_type": EventFeedback.FeedbackType.REVIEW,
                "statement": "午餐任务验收标准需要复核。",
                "evidence_refs": ["event-0001"],
            },
        )
        self.assertEqual(status, 201)
        self.assertNotEqual(payload["feedback_id"], "feedback-forged")
        self.assertEqual(payload["status"], EventFeedback.Status.SUBMITTED)
        self.assertEqual(payload["submitted_by_member_no"], self.member.member_no)

    def test_basic_member_can_create_event_feedback_through_api(self) -> None:
        basic = create_member("api-basic-feedback")
        login_as_member(self.client, basic)
        target = Event.objects.create(event_id="event-basic-feedback", event_type=Event.EventType.SYSTEM, simulation_day=1, severity=Event.Severity.INFO, title="公开事件", summary="公开事件", occurred_at=timezone.now(), generated_by=Event.GeneratedBy.LIVE_OS, visibility=Event.Visibility.PUBLIC)

        status, payload = self.post_json(
            self.api("/event-feedbacks"),
            {
                "related_event_id": target.event_id,
                "feedback_type": EventFeedback.FeedbackType.OPINION,
                "statement": "基础成员可以反馈公开事件。",
            },
        )

        self.assertEqual(status, 201)

    def test_event_feedback_api_rejects_malformed_payload_shapes(self) -> None:
        login_as_member(self.client, self.member)
        target = Event.objects.create(
            event_id="event-feedback-invalid-json", event_type=Event.EventType.SYSTEM,
            simulation_day=1, severity=Event.Severity.INFO, title="严格校验", summary="严格校验",
            occurred_at=timezone.now(), generated_by=Event.GeneratedBy.LIVE_OS,
            visibility=Event.Visibility.PUBLIC,
        )
        base = {
            "related_event_id": target.event_id,
            "feedback_type": EventFeedback.FeedbackType.REVIEW,
            "statement": "校验输入。",
        }
        invalid_payloads = [
            {**base, "unknown": True},
            {**base, "evidence_refs": "event-1"},
            {**base, "evidence_refs": [""]},
            {**base, "metadata": []},
            {**base, "statement": ["错误类型"]},
        ]

        for payload_to_send in invalid_payloads:
            with self.subTest(payload=payload_to_send):
                status, payload = self.post_json(self.api("/event-feedbacks"), payload_to_send)
                self.assertEqual(status, 400)
                self.assertEqual(payload["code"], "invalid_request")

        response = self.client.post(
            self.api("/event-feedbacks"),
            data='["not-an-object"]',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invalid_request")

    def test_events_api_filters_internal_events_by_default(self) -> None:
        now = timezone.now()
        Event.objects.create(
            event_id="event-public-0001",
            event_type=Event.EventType.TASK,
            simulation_day=1,
            severity=Event.Severity.INFO,
            title="公开任务事件",
            summary="公开事件。",
            involved_member_ids=[self.member.member_no],
            related_task=self.task,
            related_feedback_id="feedback-private-0001",
            occurred_at=now,
            generated_by=Event.GeneratedBy.LIVE_OS,
            visibility=Event.Visibility.PUBLIC,
            payload={"private_note": "should not be public"},
        )
        Event.objects.create(
            event_id="event-internal-0001",
            event_type=Event.EventType.EVENT_FEEDBACK,
            simulation_day=1,
            severity=Event.Severity.WARNING,
            title="内部反馈事件",
            summary="内部事件。",
            involved_member_ids=[self.member.member_no],
            occurred_at=now,
            generated_by=Event.GeneratedBy.HUMAN_OPERATOR,
            visibility=Event.Visibility.INTERNAL,
            payload={"private_note": "不应公开"},
        )

        public_response = self.client.get(self.api("/events"), {"simulation_day": 1})
        self.assertEqual(public_response.status_code, 200)
        self.assertEqual(
            {event["event_id"] for event in public_response.json()},
            {"event-public-0001"},
        )
        public_event = public_response.json()[0]
        self.assertEqual(public_event["related_task_id"], self.task.task_id)
        self.assertNotIn("involved_member_ids", public_event)
        self.assertNotIn("related_feedback_id", public_event)
        self.assertNotIn("payload", public_event)

        internal_response = self.client.get(
            self.api("/events"),
            {"simulation_day": 1, "visibility": Event.Visibility.INTERNAL},
        )
        self.assertEqual(internal_response.status_code, 401)

        login_as_member(self.client, self.reviewer)
        internal_response = self.client.get(
            self.api("/events"),
            {"simulation_day": 1, "visibility": Event.Visibility.INTERNAL},
        )
        self.assertEqual(internal_response.status_code, 200)
        internal_event = internal_response.json()[0]
        self.assertEqual(internal_event["event_id"], "event-internal-0001")
        self.assertEqual(internal_event["involved_member_ids"], [self.member.member_no])
        self.assertEqual(internal_event["payload"], {"private_note": "不应公开"})

    def test_workspace_summary_is_member_centered(self) -> None:
        now = timezone.now()
        self.task.assignee_member = self.member
        self.task.status = Task.Status.CLAIMED
        self.task.save(update_fields=["assignee_member", "status"])
        Task.objects.create(
            task_id="task-0002",
            title="整理临时仓库货架",
            task_type=Task.TaskType.WAREHOUSE,
            status=Task.Status.OPEN,
            standard_minutes=150,
            base_points=24,
            role_coefficient=Decimal("1.100"),
            can_be_delayed=True,
            requires_review=True,
            failure_consequence=Task.FailureConsequence.MEDIUM,
            rule_version="ruleset-v0.1.0",
            created_at=now,
            due_at=now + timedelta(hours=8),
        )
        history_task = Task.objects.create(
            task_id="task-0003",
            title="清理公共厨房",
            task_type=Task.TaskType.PUBLIC_CLEANING,
            status=Task.Status.ACCEPTED,
            standard_minutes=120,
            base_points=20,
            role_coefficient=Decimal("1.000"),
            can_be_delayed=False,
            requires_review=True,
            failure_consequence=Task.FailureConsequence.MEDIUM,
            assignee_member=self.member,
            rule_version="ruleset-v0.1.0",
            created_at=now,
            submitted_at=now,
            reviewed_at=now,
            metadata={"labor_note": "已完成厨房台面清理。"},
        )
        Resource.objects.create(
            resource_id="res-medicine",
            resource_type=Resource.ResourceType.MEDICINE,
            unit=Resource.Unit.COUNT,
            current_stock=Decimal("18"),
            daily_consumption_estimate=Decimal("6"),
            replenishment_method=Resource.ReplenishmentMethod.PURCHASE,
            loss_rate=Decimal("0.01000"),
            warning_threshold=Decimal("30"),
            shortage_impact={"health_risk_delta": 24},
            updated_at=now,
            rule_version="ruleset-v0.1.0",
        )
        event = Event.objects.create(
            event_id="event-0001",
            event_type=Event.EventType.TASK,
            simulation_day=1,
            severity=Event.Severity.INFO,
            title="任务已领取",
            summary="成员已领取任务。",
            involved_member_ids=[self.member.member_no],
            related_task=self.task,
            occurred_at=now,
            generated_by=Event.GeneratedBy.LIVE_OS,
            visibility=Event.Visibility.PUBLIC,
            payload={},
        )
        LedgerEntry.objects.create(
            ledger_entry_id="ledger-0001",
            member=self.member,
            amount=10,
            entry_type=LedgerEntry.EntryType.CONTRIBUTION,
            reason="历史贡献积分",
            related_task=self.task,
            related_event_id=event.event_id,
            rule_version="ruleset-v0.1.0",
            created_at=now,
            created_by=actor(),
            status=LedgerEntry.Status.POSTED,
        )
        # Create matching CreditTransaction for the member credit balance query
        from core.credit_services import (
            ensure_system_accounts, get_or_create_member_credit_account,
            issue_credits_to_pool, lock_task_credit_budget,
            post_task_reward_credit_transaction,
        )
        from core.models import LedgerEntry as _LE
        ensure_system_accounts()
        get_or_create_member_credit_account(self.member)
        issue_credits_to_pool(
            amount=100, reason="test", initiated_by=self.reviewer, reviewed_by=self.reviewer,
        )
        lock_task_credit_budget(task=self.task, amount=20, reason="workspace test")
        le = _LE.objects.get(ledger_entry_id="ledger-0001")
        post_task_reward_credit_transaction(
            task=self.task, member=self.member, amount=10, ledger_entry=le,
            reviewed_by=self.reviewer,
        )
        EventFeedback.objects.create(
            feedback_id="feedback-0001", related_event=event,
            feedback_type=EventFeedback.FeedbackType.REVIEW,
            status=EventFeedback.Status.VERIFYING,
            submitted_by=self.member,
            statement="成员申请复核任务验收标准。",
            evidence_refs=[event.event_id],
            submitted_at=now,
        )

        login_as_member(self.client, self.member)
        response = self.client.get(self.api(f"/members/{self.member.member_no}/workspace"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload["simulation_day"], 7)
        self.assertEqual(payload["member"]["member_no"], self.member.member_no)
        self.assertEqual(payload["credit_balance"], 10)
        self.assertEqual(payload["available_credit_balance"], 10)
        self.assertEqual(payload["lifetime_contribution"], 10)
        self.assertNotIn("available_tasks", payload)
        self.assertNotIn("active_tasks", payload)
        self.assertNotIn("task_history", payload)
        self.assertEqual(payload["recent_ledger_entries"][0]["ledger_entry_id"], "ledger-0001")
        self.assertNotIn("recent_events", payload)
        self.assertEqual(payload["open_feedbacks"][0]["feedback_id"], "feedback-0001")
        self.assertEqual(payload["feedback_history"][0]["feedback_id"], "feedback-0001")
        self.assertNotIn("resource_warnings", payload)
        self.assertEqual(payload["task_counts"][Task.Status.OPEN], 1)
        self.assertEqual(payload["task_counts"][Task.Status.CLAIMED], 1)
        self.assertEqual(payload["task_counts"][Task.Status.ACCEPTED], 1)
        self.assertNotIn("next_actions", payload)

    def test_basic_member_cannot_read_full_workspace_summary(self) -> None:
        basic = create_member("api-basic-summary")
        login_as_member(self.client, basic)

        response = self.client.get(self.api(f"/members/{basic.member_no}/workspace"))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "permission_denied")


class CreditTransferApiTests(TestCase):
    """POST /api/v0.1/members/<no>/credit-transfers"""

    api_base = "/api/v0.1"

    def setUp(self):
        from core.credit_services import ensure_system_accounts, get_or_create_member_credit_account
        ensure_system_accounts()
        self.member_a = create_member("transfer-api-a", role_name=ROLE_COVENANTER)
        self.member_b = create_member("transfer-api-b", role_name=ROLE_COVENANTER)
        get_or_create_member_credit_account(self.member_a)
        get_or_create_member_credit_account(self.member_b)
        # Give A some credits
        from core.credit_services import post_credit_transaction
        from core.models import CreditTransaction
        a_acct = get_or_create_member_credit_account(self.member_a)
        post_credit_transaction(
            transaction_type=CreditTransaction.Type.ISSUANCE,
            amount=200, target_account=a_acct,
        )

    def post_json(self, path: str, payload: dict) -> tuple[int, dict]:
        response = self.client.post(
            path, data=json.dumps(payload), content_type="application/json",
        )
        return response.status_code, response.json()

    def api(self, path: str) -> str:
        return f"{self.api_base}{path}"

    def test_transfer_succeeds(self):
        login_as_member(self.client, self.member_a)
        resp = self.client.post(
            self.api(f"/members/{self.member_a.member_no}/credit-transfers"),
            {"to_member_no": self.member_b.member_no, "amount": 50, "reason": "test"},
            content_type="application/json",
        )
        self.assertIn(resp.status_code, [200, 201])
        data = resp.json()
        self.assertEqual(data["amount"], 50)
        self.assertEqual(data["from_member_no"], self.member_a.member_no)
        self.assertEqual(data["to_member_no"], self.member_b.member_no)

    def test_cannot_transfer_as_other_member(self):
        login_as_member(self.client, self.member_b)
        resp = self.client.post(
            self.api(f"/members/{self.member_a.member_no}/credit-transfers"),
            {"to_member_no": self.member_b.member_no, "amount": 50},
            content_type="application/json",
        )
        self.assertNotEqual(resp.status_code, 201)

    def test_balance_zero_blocks_transfer(self):
        from core.credit_services import member_credit_balance
        self.assertEqual(member_credit_balance(self.member_b), 0)
        login_as_member(self.client, self.member_b)
        resp = self.client.post(
            self.api(f"/members/{self.member_b.member_no}/credit-transfers"),
            {"to_member_no": self.member_a.member_no, "amount": 10},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_insufficient_balance_blocks_transfer(self):
        login_as_member(self.client, self.member_a)
        resp = self.client.post(
            self.api(f"/members/{self.member_a.member_no}/credit-transfers"),
            {"to_member_no": self.member_b.member_no, "amount": 9999},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_lifetime_not_changed_by_transfer(self):
        from core.credit_services import member_lifetime_contribution
        login_as_member(self.client, self.member_a)
        self.client.post(
            self.api(f"/members/{self.member_a.member_no}/credit-transfers"),
            {"to_member_no": self.member_b.member_no, "amount": 30},
            content_type="application/json",
        )
        self.assertEqual(member_lifetime_contribution(self.member_a), 0)
        self.assertEqual(member_lifetime_contribution(self.member_b), 0)

    def test_reason_can_be_empty(self):
        login_as_member(self.client, self.member_a)
        resp = self.client.post(
            self.api(f"/members/{self.member_a.member_no}/credit-transfers"),
            {"to_member_no": self.member_b.member_no, "amount": 10},
            content_type="application/json",
        )
        self.assertIn(resp.status_code, [200, 201])

    def test_idempotency_key_duplicate_returns_same_txn(self):
        login_as_member(self.client, self.member_a)
        body = {"to_member_no": self.member_b.member_no, "amount": 15, "idempotency_key": "api-idem-1"}
        r1 = self.client.post(
            self.api(f"/members/{self.member_a.member_no}/credit-transfers"),
            body, content_type="application/json",
        )
        r2 = self.client.post(
            self.api(f"/members/{self.member_a.member_no}/credit-transfers"),
            body, content_type="application/json",
        )
        self.assertEqual(r1.json()["transaction_id"], r2.json()["transaction_id"])

    def test_idempotency_key_different_amount_errors(self):
        login_as_member(self.client, self.member_a)
        key = "api-diff-amount"
        self.client.post(
            self.api(f"/members/{self.member_a.member_no}/credit-transfers"),
            {"to_member_no": self.member_b.member_no, "amount": 10, "idempotency_key": key},
            content_type="application/json",
        )
        resp = self.client.post(
            self.api(f"/members/{self.member_a.member_no}/credit-transfers"),
            {"to_member_no": self.member_b.member_no, "amount": 20, "idempotency_key": key},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_governance_cannot_transfer_as_other_member(self):
        """管理员不能通过成员转账 API 代别人转出。"""
        from core.tests.helpers import create_administrator_member
        gov = create_administrator_member("administrator-transfer-hack")
        login_as_member(self.client, gov)
        bal_before_a = self._balance(self.member_a)
        bal_before_b = self._balance(self.member_b)
        resp = self.client.post(
            self.api(f"/members/{self.member_a.member_no}/credit-transfers"),
            {"to_member_no": self.member_b.member_no, "amount": 10},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self._balance(self.member_a), bal_before_a)
        self.assertEqual(self._balance(self.member_b), bal_before_b)

    def _balance(self, member):
        from core.credit_services import member_credit_balance
        return member_credit_balance(member)

    def test_basic_member_cannot_transfer_through_api(self):
        from core.credit_services import get_or_create_member_credit_account, post_credit_transaction
        from core.models import CreditTransaction

        basic = create_member("transfer-api-basic")
        account = get_or_create_member_credit_account(basic)
        post_credit_transaction(
            transaction_type=CreditTransaction.Type.ISSUANCE,
            amount=50,
            target_account=account,
        )
        login_as_member(self.client, basic)

        resp = self.client.post(
            self.api(f"/members/{basic.member_no}/credit-transfers"),
            {"to_member_no": self.member_b.member_no, "amount": 10},
            content_type="application/json",
        )

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["code"], "permission_denied")

    def test_to_member_no_required(self):
        login_as_member(self.client, self.member_a)
        resp = self.client.post(
            self.api(f"/members/{self.member_a.member_no}/credit-transfers"),
            {"amount": 10},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_body_not_object_returns_400(self):
        login_as_member(self.client, self.member_a)
        resp = self.client.post(
            self.api(f"/members/{self.member_a.member_no}/credit-transfers"),
            data=json.dumps([1, 2, 3]),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_to_member_no_null_returns_400(self):
        login_as_member(self.client, self.member_a)
        resp = self.client.post(
            self.api(f"/members/{self.member_a.member_no}/credit-transfers"),
            {"to_member_no": None, "amount": 10},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_amount_float_returns_400(self):
        login_as_member(self.client, self.member_a)
        resp = self.client.post(
            self.api(f"/members/{self.member_a.member_no}/credit-transfers"),
            {"to_member_no": self.member_b.member_no, "amount": 1.5},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_amount_bool_returns_400(self):
        login_as_member(self.client, self.member_a)
        for val in (True, False):
            resp = self.client.post(
                self.api(f"/members/{self.member_a.member_no}/credit-transfers"),
                {"to_member_no": self.member_b.member_no, "amount": val},
                content_type="application/json",
            )
            self.assertEqual(resp.status_code, 400, f"amount={val} should be rejected")

    def test_idempotency_key_int_returns_400(self):
        login_as_member(self.client, self.member_a)
        resp = self.client.post(
            self.api(f"/members/{self.member_a.member_no}/credit-transfers"),
            {"to_member_no": self.member_b.member_no, "amount": 10, "idempotency_key": 123},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)


class RedemptionOrderApiTests(TestCase):
    api_base = "/api/v0.1"

    def setUp(self):
        from core.credit_services import ensure_system_accounts, get_or_create_member_credit_account
        ensure_system_accounts()
        self.member = create_member("ro-api-member", role_name=ROLE_COVENANTER)
        self.governor = create_administrator_member("administrator-ro-api")
        get_or_create_member_credit_account(self.member)
        # Give member enough credits
        from core.models import CreditTransaction
        acct = get_or_create_member_credit_account(self.member)
        from core.credit_services import post_credit_transaction
        post_credit_transaction(
            transaction_type=CreditTransaction.Type.ISSUANCE,
            amount=200, target_account=acct,
        )

    def api(self, path):
        return f"{self.api_base}{path}"

    def test_create_order_freezes_credits(self):
        from core.credit_services import credit_balance
        from core.models import CreditAccount
        login_as_member(self.client, self.member)
        frozen = CreditAccount.objects.get(account_type=CreditAccount.Type.FROZEN)
        bal_before = credit_balance(frozen)
        resp = self.client.post(
            self.api(f"/members/{self.member.member_no}/redemption-orders"),
            {"credit_amount": 30, "item_type": "meal", "title": "lunch"},
            content_type="application/json",
        )
        self.assertIn(resp.status_code, [200, 201])
        data = resp.json()
        self.assertEqual(data["status"], "pending")
        self.assertEqual(data["credit_amount"], 30)
        self.assertEqual(credit_balance(frozen), bal_before + 30)

    def test_create_order_balance_zero_blocks(self):
        zero_member = create_member("ro-api-zero", role_name=ROLE_COVENANTER)
        from core.credit_services import get_or_create_member_credit_account
        get_or_create_member_credit_account(zero_member)
        login_as_member(self.client, zero_member)
        resp = self.client.post(
            self.api(f"/members/{zero_member.member_no}/redemption-orders"),
            {"credit_amount": 10, "item_type": "meal", "title": "x"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_basic_member_cannot_create_order_through_api(self):
        basic = create_member("ro-api-basic")
        login_as_member(self.client, basic)
        resp = self.client.post(
            self.api(f"/members/{basic.member_no}/redemption-orders"),
            {"credit_amount": 10, "item_type": "meal", "title": "x"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["code"], "permission_denied")

    def test_create_idempotent(self):
        login_as_member(self.client, self.member)
        body = {"credit_amount": 20, "item_type": "meal", "title": "test", "idempotency_key": "ro-api-idem-1"}
        r1 = self.client.post(
            self.api(f"/members/{self.member.member_no}/redemption-orders"),
            body, content_type="application/json",
        )
        r2 = self.client.post(
            self.api(f"/members/{self.member.member_no}/redemption-orders"),
            body, content_type="application/json",
        )
        self.assertEqual(r1.json()["order_id"], r2.json()["order_id"])

    def test_create_different_item_type_errors(self):
        login_as_member(self.client, self.member)
        key = "ro-api-diff-type"
        self.client.post(
            self.api(f"/members/{self.member.member_no}/redemption-orders"),
            {"credit_amount": 10, "item_type": "meal", "title": "x", "idempotency_key": key},
            content_type="application/json",
        )
        resp = self.client.post(
            self.api(f"/members/{self.member.member_no}/redemption-orders"),
            {"credit_amount": 10, "item_type": "goods", "title": "x", "idempotency_key": key},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_cannot_create_as_other_member(self):
        other = create_member("ro-api-other")
        login_as_member(self.client, other)
        resp = self.client.post(
            self.api(f"/members/{self.member.member_no}/redemption-orders"),
            {"credit_amount": 10, "item_type": "meal", "title": "x"},
            content_type="application/json",
        )
        self.assertNotEqual(resp.status_code, 201)

    def test_cancel_unfreezes_credits(self):
        from core.credit_services import credit_balance
        from core.models import CreditAccount
        login_as_member(self.client, self.member)
        r = self.client.post(
            self.api(f"/members/{self.member.member_no}/redemption-orders"),
            {"credit_amount": 30, "item_type": "meal", "title": "cancel test"},
            content_type="application/json",
        )
        order_id = r.json()["order_id"]
        frozen_acct = CreditAccount.objects.get(account_type=CreditAccount.Type.FROZEN)
        froz_before = credit_balance(frozen_acct)
        cancel_resp = self.client.post(
            self.api(f"/redemption-orders/{order_id}/cancel"),
            {"reason": "changed mind"}, content_type="application/json",
        )
        self.assertIn(cancel_resp.status_code, [200, 201])
        self.assertEqual(cancel_resp.json()["status"], "cancelled")
        self.assertEqual(credit_balance(frozen_acct), froz_before - 30)

    def test_cannot_cancel_fulfilled(self):
        from core.credit_services import fulfill_redemption_order
        from core.models import RedemptionOrder
        login_as_member(self.client, self.member)
        r = self.client.post(
            self.api(f"/members/{self.member.member_no}/redemption-orders"),
            {"credit_amount": 10, "item_type": "meal", "title": "x"},
            content_type="application/json",
        )
        order_id = r.json()["order_id"]
        order = RedemptionOrder.objects.get(order_id=order_id)
        fulfill_redemption_order(order=order, reason="test")
        resp = self.client.post(
            self.api(f"/redemption-orders/{order_id}/cancel"), {},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_dispute_does_not_change_balance(self):
        from core.credit_services import credit_balance
        from core.models import CreditAccount
        login_as_member(self.client, self.member)
        r = self.client.post(
            self.api(f"/members/{self.member.member_no}/redemption-orders"),
            {"credit_amount": 10, "item_type": "meal", "title": "dispute test"},
            content_type="application/json",
        )
        order_id = r.json()["order_id"]
        frozen = CreditAccount.objects.get(account_type=CreditAccount.Type.FROZEN)
        froz_before = credit_balance(frozen)
        resp = self.client.post(
            self.api(f"/redemption-orders/{order_id}/issue"),
            {"reason": "wrong item"}, content_type="application/json",
        )
        self.assertIn(resp.status_code, [200, 201])
        self.assertEqual(resp.json()["status"], "disputed")
        self.assertEqual(credit_balance(frozen), froz_before)

    def test_governance_can_fulfill(self):
        from core.models import RedemptionOrder, CreditAccount
        from core.credit_services import credit_balance
        login_as_member(self.client, self.member)
        r = self.client.post(
            self.api(f"/members/{self.member.member_no}/redemption-orders"),
            {"credit_amount": 10, "item_type": "meal", "title": "fulfill test"},
            content_type="application/json",
        )
        order_id = r.json()["order_id"]
        login_as_member(self.client, self.governor)
        burn_before = credit_balance(CreditAccount.objects.get(account_type=CreditAccount.Type.BURN))
        resp = self.client.post(
            self.api(f"/redemption-orders/{order_id}/fulfill"),
            {"reason": "done"}, content_type="application/json",
        )
        self.assertIn(resp.status_code, [200, 201])
        self.assertEqual(resp.json()["status"], "fulfilled")
        self.assertGreater(credit_balance(CreditAccount.objects.get(account_type=CreditAccount.Type.BURN)), burn_before)

    def test_non_governance_cannot_fulfill(self):
        login_as_member(self.client, self.member)
        r = self.client.post(
            self.api(f"/members/{self.member.member_no}/redemption-orders"),
            {"credit_amount": 10, "item_type": "meal", "title": "x"},
            content_type="application/json",
        )
        order_id = r.json()["order_id"]
        resp = self.client.post(
            self.api(f"/redemption-orders/{order_id}/fulfill"),
            {"reason": "hack"}, content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_list_returns_my_orders(self):
        login_as_member(self.client, self.member)
        self.client.post(
            self.api(f"/members/{self.member.member_no}/redemption-orders"),
            {"credit_amount": 5, "item_type": "meal", "title": "test"},
            content_type="application/json",
        )
        resp = self.client.get(
            self.api(f"/members/{self.member.member_no}/redemption-orders"),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertGreater(len(resp.json()["orders"]), 0)

    def test_put_method_not_allowed(self):
        login_as_member(self.client, self.member)
        resp = self.client.put(
            self.api(f"/members/{self.member.member_no}/redemption-orders"),
            {}, content_type="application/json",
        )
        self.assertEqual(resp.status_code, 405)

    def test_strict_validation_rejects_float_amount(self):
        login_as_member(self.client, self.member)
        resp = self.client.post(
            self.api(f"/members/{self.member.member_no}/redemption-orders"),
            {"credit_amount": 1.5, "item_type": "meal"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_create_idem_different_resource_id_errors(self):
        login_as_member(self.client, self.member)
        key = "ro-api-diff-res"
        self.client.post(
            self.api(f"/members/{self.member.member_no}/redemption-orders"),
            {"credit_amount": 5, "item_type": "meal", "resource_id": "res-a", "idempotency_key": key},
            content_type="application/json",
        )
        resp = self.client.post(
            self.api(f"/members/{self.member.member_no}/redemption-orders"),
            {"credit_amount": 5, "item_type": "meal", "resource_id": "res-b", "idempotency_key": key},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_create_idem_different_snapshot_errors(self):
        login_as_member(self.client, self.member)
        key = "ro-api-diff-snap"
        self.client.post(
            self.api(f"/members/{self.member.member_no}/redemption-orders"),
            {"credit_amount": 5, "item_type": "meal", "item_snapshot": {"v": 1}, "idempotency_key": key},
            content_type="application/json",
        )
        resp = self.client.post(
            self.api(f"/members/{self.member.member_no}/redemption-orders"),
            {"credit_amount": 5, "item_type": "meal", "item_snapshot": {"v": 2}, "idempotency_key": key},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_create_idem_different_finance_ref_errors(self):
        login_as_member(self.client, self.member)
        key = "ro-api-diff-fref"
        self.client.post(
            self.api(f"/members/{self.member.member_no}/redemption-orders"),
            {"credit_amount": 5, "item_type": "meal", "finance_treatment_ref": "F1", "idempotency_key": key},
            content_type="application/json",
        )
        resp = self.client.post(
            self.api(f"/members/{self.member.member_no}/redemption-orders"),
            {"credit_amount": 5, "item_type": "meal", "finance_treatment_ref": "F2", "idempotency_key": key},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_micro_merchant_redemption_blocked_api(self):
        """API: member_micro_merchant 的 merchant_id 创建 RedemptionOrder 返回 400。"""
        from core.models import MerchantProfile
        MerchantProfile.objects.create(
            merchant_id="mch-micro-api", display_name="MicroAPITest",
            merchant_type=MerchantProfile.Type.MEMBER_MICRO,
            operator_member=create_member("mch-micro-op"),
        )
        login_as_member(self.client, self.member)
        resp = self.client.post(
            self.api(f"/members/{self.member.member_no}/redemption-orders"),
            {"credit_amount": 10, "item_type": "meal", "merchant_id": "mch-micro-api"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)


from core.models import MerchantProfile
from core.credit_services import create_redemption_order, fulfill_redemption_order


class MerchantSettlementApiTests(TestCase):
    api_base = "/api/v0.1"

    def setUp(self):
        from core.credit_services import ensure_system_accounts, get_or_create_member_credit_account
        ensure_system_accounts()
        self.governor = create_administrator_member("administrator-settle-api")
        self.operator = create_member("settle-op-api", role_name=ROLE_COVENANTER)
        self.unrelated = create_member("settle-unrel-api", role_name=ROLE_COVENANTER)
        acct = get_or_create_member_credit_account(self.operator)
        from core.credit_services import post_credit_transaction
        from core.models import CreditAccount, CreditTransaction
        pool = CreditAccount.objects.get(account_type=CreditAccount.Type.ISSUANCE_POOL)
        post_credit_transaction(transaction_type=CreditTransaction.Type.ISSUANCE,
                               amount=500, target_account=pool)
        post_credit_transaction(transaction_type=CreditTransaction.Type.ISSUANCE,
                               amount=200, target_account=acct)

        self.merchant = MerchantProfile.objects.create(
            merchant_id="mch-settle-test", display_name="食堂S",
            merchant_type=MerchantProfile.Type.CASH_SETTLEMENT,
            operator_member=self.operator, settlement_rate=0.5,
        )
        order, _ = create_redemption_order(
            member=self.operator, credit_amount=40, merchant=self.merchant,
        )
        fulfill_redemption_order(order=order, reviewed_by=self.governor)

    def api(self, path):
        return f"{self.api_base}{path}"

    def test_governance_sees_all(self):
        login_as_member(self.client, self.governor)
        resp = self.client.get(self.api("/merchant-settlements"))
        self.assertEqual(resp.status_code, 200)
        self.assertGreater(len(resp.json()["settlements"]), 0)

    def test_operator_sees_own(self):
        login_as_member(self.client, self.operator)
        resp = self.client.get(self.api("/merchant-settlements"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreater(len(data["settlements"]), 0)
        self.assertEqual(data["settlements"][0]["merchant_id"], "mch-settle-test")

    def test_unrelated_sees_nothing(self):
        login_as_member(self.client, self.unrelated)
        resp = self.client.get(self.api("/merchant-settlements"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["settlements"]), 0)

    def test_filter_by_merchant_id(self):
        login_as_member(self.client, self.governor)
        resp = self.client.get(self.api("/merchant-settlements?merchant_id=mch-settle-test"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreater(len(data["settlements"]), 0)
        self.assertEqual(data["settlements"][0]["merchant_id"], "mch-settle-test")

    def test_governance_does_not_see_unrelated_on_filter(self):
        login_as_member(self.client, self.unrelated)
        resp = self.client.get(self.api("/merchant-settlements?merchant_id=mch-settle-test"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["settlements"]), 0)

    def test_basic_member_cannot_read_settlements(self):
        basic = create_member("settle-basic-api")
        login_as_member(self.client, basic)
        resp = self.client.get(self.api("/merchant-settlements"))
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["code"], "permission_denied")


class CreditTransferPageTest(TestCase):
    """Workspace credit-transfer page UI tests."""

    def setUp(self):
        from core.credit_services import ensure_system_accounts, get_or_create_member_credit_account, post_credit_transaction
        from core.models import CreditAccount, CreditTransaction
        from core.member_roles import ROLE_COVENANTER
        ensure_system_accounts()
        self.member_a = create_member("transfer-page-a", role_name=ROLE_COVENANTER)
        self.member_b = create_member("transfer-page-b", role_name=ROLE_COVENANTER)
        acct = get_or_create_member_credit_account(self.member_a)
        get_or_create_member_credit_account(self.member_b)
        post_credit_transaction(
            transaction_type=CreditTransaction.Type.ISSUANCE, amount=200, target_account=acct,
        )
        # Basic member without full workspace access
        self.basic = create_member("transfer-page-basic")

    def test_transfer_page_loads(self):
        login_as_member(self.client, self.member_a)
        resp = self.client.get("/workspace/credits/transfer/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "积分转账")

    def test_transfer_page_post_success(self):
        login_as_member(self.client, self.member_a)
        resp = self.client.post(
            "/workspace/credits/transfer/",
            {"to_member_no": self.member_b.member_no, "amount": "30", "reason": "page test"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "30")

    def test_transfer_page_self_rejected(self):
        login_as_member(self.client, self.member_a)
        resp = self.client.post(
            "/workspace/credits/transfer/",
            {"to_member_no": self.member_a.member_no, "amount": "10"},
            follow=False,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "不能向自己转账")

    def test_transfer_page_unauthorized(self):
        resp = self.client.get("/workspace/credits/transfer/")
        self.assertEqual(resp.status_code, 403)

    def test_basic_member_transfer_get_403(self):
        """Basic member without full workspace access gets 403 on transfer GET."""
        login_as_member(self.client, self.basic)
        resp = self.client.get("/workspace/credits/transfer/")
        self.assertEqual(resp.status_code, 403)

    def test_basic_member_transfer_post_403(self):
        """Basic member without full workspace access gets 403 on transfer POST."""
        login_as_member(self.client, self.basic)
        resp = self.client.post(
            "/workspace/credits/transfer/",
            {"to_member_no": self.member_b.member_no, "amount": "10"},
        )
        self.assertEqual(resp.status_code, 403)


class RedemptionOrderPageTest(TestCase):
    """Workspace redemption-order page UI tests."""

    def setUp(self):
        from core.credit_services import ensure_system_accounts, get_or_create_member_credit_account, post_credit_transaction
        from core.models import CreditAccount, CreditTransaction
        from core.member_roles import ROLE_COVENANTER
        ensure_system_accounts()
        self.member = create_member("redemption-page-m", role_name=ROLE_COVENANTER)
        acct = get_or_create_member_credit_account(self.member)
        post_credit_transaction(
            transaction_type=CreditTransaction.Type.ISSUANCE, amount=200, target_account=acct,
        )
        self.basic = create_member("redemption-page-basic")

    def test_redemption_page_loads(self):
        login_as_member(self.client, self.member)
        resp = self.client.get("/workspace/credits/redemption/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "兑换订单")

    def test_create_order_via_page(self):
        login_as_member(self.client, self.member)
        resp = self.client.post(
            "/workspace/credits/redemption/",
            {"create": "1", "credit_amount": "10", "item_type": "meal", "title": "page order"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "积分已冻结")

    def test_cancel_order_via_page(self):
        login_as_member(self.client, self.member)
        # Create an order first
        self.client.post(
            "/workspace/credits/redemption/",
            {"create": "1", "credit_amount": "5", "item_type": "meal", "title": "cancel me"},
        )
        from core.models import RedemptionOrder
        order = RedemptionOrder.objects.filter(member=self.member, title="cancel me").first()
        self.assertIsNotNone(order, "Order should exist before cancel test")
        resp = self.client.post(
            "/workspace/credits/redemption/",
            {"cancel": order.order_id},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "已取消")
        order.refresh_from_db()
        self.assertEqual(order.status, RedemptionOrder.Status.CANCELLED)

    def test_dispute_order_via_page(self):
        login_as_member(self.client, self.member)
        self.client.post(
            "/workspace/credits/redemption/",
            {"create": "1", "credit_amount": "5", "item_type": "meal", "title": "dispute me"},
        )
        from core.models import RedemptionOrder
        order = RedemptionOrder.objects.filter(member=self.member, title="dispute me").first()
        self.assertIsNotNone(order)
        resp = self.client.post(
            "/workspace/credits/redemption/",
            {"report_issue": order.order_id, "issue_reason": "wrong"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "已报告履约问题")
        order.refresh_from_db()
        self.assertEqual(order.status, RedemptionOrder.Status.DISPUTED)

    def test_redemption_page_unauthorized(self):
        resp = self.client.get("/workspace/credits/redemption/")
        self.assertEqual(resp.status_code, 403)

    def test_basic_member_redemption_get_403(self):
        login_as_member(self.client, self.basic)
        resp = self.client.get("/workspace/credits/redemption/")
        self.assertEqual(resp.status_code, 403)

    def test_basic_member_redemption_post_403(self):
        login_as_member(self.client, self.basic)
        resp = self.client.post(
            "/workspace/credits/redemption/",
            {"create": "1", "credit_amount": "10", "item_type": "meal"},
        )
        self.assertEqual(resp.status_code, 403)

    def test_workspace_page_hides_credit_stats_but_keeps_credit_actions(self):
        """Workspace index omits credit summaries while keeping credit action entry points."""
        login_as_member(self.client, self.member)
        resp = self.client.get("/workspace/")
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "当前积分")
        self.assertNotContains(resp, "可用积分")
        self.assertNotContains(resp, "历史贡献")
        self.assertContains(resp, "积分转账")
        self.assertContains(resp, "兑换订单")

    def test_workspace_shows_fulfill_link_for_governance(self):
        """Governance member sees 兑换履约 and 商户结算 nav entries."""
        from core.tests.helpers import create_administrator_member
        from core.credit_services import ensure_system_accounts, get_or_create_member_credit_account, post_credit_transaction
        from core.models import CreditAccount, CreditTransaction
        ensure_system_accounts()
        gov = create_administrator_member("review-test-administrator")
        acct = get_or_create_member_credit_account(gov)
        post_credit_transaction(transaction_type=CreditTransaction.Type.ISSUANCE, amount=100, target_account=acct)
        login_as_member(self.client, gov)
        resp = self.client.get("/workspace/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "兑换履约")
        self.assertContains(resp, "商户结算")

    def test_regular_member_does_not_see_review_link(self):
        """Regular covenanter does NOT see 兑换履约 nav entry."""
        login_as_member(self.client, self.member)
        resp = self.client.get("/workspace/")
        self.assertNotContains(resp, "兑换履约")


class GovernanceReviewPageTests(TestCase):
    """Governance fulfillment page tests."""

    def setUp(self):
        from core.credit_services import ensure_system_accounts, get_or_create_member_credit_account, post_credit_transaction
        from core.models import CreditAccount, CreditTransaction
        from core.tests.helpers import create_administrator_member
        from core.member_roles import ROLE_COVENANTER
        ensure_system_accounts()
        self.gov = create_administrator_member("review-administrator-page")
        self.member = create_member("review-normal", role_name=ROLE_COVENANTER)
        acct = get_or_create_member_credit_account(self.member)
        get_or_create_member_credit_account(self.gov)
        post_credit_transaction(
            transaction_type=CreditTransaction.Type.ISSUANCE, amount=200, target_account=acct,
        )
        # Create a pending redemption order
        from core.credit_services import create_redemption_order as _cro
        self.order, _ = _cro(member=self.member, credit_amount=10, item_type="meal", title="review me")

    def test_governance_can_access_review_page(self):
        login_as_member(self.client, self.gov)
        resp = self.client.get("/workspace/credits/redemption/review/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "兑换履约")

    def test_regular_member_review_403(self):
        login_as_member(self.client, self.member)
        resp = self.client.get("/workspace/credits/redemption/review/")
        self.assertEqual(resp.status_code, 403)

    def test_governance_can_fulfill_pending_order(self):
        from core.models import RedemptionOrder as RO
        login_as_member(self.client, self.gov)
        resp = self.client.post(
            "/workspace/credits/redemption/review/",
            {"fulfill": self.order.order_id},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "已履约")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, RO.Status.FULFILLED)

    def test_cannot_fulfill_cancelled_order(self):
        login_as_member(self.client, self.gov)
        from core.credit_services import cancel_redemption_order
        cancel_redemption_order(order=self.order)
        resp = self.client.post(
            "/workspace/credits/redemption/review/",
            {"fulfill": self.order.order_id},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "不能履约")


class MerchantSettlementsPageTests(TestCase):
    """Merchant settlement read-only page tests."""

    def setUp(self):
        from core.credit_services import ensure_system_accounts, get_or_create_member_credit_account, post_credit_transaction, create_redemption_order as _cro, fulfill_redemption_order
        from core.models import CreditAccount, CreditTransaction, MerchantProfile
        from core.tests.helpers import create_administrator_member
        from core.member_roles import ROLE_COVENANTER
        ensure_system_accounts()
        self.gov = create_administrator_member("settle-administrator-page")
        self.operator = create_member("settle-op-page", role_name=ROLE_COVENANTER)
        self.unrelated = create_member("settle-urel-page", role_name=ROLE_COVENANTER)
        op_acct = get_or_create_member_credit_account(self.operator)
        get_or_create_member_credit_account(self.gov)
        get_or_create_member_credit_account(self.unrelated)
        post_credit_transaction(
            transaction_type=CreditTransaction.Type.ISSUANCE, amount=500, target_account=op_acct,
        )
        pool = CreditAccount.objects.get(account_type=CreditAccount.Type.ISSUANCE_POOL)
        post_credit_transaction(
            transaction_type=CreditTransaction.Type.ISSUANCE, amount=200, target_account=pool,
        )
        self.merchant = MerchantProfile.objects.create(
            merchant_id="mch-settle-page", display_name="结算测试商户",
            merchant_type=MerchantProfile.Type.CASH_SETTLEMENT,
            operator_member=self.operator, settlement_rate=0.5,
            status=MerchantProfile.Status.ACTIVE,
        )
        order, _ = _cro(member=self.operator, credit_amount=40, merchant=self.merchant)
        fulfill_redemption_order(order=order, reviewed_by=self.gov)

    def test_governance_sees_settlements(self):
        login_as_member(self.client, self.gov)
        resp = self.client.get("/workspace/credits/merchant-settlements/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "商户结算")
        self.assertContains(resp, "结算测试商户")

    def test_operator_sees_own_settlements(self):
        login_as_member(self.client, self.operator)
        resp = self.client.get("/workspace/credits/merchant-settlements/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "结算测试商户")

    def test_unrelated_member_403(self):
        login_as_member(self.client, self.unrelated)
        resp = self.client.get("/workspace/credits/merchant-settlements/")
        self.assertEqual(resp.status_code, 403)

    def test_workspace_nav_shows_settlements_for_operator(self):
        login_as_member(self.client, self.operator)
        resp = self.client.get("/workspace/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "商户结算")
        self.assertNotContains(resp, "兑换履约")

    def test_operator_with_no_settlements_gets_200_empty(self):
        """Operator with a merchant but zero settlement records gets 200 + empty list."""
        from core.models import MerchantProfile
        from core.member_roles import ROLE_COVENANTER
        new_op = create_member("settle-empty-op", role_name=ROLE_COVENANTER)
        from core.credit_services import get_or_create_member_credit_account
        get_or_create_member_credit_account(new_op)
        MerchantProfile.objects.create(
            merchant_id="mch-empty-op", display_name="Empty",
            merchant_type=MerchantProfile.Type.CASH_SETTLEMENT,
            operator_member=new_op, settlement_rate=0.5,
            status=MerchantProfile.Status.ACTIVE,
        )
        login_as_member(self.client, new_op)
        resp = self.client.get("/workspace/credits/merchant-settlements/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "暂无结算记录")

    def test_operator_cannot_see_other_merchant_filter(self):
        """Operator cannot use ?merchant_id= to see another merchant's settlements."""
        from core.models import MerchantProfile
        from core.member_roles import ROLE_COVENANTER
        other_op = create_member("settle-other-op", role_name=ROLE_COVENANTER)
        from core.credit_services import get_or_create_member_credit_account
        get_or_create_member_credit_account(other_op)
        other_merchant = MerchantProfile.objects.create(
            merchant_id="mch-other-op", display_name="Other",
            merchant_type=MerchantProfile.Type.CASH_SETTLEMENT,
            operator_member=other_op, settlement_rate=0.5,
            status=MerchantProfile.Status.ACTIVE,
        )
        from core.credit_services import create_redemption_order as _cro, fulfill_redemption_order, post_credit_transaction
        from core.models import CreditTransaction
        other_acct = get_or_create_member_credit_account(other_op)
        post_credit_transaction(
            transaction_type=CreditTransaction.Type.ISSUANCE,
            amount=100,
            target_account=other_acct,
        )
        other_order, _ = _cro(member=other_op, credit_amount=10, merchant=other_merchant)
        fulfill_redemption_order(order=other_order, reviewed_by=self.gov)

        login_as_member(self.client, other_op)
        resp = self.client.get("/workspace/credits/merchant-settlements/?merchant_id=mch-settle-page")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context.get("settlements", [])), 0)

    def test_regular_member_cannot_access_settlements(self):
        """Regular covenanter (not operator, not governance) gets 403."""
        from core.member_roles import ROLE_COVENANTER
        reg = create_member("settle-regular", role_name=ROLE_COVENANTER)
        from core.credit_services import get_or_create_member_credit_account
        get_or_create_member_credit_account(reg)
        login_as_member(self.client, reg)
        resp = self.client.get("/workspace/credits/merchant-settlements/")
        self.assertEqual(resp.status_code, 403)

    def test_regular_member_cannot_access_review_page(self):
        """Regular member cannot access fulfillment page."""
        from core.member_roles import ROLE_COVENANTER
        reg = create_member("review-regular", role_name=ROLE_COVENANTER)
        from core.credit_services import get_or_create_member_credit_account
        get_or_create_member_credit_account(reg)
        login_as_member(self.client, reg)
        resp = self.client.get("/workspace/credits/redemption/review/")
        self.assertEqual(resp.status_code, 403)


class RedemptionMerchantUITests(TestCase):
    """UI tests for merchant dropdown and merchant-id post behavior."""

    def setUp(self):
        from core.credit_services import ensure_system_accounts, get_or_create_member_credit_account, post_credit_transaction
        from core.models import CreditAccount, CreditTransaction, MerchantProfile
        from core.member_roles import ROLE_COVENANTER
        ensure_system_accounts()
        self.member = create_member("redo-merchant", role_name=ROLE_COVENANTER)
        acct = get_or_create_member_credit_account(self.member)
        post_credit_transaction(
            transaction_type=CreditTransaction.Type.ISSUANCE, amount=200, target_account=acct,
        )
        self.cash = MerchantProfile.objects.create(
            merchant_id="redo-cash", display_name="ReDo Cash",
            merchant_type=MerchantProfile.Type.CASH_SETTLEMENT,
            operator_member=self.member, settlement_rate=0.5,
            status=MerchantProfile.Status.ACTIVE,
        )
        self.micro = MerchantProfile.objects.create(
            merchant_id="redo-micro", display_name="ReDo Micro",
            merchant_type=MerchantProfile.Type.MEMBER_MICRO,
            operator_member=self.member,
        )
        self.suspended = MerchantProfile.objects.create(
            merchant_id="redo-sus", display_name="ReDo Closed",
            merchant_type=MerchantProfile.Type.CASH_SETTLEMENT,
            operator_member=self.member, settlement_rate=0.3,
            status=MerchantProfile.Status.SUSPENDED,
        )

    def test_cash_merchant_appears_in_dropdown(self):
        login_as_member(self.client, self.member)
        resp = self.client.get("/workspace/credits/redemption/")
        self.assertContains(resp, self.cash.merchant_id)

    def test_micro_merchant_not_in_dropdown(self):
        login_as_member(self.client, self.member)
        resp = self.client.get("/workspace/credits/redemption/")
        self.assertNotContains(resp, self.micro.merchant_id)

    def test_suspended_merchant_not_in_dropdown(self):
        login_as_member(self.client, self.member)
        resp = self.client.get("/workspace/credits/redemption/")
        self.assertNotContains(resp, self.suspended.merchant_id)

    def test_create_order_with_cash_merchant(self):
        login_as_member(self.client, self.member)
        resp = self.client.post(
            "/workspace/credits/redemption/",
            {"create": "1", "credit_amount": "15", "item_type": "meal",
             "merchant_id": self.cash.merchant_id, "title": "merchant order"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "积分已冻结")
        from core.models import RedemptionOrder
        order = RedemptionOrder.objects.filter(member=self.member, merchant=self.cash).first()
        self.assertIsNotNone(order, "Order should have merchant FK set")

    def test_create_order_with_micro_merchant_rejected(self):
        login_as_member(self.client, self.member)
        resp = self.client.post(
            "/workspace/credits/redemption/",
            {"create": "1", "credit_amount": "10", "item_type": "meal",
             "merchant_id": self.micro.merchant_id},
            follow=False,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "微创业")

class SeedCreditsQaCommandTests(TestCase):
    """Manual-QA seed command tests."""

    def test_seed_creates_login_users_and_is_idempotent(self):
        call_command("seed_credits_qa", "--yes", stdout=StringIO())

        user_model = get_user_model()
        user_a = user_model.objects.get(username="qa-a")
        user_b = user_model.objects.get(username="qa-b")
        user_administrator = user_model.objects.get(username="qa-administrator")
        self.assertTrue(user_a.check_password("test-password"))
        self.assertTrue(user_b.check_password("test-password"))
        self.assertTrue(user_administrator.check_password("test-password"))

        member_a = Member.objects.get(member_no="qa-a")
        self.assertEqual(member_a.user_id, user_a.pk)
        member_administrator = Member.objects.get(member_no="qa-administrator")
        from core.access import member_can_administer
        self.assertTrue(member_can_administer(member_administrator))

        from core.credit_services import member_credit_balance
        self.assertEqual(member_credit_balance(member_a), 500)

        call_command("seed_credits_qa", "--yes", stdout=StringIO())
        member_a.refresh_from_db()
        self.assertEqual(member_credit_balance(member_a), 500)

    def test_seed_requires_explicit_confirmation(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("seed_credits_qa", stdout=StringIO())


class CreditBudgetsPageTests(TestCase):
    """Governance credits/budgets page UI tests."""

    def setUp(self):
        from core.credit_services import ensure_system_accounts, issue_credits_to_pool, get_or_create_member_credit_account, post_credit_transaction
        from core.models import CreditAccount, CreditTransaction
        from core.tests.helpers import create_administrator_member
        from core.member_roles import ROLE_COVENANTER
        ensure_system_accounts()
        self.gov = create_administrator_member("budget-administrator-page")
        self.normal = create_member("budget-normal", role_name=ROLE_COVENANTER)
        get_or_create_member_credit_account(self.gov)
        get_or_create_member_credit_account(self.normal)
        # Give pool some initial credits for lock/unlock tests
        pool = CreditAccount.objects.get(account_type=CreditAccount.Type.ISSUANCE_POOL)
        post_credit_transaction(
            transaction_type=CreditTransaction.Type.ISSUANCE, amount=500, target_account=pool,
        )
        # Create a task to lock budget against
        from core.models import Task
        from django.utils import timezone
        self.task = Task.objects.create(
            task_id="task-budget-test", title="Budget test task",
            task_type=Task.TaskType.PUBLIC_CLEANING, status=Task.Status.OPEN,
            standard_minutes=60, base_points=30, rule_version="v1", requires_review=True,
            created_at=timezone.now(),
        )

    def test_governance_can_access_budgets_page(self):
        login_as_member(self.client, self.gov)
        resp = self.client.get("/workspace/credits/budgets/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "积分预算")

    def test_normal_member_budgets_403(self):
        login_as_member(self.client, self.normal)
        resp = self.client.get("/workspace/credits/budgets/")
        self.assertEqual(resp.status_code, 403)

    def test_issue_credits_increases_pool(self):
        login_as_member(self.client, self.gov)
        resp = self.client.post(
            "/workspace/credits/budgets/",
            {"action": "issue", "amount": "100", "reason": "test issue", "idempotency_key": "test-issue-key"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "成功发行 100 积分")

    def test_issue_creates_system_accounts_when_missing(self):
        from core.models import CreditAccount, CreditTransaction
        CreditTransaction.objects.all().delete()
        CreditAccount.objects.all().delete()
        login_as_member(self.client, self.gov)
        resp = self.client.post(
            "/workspace/credits/budgets/",
            {"action": "issue", "amount": "100", "reason": "first issue", "idempotency_key": "test-issue-first"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "成功发行 100 积分")
        self.assertTrue(
            CreditAccount.objects.filter(account_type=CreditAccount.Type.ISSUANCE_POOL).exists()
        )

    def test_lock_budget_decreases_pool(self):
        login_as_member(self.client, self.gov)
        resp = self.client.post(
            "/workspace/credits/budgets/",
            {"action": "lock", "task_id": self.task.task_id, "amount": "50", "reason": "test lock", "idempotency_key": "test-lock-key"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "锁定 50 积分")

    def test_lock_exceeds_pool_fails(self):
        login_as_member(self.client, self.gov)
        resp = self.client.post(
            "/workspace/credits/budgets/",
            {"action": "lock", "task_id": self.task.task_id, "amount": "9999", "reason": "too much", "idempotency_key": "test-lock-over"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "不足")

    def test_unlock_succeeds(self):
        from core.credit_services import lock_task_credit_budget
        lock_task_credit_budget(task=self.task, amount=50, reason="pre-lock")
        login_as_member(self.client, self.gov)
        resp = self.client.post(
            "/workspace/credits/budgets/",
            {"action": "unlock", "task_id": self.task.task_id, "amount": "20", "reason": "unlock test", "idempotency_key": "test-unlock-key"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "退回 20 积分")

    def test_unlock_exceeds_remaining_fails(self):
        from core.credit_services import lock_task_credit_budget
        lock_task_credit_budget(task=self.task, amount=30, reason="pre-lock")
        login_as_member(self.client, self.gov)
        resp = self.client.post(
            "/workspace/credits/budgets/",
            {"action": "unlock", "task_id": self.task.task_id, "amount": "999", "reason": "too much", "idempotency_key": "test-unlock-over"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "超过该任务剩余锁定预算")

    def test_invalid_amount_rejected(self):
        login_as_member(self.client, self.gov)
        for bad in ["0", "-10", "abc"]:
            resp = self.client.post(
                "/workspace/credits/budgets/",
                {"action": "issue", "amount": bad, "idempotency_key": "test-issue-bad"},
                follow=True,
            )
            self.assertContains(resp, "正整数", msg_prefix=f"amount={bad}")

    def test_nonexistent_task_rejected(self):
        login_as_member(self.client, self.gov)
        resp = self.client.post(
            "/workspace/credits/budgets/",
            {"action": "lock", "task_id": "task-does-not-exist", "amount": "10", "idempotency_key": "test-lock-missing"},
            follow=True,
        )
        self.assertContains(resp, "不存在")

    def test_workspace_nav_shows_budgets_for_governance(self):
        login_as_member(self.client, self.gov)
        resp = self.client.get("/workspace/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "积分预算")

    def test_workspace_nav_hides_budgets_for_normal(self):
        login_as_member(self.client, self.normal)
        resp = self.client.get("/workspace/")
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "积分预算")

    def test_issue_auto_creates_pool_on_cold_start(self):
        """After deleting CreditTransaction+CreditAccount, POST issue still works
        because ensure_system_accounts() re-creates the issuance pool."""
        from core.models import CreditAccount, CreditTransaction
        from core.credit_services import credit_balance

        # Delete in FK-safe order: transactions first, then accounts
        pool = CreditAccount.objects.filter(account_type=CreditAccount.Type.ISSUANCE_POOL).first()
        if pool:
            CreditTransaction.objects.filter(source_account=pool).delete()
            CreditTransaction.objects.filter(target_account=pool).delete()
            pool.delete()

        # Now no issuance_pool exists — budgets_page() must recreate it
        login_as_member(self.client, self.gov)
        resp = self.client.post(
            "/workspace/credits/budgets/",
            {"action": "issue", "amount": "50", "reason": "cold start test", "idempotency_key": "test-issue-cold"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "成功发行 50 积分")

        # Verify pool exists and has balance
        pool = CreditAccount.objects.filter(account_type=CreditAccount.Type.ISSUANCE_POOL).first()
        self.assertIsNotNone(pool, "Pool should be re-created by ensure_system_accounts()")
        self.assertGreaterEqual(credit_balance(pool), 50)


class TaskManagePageTests(TestCase):
    """Governance task creation and publishing UI tests."""

    def setUp(self):
        from core.credit_services import ensure_system_accounts, issue_credits_to_pool, get_or_create_member_credit_account, post_credit_transaction
        from core.models import CreditAccount, CreditTransaction
        from core.tests.helpers import create_administrator_member
        from core.member_roles import ROLE_COVENANTER
        from django.utils import timezone
        ensure_system_accounts()
        self.gov = create_administrator_member("task-mgmt-administrator")
        self.normal = create_member("task-mgmt-normal", role_name=ROLE_COVENANTER)
        get_or_create_member_credit_account(self.gov)
        get_or_create_member_credit_account(self.normal)
        # Give pool some credits for publish-with-budget tests
        pool = CreditAccount.objects.get(account_type=CreditAccount.Type.ISSUANCE_POOL)
        post_credit_transaction(
            transaction_type=CreditTransaction.Type.ISSUANCE, amount=500, target_account=pool,
        )

    def test_governance_can_access_task_create_page(self):
        login_as_member(self.client, self.gov)
        resp = self.client.get("/workspace/tasks/new/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "任务管理")

    def test_normal_member_task_create_403(self):
        login_as_member(self.client, self.normal)
        resp = self.client.get("/workspace/tasks/new/")
        self.assertEqual(resp.status_code, 403)

    def test_create_draft_with_zero_points_succeeds(self):
        """base_points=0 表示无积分奖励任务，创建应成功。"""
        login_as_member(self.client, self.gov)
        resp = self.client.post(
            "/workspace/tasks/new/",
            {"title": "Zero point task", "task_type": "public_cleaning",
             "standard_minutes": "60", "base_points": "0"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "已创建为草稿")
        self.assertEqual(
            Task.objects.get(title="Zero point task").standard_minutes,
            60,
        )

    def test_create_draft_with_points(self):
        login_as_member(self.client, self.gov)
        resp = self.client.post(
            "/workspace/tasks/new/",
            {"title": "Reward task", "task_type": "cooking",
             "standard_minutes": "120", "base_points": "30"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "已创建为草稿")

    def test_empty_title_rejected(self):
        login_as_member(self.client, self.gov)
        resp = self.client.post(
            "/workspace/tasks/new/",
            {"title": "", "task_type": "public_cleaning",
             "standard_minutes": "60", "base_points": "0"},
            follow=True,
        )
        self.assertContains(resp, "标题不能为空")

    def test_negative_base_points_rejected(self):
        login_as_member(self.client, self.gov)
        resp = self.client.post(
            "/workspace/tasks/new/",
            {"title": "Bad task", "task_type": "public_cleaning",
             "standard_minutes": "60", "base_points": "-10"},
            follow=True,
        )
        self.assertContains(resp, "非负整数")

    def test_invalid_standard_minutes_rejected(self):
        login_as_member(self.client, self.gov)
        for bad in ["0", "-1", "1.5", "abc"]:
            resp = self.client.post(
                "/workspace/tasks/new/",
                {"title": "Bad hours", "task_type": "public_cleaning",
                 "standard_minutes": bad, "base_points": "0"},
                follow=True,
            )
            self.assertContains(resp, "标准工时", msg_prefix=f"minutes={bad}")

    def test_invalid_task_type_rejected(self):
        login_as_member(self.client, self.gov)
        resp = self.client.post(
            "/workspace/tasks/new/",
            {"title": "Bad type", "task_type": "INVALID_TYPE",
             "standard_minutes": "60", "base_points": "0"},
            follow=True,
        )
        self.assertContains(resp, "无效的任务类型")

    def test_publish_zero_points_task_succeeds_no_budget(self):
        """base_points=0 的任务发布不需要锁定预算。"""
        from core.tasks.authoring import create_task_draft
        from decimal import Decimal
        task = create_task_draft(
            title="Pub zero points", task_type="public_cleaning", standard_minutes=60,
            base_points=0, role_coefficient=Decimal("1.0"), failure_consequence="",
            can_be_delayed=True, requires_review=True, rule_version="ruleset-v0.1.0",
            created_by={"actor_id": "gov", "display_name": "Gov"},
        )
        login_as_member(self.client, self.gov)
        resp = self.client.post(
            f"/workspace/tasks/{task.task_id}/publish/", {"reason": ""}, follow=True,
        )
        self.assertContains(resp, "已发布")
        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.OPEN)

    def test_publish_with_points_no_budget_fails(self):
        from core.tasks.authoring import create_task_draft
        from decimal import Decimal
        task = create_task_draft(
            title="Pub reward no budget", task_type="public_cleaning", standard_minutes=60,
            base_points=30, role_coefficient=Decimal("1.0"), failure_consequence="",
            can_be_delayed=True, requires_review=True, rule_version="ruleset-v0.1.0",
            created_by={"actor_id": "gov", "display_name": "Gov"},
        )
        login_as_member(self.client, self.gov)
        resp = self.client.post(
            f"/workspace/tasks/{task.task_id}/publish/", {"reason": ""}, follow=True,
        )
        self.assertContains(resp, "预算")
        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.DRAFT)

    def test_publish_with_points_and_budget_succeeds(self):
        from core.tasks.authoring import create_task_draft
        from core.credit_services import lock_task_credit_budget
        from decimal import Decimal
        task = create_task_draft(
            title="Pub reward budget", task_type="public_cleaning", standard_minutes=60,
            base_points=30, role_coefficient=Decimal("1.0"), failure_consequence="",
            can_be_delayed=True, requires_review=True, rule_version="ruleset-v0.1.0",
            created_by={"actor_id": "gov", "display_name": "Gov"},
        )
        lock_task_credit_budget(task=task, amount=50, reason="test")
        login_as_member(self.client, self.gov)
        resp = self.client.post(
            f"/workspace/tasks/{task.task_id}/publish/", {"reason": ""}, follow=True,
        )
        self.assertContains(resp, "已发布")
        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.OPEN)

    def test_normal_member_cannot_publish(self):
        from core.tasks.authoring import create_task_draft
        from decimal import Decimal
        task = create_task_draft(
            title="Normal publish hack", task_type="public_cleaning", standard_minutes=60,
            base_points=1, role_coefficient=Decimal("1.0"), failure_consequence="",
            can_be_delayed=True, requires_review=True, rule_version="ruleset-v0.1.0",
            created_by={"actor_id": "gov", "display_name": "Gov"},
        )
        login_as_member(self.client, self.normal)
        resp = self.client.post(
            f"/workspace/tasks/{task.task_id}/publish/", {"reason": ""}, follow=True,
        )
        self.assertNotEqual(resp.status_code, 302)  # not a redirect, must be 403

    def test_workspace_nav_shows_create_task_for_gov(self):
        login_as_member(self.client, self.gov)
        resp = self.client.get("/workspace/")
        self.assertContains(resp, "创建任务")

    def test_workspace_nav_hides_create_task_for_normal(self):
        login_as_member(self.client, self.normal)
        resp = self.client.get("/workspace/")
        self.assertNotContains(resp, "创建任务")


class TaskReviewPageTests(TestCase):
    """Governance task review UI tests."""

    def setUp(self):
        from core.credit_services import ensure_system_accounts, lock_task_credit_budget, get_or_create_member_credit_account, post_credit_transaction, issue_credits_to_pool
        from core.models import CreditAccount, CreditTransaction
        from core.tests.helpers import create_administrator_member
        from core.member_roles import ROLE_COVENANTER
        from core.tasks.member_workflow import claim_task, submit_labor
        from core.tasks.authoring import create_task_draft, publish_task
        from decimal import Decimal
        from django.utils import timezone
        ensure_system_accounts()
        self.gov = create_administrator_member("task-review-administrator")
        self.worker = create_member("task-review-worker", role_name=ROLE_COVENANTER)
        self.normal = create_member("task-review-normal", role_name=ROLE_COVENANTER)
        get_or_create_member_credit_account(self.gov)
        get_or_create_member_credit_account(self.worker)
        get_or_create_member_credit_account(self.normal)
        pool = CreditAccount.objects.get(account_type=CreditAccount.Type.ISSUANCE_POOL)
        post_credit_transaction(
            transaction_type=CreditTransaction.Type.ISSUANCE, amount=500, target_account=pool,
        )

        # Create and submit a task for review
        self.reward_task = create_task_draft(
            title="Review reward test", task_type="public_cleaning", standard_minutes=60,
            base_points=30, role_coefficient=Decimal("1.0"), failure_consequence="",
            can_be_delayed=True, requires_review=True, rule_version="ruleset-v0.1.0",
            created_by={"actor_id": "gov", "display_name": "Gov"},
        )
        lock_task_credit_budget(task=self.reward_task, amount=50, reason="test budget")
        publish_task(task=self.reward_task, publisher={"actor_id": "gov", "display_name": "Gov"})
        claim_task(task=self.reward_task, member=self.worker)
        self.reward_task.refresh_from_db()
        submit_labor(task=self.reward_task, member=self.worker, labor_note="QA labor", evidence_refs=["img-01"])

        # Create a no-reward task
        self.no_reward_task = create_task_draft(
            title="Review no reward", task_type="public_cleaning", standard_minutes=60,
            base_points=0, role_coefficient=Decimal("1.0"), failure_consequence="",
            can_be_delayed=True, requires_review=True, rule_version="ruleset-v0.1.0",
            created_by={"actor_id": "gov", "display_name": "Gov"},
        )
        publish_task(task=self.no_reward_task, publisher={"actor_id": "gov", "display_name": "Gov"})
        claim_task(task=self.no_reward_task, member=self.worker)
        self.no_reward_task.refresh_from_db()
        submit_labor(task=self.no_reward_task, member=self.worker, labor_note="No reward labor", evidence_refs=[])

    def test_governance_can_access_review_page(self):
        login_as_member(self.client, self.gov)
        resp = self.client.get("/workspace/tasks/review/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "任务验收")

    def test_normal_member_review_403(self):
        login_as_member(self.client, self.normal)
        resp = self.client.get("/workspace/tasks/review/")
        self.assertEqual(resp.status_code, 403)

    def test_page_lists_pending_review_tasks(self):
        login_as_member(self.client, self.gov)
        resp = self.client.get("/workspace/tasks/review/")
        self.assertContains(resp, self.reward_task.task_id)
        self.assertContains(resp, self.no_reward_task.task_id)

    def test_page_excludes_draft_tasks(self):
        from core.tasks.authoring import create_task_draft
        from decimal import Decimal
        draft = create_task_draft(
            title="Draft should not show", task_type="public_cleaning", standard_minutes=60,
            base_points=0, role_coefficient=Decimal("1.0"), failure_consequence="",
            can_be_delayed=True, requires_review=True, rule_version="ruleset-v0.1.0",
            created_by={"actor_id": "gov", "display_name": "Gov"},
        )
        login_as_member(self.client, self.gov)
        resp = self.client.get("/workspace/tasks/review/")
        self.assertNotContains(resp, draft.task_id)

    def test_accept_with_budget_succeeds(self):
        from core.credit_services import member_credit_balance
        bal_before = member_credit_balance(self.worker)
        login_as_member(self.client, self.gov)
        resp = self.client.post(
            "/workspace/tasks/review/",
            {"task_id": self.reward_task.task_id, "decision": "accepted", "reason": "good work"},
            follow=True,
        )
        self.assertContains(resp, "验收通过")
        self.reward_task.refresh_from_db()
        self.assertEqual(self.reward_task.status, Task.Status.ACCEPTED)
        # Worker should have received points
        self.assertGreater(member_credit_balance(self.worker), bal_before)

    def test_accept_without_budget_shows_error(self):
        """Lock budget→publish→unlock budget→review should fail with budget error."""
        from core.tasks.authoring import create_task_draft, publish_task
        from core.tasks.member_workflow import claim_task, submit_labor
        from core.credit_services import lock_task_credit_budget, unlock_unused_task_credit_budget
        from decimal import Decimal
        task = create_task_draft(
            title="No budget task", task_type="public_cleaning", standard_minutes=60,
            base_points=30, role_coefficient=Decimal("1.0"), failure_consequence="",
            can_be_delayed=True, requires_review=True, rule_version="ruleset-v0.1.0",
            created_by={"actor_id": "gov", "display_name": "Gov"},
        )
        lock_task_credit_budget(task=task, amount=30, reason="temp budget")
        publish_task(task=task, publisher={"actor_id": "gov", "display_name": "Gov"})
        unlock_unused_task_credit_budget(task=task, amount=30, reason="remove budget for test")
        claim_task(task=task, member=self.worker)
        task.refresh_from_db()
        submit_labor(task=task, member=self.worker, labor_note="no budget", evidence_refs=[])

        login_as_member(self.client, self.gov)
        resp = self.client.post(
            "/workspace/tasks/review/",
            {"task_id": task.task_id, "decision": "accepted", "reason": "try"},
            follow=True,
        )
        self.assertContains(resp, "预算")
        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.PENDING_REVIEW)

    def test_reject_succeeds_no_points(self):
        from core.credit_services import member_credit_balance
        bal_before = member_credit_balance(self.worker)
        login_as_member(self.client, self.gov)
        resp = self.client.post(
            "/workspace/tasks/review/",
            {"task_id": self.no_reward_task.task_id, "decision": "rejected", "reason": "not good enough"},
            follow=True,
        )
        self.assertContains(resp, "驳回")
        self.no_reward_task.refresh_from_db()
        self.assertEqual(self.no_reward_task.status, Task.Status.REJECTED)
        self.assertEqual(member_credit_balance(self.worker), bal_before)

    def test_invalid_decision_shows_error(self):
        login_as_member(self.client, self.gov)
        resp = self.client.post(
            "/workspace/tasks/review/",
            {"task_id": self.reward_task.task_id, "decision": "INVALID"},
            follow=True,
        )
        self.assertContains(resp, "accepted 或 rejected")

    def test_nonexistent_task_shows_error(self):
        login_as_member(self.client, self.gov)
        resp = self.client.post(
            "/workspace/tasks/review/",
            {"task_id": "task-does-not-exist-review", "decision": "accepted"},
            follow=True,
        )
        self.assertContains(resp, "不存在")

    def test_normal_member_cannot_post_review(self):
        login_as_member(self.client, self.normal)
        resp = self.client.post(
            "/workspace/tasks/review/",
            {"task_id": self.reward_task.task_id, "decision": "accepted"},
            follow=True,
        )
        self.assertNotEqual(resp.status_code, 302)

    def test_double_accept_blocked_by_service(self):
        """Duplicate accept should be blocked — service rejects non-pending review task."""
        login_as_member(self.client, self.gov)
        self.client.post(
            "/workspace/tasks/review/",
            {"task_id": self.reward_task.task_id, "decision": "accepted", "reason": "first"},
            follow=True,
        )
        resp = self.client.post(
            "/workspace/tasks/review/",
            {"task_id": self.reward_task.task_id, "decision": "accepted", "reason": "second try"},
            follow=True,
        )
        # Service rejects because status is no longer PENDING_REVIEW
        self.assertContains(resp, "Only tasks pending review")

    def test_workspace_nav_shows_review_url_for_gov(self):
        login_as_member(self.client, self.gov)
        resp = self.client.get("/workspace/")
        self.assertContains(resp, "/tasks/review/")

    def test_workspace_nav_hides_review_url_for_normal(self):
        from core.member_roles import ROLE_COVENANTER
        reg = create_member("task-review-regular-nav3", role_name=ROLE_COVENANTER)
        login_as_member(self.client, reg)
        resp = self.client.get("/workspace/")
        self.assertNotContains(resp, "/tasks/review/")

    def test_accept_zero_point_task_succeeds_no_points(self):
        """base_points=0 的任务验收通过 → ACCEPTED，成员积分不变。"""
        from core.credit_services import member_credit_balance
        bal_before = member_credit_balance(self.worker)
        login_as_member(self.client, self.gov)
        resp = self.client.post(
            "/workspace/tasks/review/",
            {"task_id": self.no_reward_task.task_id, "decision": "accepted", "reason": "zero point ok"},
            follow=True,
        )
        self.assertContains(resp, "验收通过")
        self.no_reward_task.refresh_from_db()
        self.assertEqual(self.no_reward_task.status, Task.Status.ACCEPTED)
        self.assertEqual(member_credit_balance(self.worker), bal_before,
                         "0 分验收不应增加成员积分")

    def test_cold_start_review_page_200_for_zero_point(self):
        """删除 CreditTransaction+CreditAccount 后，0 分任务验收页仍 200。"""
        from core.models import CreditAccount, CreditTransaction
        from core.credit_services import ensure_system_accounts
        # Delete in safe order
        pool = CreditAccount.objects.filter(account_type=CreditAccount.Type.ISSUANCE_POOL).first()
        if pool:
            CreditTransaction.objects.filter(source_account=pool).delete()
            CreditTransaction.objects.filter(target_account=pool).delete()
            pool.delete()
        login_as_member(self.client, self.gov)
        resp = self.client.get("/workspace/tasks/review/")
        self.assertEqual(resp.status_code, 200)

    def test_task_manage_page_200_on_cold_start(self):
        """Cold start: delete all CreditAccount/CreditTransaction, GET tasks/new/ still 200."""
        from core.models import CreditAccount, CreditTransaction
        pool = CreditAccount.objects.filter(account_type=CreditAccount.Type.ISSUANCE_POOL).first()
        if pool:
            CreditTransaction.objects.filter(source_account=pool).delete()
            CreditTransaction.objects.filter(target_account=pool).delete()
            pool.delete()
        task_locked = CreditAccount.objects.filter(account_type=CreditAccount.Type.TASK_LOCKED).first()
        if task_locked:
            CreditTransaction.objects.filter(source_account=task_locked).delete()
            CreditTransaction.objects.filter(target_account=task_locked).delete()
            task_locked.delete()
        login_as_member(self.client, self.gov)
        resp = self.client.get("/workspace/tasks/new/")
        self.assertEqual(resp.status_code, 200)


class BudgetIdempotencyTests(TestCase):
    """Budget page per-render idempotency key tests."""

    def setUp(self):
        from core.credit_services import ensure_system_accounts, get_or_create_member_credit_account, post_credit_transaction
        from core.models import CreditAccount, CreditTransaction
        from core.tests.helpers import create_administrator_member
        from django.utils import timezone
        ensure_system_accounts()
        self.gov = create_administrator_member("budget-idem-administrator")
        get_or_create_member_credit_account(self.gov)
        pool = CreditAccount.objects.get(account_type=CreditAccount.Type.ISSUANCE_POOL)
        post_credit_transaction(
            transaction_type=CreditTransaction.Type.ISSUANCE, amount=500, target_account=pool,
        )
        self.task = Task.objects.create(
            task_id="task-idem-test", title="Idem test task",
            task_type=Task.TaskType.PUBLIC_CLEANING, status=Task.Status.DRAFT,
            standard_minutes=60, base_points=10, rule_version="ruleset-v0.1.0",
            requires_review=True, created_at=timezone.now(),
        )

    def test_issue_same_key_no_duplicate(self):
        """同 hidden key 重复提交 issue 不重复发行。"""
        from core.models import CreditTransaction
        before = CreditTransaction.objects.filter(
            transaction_type=CreditTransaction.Type.ISSUANCE,
        ).count()
        login_as_member(self.client, self.gov)
        key = "idem-test-issue-same-key"
        for _ in range(2):
            self.client.post(
                "/workspace/credits/budgets/",
                {"action": "issue", "amount": "100", "reason": "idem test",
                 "idempotency_key": key},
            )
        after = CreditTransaction.objects.filter(
            transaction_type=CreditTransaction.Type.ISSUANCE,
        ).count()
        self.assertEqual(after, before + 1, "同 key 重复提交应只生成一笔 issue")

    def test_issue_new_key_creates_new_txn(self):
        """刷新页面获得新 key 后再次发行相同 amount，应新增第二笔。"""
        from core.models import CreditTransaction
        before = CreditTransaction.objects.filter(
            transaction_type=CreditTransaction.Type.ISSUANCE,
        ).count()
        login_as_member(self.client, self.gov)
        self.client.post(
            "/workspace/credits/budgets/",
            {"action": "issue", "amount": "100", "reason": "first",
             "idempotency_key": "idem-test-issue-key1"},
        )
        self.client.post(
            "/workspace/credits/budgets/",
            {"action": "issue", "amount": "100", "reason": "second",
             "idempotency_key": "idem-test-issue-key2"},
        )
        after = CreditTransaction.objects.filter(
            transaction_type=CreditTransaction.Type.ISSUANCE,
        ).count()
        self.assertEqual(after, before + 2, "新 key 应新增第二笔发行")

    def test_lock_same_key_no_duplicate(self):
        """同 hidden key 重复提交 lock 不重复锁定。"""
        from core.models import CreditTransaction
        before = CreditTransaction.objects.filter(
            transaction_type=CreditTransaction.Type.LOCK,
        ).count()
        login_as_member(self.client, self.gov)
        key = "idem-test-lock-same-key"
        for _ in range(2):
            self.client.post(
                "/workspace/credits/budgets/",
                {"action": "lock", "task_id": self.task.task_id, "amount": "50",
                 "reason": "idem lock", "idempotency_key": key},
            )
        after = CreditTransaction.objects.filter(
            transaction_type=CreditTransaction.Type.LOCK,
        ).count()
        self.assertEqual(after, before + 1, "同 key 重复提交应只生成一笔 lock")

    def test_lock_new_key_creates_new_lock(self):
        """新 key 同 task+amount 可再次锁定。"""
        from core.models import CreditTransaction
        before = CreditTransaction.objects.filter(
            transaction_type=CreditTransaction.Type.LOCK,
        ).count()
        login_as_member(self.client, self.gov)
        self.client.post(
            "/workspace/credits/budgets/",
            {"action": "lock", "task_id": self.task.task_id, "amount": "50",
             "reason": "first lock", "idempotency_key": "idem-test-lock-key1"},
        )
        self.client.post(
            "/workspace/credits/budgets/",
            {"action": "lock", "task_id": self.task.task_id, "amount": "50",
             "reason": "second lock", "idempotency_key": "idem-test-lock-key2"},
        )
        after = CreditTransaction.objects.filter(
            transaction_type=CreditTransaction.Type.LOCK,
        ).count()
        self.assertEqual(after, before + 2, "新 key 应新增第二笔锁定")

    def test_unlock_same_key_no_duplicate(self):
        """同 hidden key 重复提交 unlock 不重复退回。"""
        from core.credit_services import lock_task_credit_budget
        lock_task_credit_budget(task=self.task, amount=80, reason="pre-lock")
        from core.models import CreditTransaction
        before = CreditTransaction.objects.filter(
            transaction_type=CreditTransaction.Type.UNLOCK,
        ).count()
        login_as_member(self.client, self.gov)
        key = "idem-test-unlock-same-key"
        for _ in range(2):
            self.client.post(
                "/workspace/credits/budgets/",
                {"action": "unlock", "task_id": self.task.task_id, "amount": "30",
                 "reason": "idem unlock", "idempotency_key": key},
            )
        after = CreditTransaction.objects.filter(
            transaction_type=CreditTransaction.Type.UNLOCK,
        ).count()
        self.assertEqual(after, before + 1, "同 key 重复提交应只生成一笔 unlock")

    def test_unlock_new_key_creates_new_unlock(self):
        """新 key 在有剩余预算时可再次退回。"""
        from core.credit_services import lock_task_credit_budget
        lock_task_credit_budget(task=self.task, amount=100, reason="big lock")
        from core.models import CreditTransaction
        before = CreditTransaction.objects.filter(
            transaction_type=CreditTransaction.Type.UNLOCK,
        ).count()
        login_as_member(self.client, self.gov)
        self.client.post(
            "/workspace/credits/budgets/",
            {"action": "unlock", "task_id": self.task.task_id, "amount": "20",
             "reason": "first unlock", "idempotency_key": "idem-test-unlock-key1"},
        )
        self.client.post(
            "/workspace/credits/budgets/",
            {"action": "unlock", "task_id": self.task.task_id, "amount": "20",
             "reason": "second unlock", "idempotency_key": "idem-test-unlock-key2"},
        )
        after = CreditTransaction.objects.filter(
            transaction_type=CreditTransaction.Type.UNLOCK,
        ).count()
        self.assertEqual(after, before + 2, "新 key 应新增第二笔退回")

    def test_missing_key_returns_error(self):
        """缺少 idempotency_key 的 POST 返回错误，不创建交易。"""
        from core.models import CreditTransaction
        before = CreditTransaction.objects.filter(
            transaction_type=CreditTransaction.Type.ISSUANCE,
        ).count()
        login_as_member(self.client, self.gov)
        resp = self.client.post(
            "/workspace/credits/budgets/",
            {"action": "issue", "amount": "100"},
        )
        self.assertContains(resp, "缺少幂等键")
        after = CreditTransaction.objects.filter(
            transaction_type=CreditTransaction.Type.ISSUANCE,
        ).count()
        self.assertEqual(after, before, "缺少 key 不应创建交易")
