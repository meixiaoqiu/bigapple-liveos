from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.utils import timezone

from core.credit_services import ensure_system_accounts, issue_credits_to_pool, lock_task_credit_budget
from core.member_roles import ROLE_CONTRIBUTOR
from core.models import CapacityAssessment, Dispute, Event, LedgerEntry, Member, Resource, Task
from core.tests.helpers import create_governance_admin_member, create_member, login_as_member


def actor(actor_id: str = "member-admin-0001") -> dict[str, str]:
    return {
        "actor_id": actor_id,
        "actor_type": "human_member",
        "display_name": "开荒队治理成员",
    }


class ApiWorkflowTests(TestCase):
    """覆盖成员通过 Live OS API 完成任务的第一条闭环。"""

    api_base = "/api/v0.1"

    def setUp(self) -> None:
        self.client = Client()
        now = timezone.now()
        self.member = create_member(
            member_no="mem-0001",
            role_name=ROLE_CONTRIBUTOR,
            status=Member.Status.ADMITTED,
            batch_id="batch-opening",
            joined_simulation_day=1,
            credit_floor=-300,
            profile={"satisfaction": 64, "fatigue": 18},
            created_at=now,
        )
        self.reviewer = create_governance_admin_member(
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
            standard_hours=Decimal("3.50"),
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
            current_formal_members=100,
            current_candidate_members=900,
            maximum_admissible_members=130,
            recommended_new_members=20,
            bottlenecks=["canteen"],
            risk_indicators={
                "beds_available": 42,
                "canteen_load": 82,
                "task_gap": 18,
                "average_satisfaction": 61,
                "average_fatigue": 67,
                "open_disputes": 0,
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
        self.assertEqual(summary["formal_members"], 1)
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
        dispute_status, dispute_payload = self.post_json(
            self.api("/disputes"),
            {
                "claimant_member_no": "member-does-not-exist",
                "dispute_type": Dispute.DisputeType.TASK_REVIEW,
                "facts": "枚举防护测试。",
            },
        )

        self.assertEqual(existing_status, 403)
        self.assertEqual(missing_status, 403)
        self.assertEqual(dispute_status, 403)
        self.assertEqual(existing_payload["code"], "permission_denied")
        self.assertEqual(missing_payload["code"], "permission_denied")
        self.assertEqual(dispute_payload["code"], "permission_denied")

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

    def test_create_dispute_api_server_manages_identity_and_status(self) -> None:
        login_as_member(self.client, self.member)

        status, payload = self.post_json(
            self.api("/disputes"),
            {
                "dispute_id": "dispute-forged",
                "claimant_member_no": self.member.member_no,
                "dispute_type": Dispute.DisputeType.TASK_REVIEW,
                "status": Dispute.Status.RESOLVED,
                "facts": "伪造状态测试。",
                "handler": actor(),
                "reviewer": actor(),
                "appeal_path": "forged",
                "submitted_at": timezone.now().isoformat(),
            },
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["code"], "invalid_request")

        status, payload = self.post_json(
            self.api("/disputes"),
            {
                "claimant_member_no": self.member.member_no,
                "dispute_type": Dispute.DisputeType.TASK_REVIEW,
                "related_task_id": self.task.task_id,
                "facts": "午餐任务验收标准需要复核。",
                "evidence_refs": ["event-0001"],
            },
        )
        self.assertEqual(status, 201)
        self.assertNotEqual(payload["dispute_id"], "dispute-forged")
        self.assertEqual(payload["status"], Dispute.Status.SUBMITTED)
        self.assertEqual(payload["claimant_member_no"], self.member.member_no)
        self.assertNotIn("handler", payload)
        self.assertNotIn("reviewer", payload)

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
            related_dispute_id="dispute-private-0001",
            occurred_at=now,
            generated_by=Event.GeneratedBy.LIVE_OS,
            visibility=Event.Visibility.PUBLIC,
            payload={"private_note": "should not be public"},
        )
        Event.objects.create(
            event_id="event-internal-0001",
            event_type=Event.EventType.DISPUTE,
            simulation_day=1,
            severity=Event.Severity.WARNING,
            title="内部申诉事件",
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
        self.assertNotIn("related_dispute_id", public_event)
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
            standard_hours=Decimal("2.50"),
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
            standard_hours=Decimal("2.00"),
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
        Dispute.objects.create(
            dispute_id="dispute-0001",
            dispute_type=Dispute.DisputeType.TASK_REVIEW,
            status=Dispute.Status.IN_REVIEW,
            claimant_member=self.member,
            related_task=self.task,
            facts="成员申请复核任务验收标准。",
            evidence_refs=[event.event_id],
            handler=actor(),
            reviewer={},
            resolution="",
            appeal_path="standard-review-appeal",
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
        self.assertEqual(payload["available_tasks"][0]["task_id"], "task-0002")
        self.assertEqual(payload["active_tasks"][0]["task_id"], self.task.task_id)
        self.assertEqual(payload["task_history"][0]["task_id"], history_task.task_id)
        self.assertIn("submitted_at", payload["task_history"][0])
        self.assertIn("reviewed_at", payload["task_history"][0])
        self.assertEqual(payload["recent_ledger_entries"][0]["ledger_entry_id"], "ledger-0001")
        self.assertEqual(payload["recent_events"][0]["event_id"], event.event_id)
        self.assertEqual(payload["open_disputes"][0]["dispute_id"], "dispute-0001")
        self.assertEqual(payload["dispute_history"][0]["dispute_id"], "dispute-0001")
        self.assertNotIn("reviewer", payload["dispute_history"][0])
        self.assertEqual(payload["resource_warnings"][0]["resource_id"], "res-medicine")
        self.assertEqual(payload["task_counts"][Task.Status.OPEN], 1)
        self.assertEqual(payload["task_counts"][Task.Status.CLAIMED], 1)
        self.assertEqual(payload["task_counts"][Task.Status.ACCEPTED], 1)
        self.assertIn("submit_labor", payload["next_actions"])
        self.assertIn("claim_task", payload["next_actions"])
        self.assertIn("review_dispute", payload["next_actions"])
        self.assertIn("check_resource_warning", payload["next_actions"])


class CreditTransferApiTests(TestCase):
    """POST /api/v0.1/members/<no>/credit-transfers"""

    api_base = "/api/v0.1"

    def setUp(self):
        from core.credit_services import ensure_system_accounts, get_or_create_member_credit_account
        ensure_system_accounts()
        self.member_a = create_member("transfer-api-a")
        self.member_b = create_member("transfer-api-b")
        get_or_create_member_credit_account(self.member_a)
        get_or_create_member_credit_account(self.member_b)
        # Give A some credits
        from core.credit_services import post_credit_transaction
        from core.models import CreditAccount, CreditTransaction
        issuance = CreditAccount.objects.get(account_type=CreditAccount.Type.ISSUANCE_POOL)
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
        """治理成员不能通过成员转账 API 代别人转出。"""
        from core.tests.helpers import create_governance_admin_member
        gov = create_governance_admin_member("gov-transfer-hack")
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
        self.member = create_member("ro-api-member")
        self.governor = create_governance_admin_member("gov-ro-api")
        get_or_create_member_credit_account(self.member)
        # Give member enough credits
        from core.models import CreditAccount, CreditTransaction
        issuance = CreditAccount.objects.get(account_type=CreditAccount.Type.ISSUANCE_POOL)
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
        zero_member = create_member("ro-api-zero")
        from core.credit_services import get_or_create_member_credit_account
        get_or_create_member_credit_account(zero_member)
        login_as_member(self.client, zero_member)
        resp = self.client.post(
            self.api(f"/members/{zero_member.member_no}/redemption-orders"),
            {"credit_amount": 10, "item_type": "meal", "title": "x"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

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
            self.api(f"/redemption-orders/{order_id}/dispute"),
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
        self.governor = create_governance_admin_member("gov-settle-api")
        self.operator = create_member("settle-op-api")
        self.unrelated = create_member("settle-unrel-api")
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


class CreditTransferPageTest(TestCase):
    """Workspace credit-transfer page UI tests."""

    def setUp(self):
        from core.credit_services import ensure_system_accounts, get_or_create_member_credit_account, post_credit_transaction
        from core.models import CreditAccount, CreditTransaction
        from core.member_roles import ROLE_FORMAL_MEMBER
        ensure_system_accounts()
        self.member_a = create_member("transfer-page-a", role_name=ROLE_FORMAL_MEMBER)
        self.member_b = create_member("transfer-page-b", role_name=ROLE_FORMAL_MEMBER)
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
        from core.member_roles import ROLE_FORMAL_MEMBER
        ensure_system_accounts()
        self.member = create_member("redemption-page-m", role_name=ROLE_FORMAL_MEMBER)
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
            {"dispute": order.order_id, "dispute_reason": "wrong"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "已提交申诉")
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

    def test_workspace_page_shows_credit_stats(self):
        """Workspace index shows current/available/lifetime credit stats for formal member."""
        login_as_member(self.client, self.member)
        resp = self.client.get("/workspace/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "当前积分")
        self.assertContains(resp, "可用积分")
        self.assertContains(resp, "历史贡献")
