"""Tests for workspace work-item dashboard."""

from decimal import Decimal
from datetime import timedelta
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from core.credential_services import ensure_builtin_credential_templates
from core.member_roles import ROLE_COVENANTER
from core.models import (
    ApprovalProposal,
    ApprovalDecision,
    Dispute,
    Resource,
    SupplierQuote,
    Task,
)
from core.procurement_services import submit_resource_offer
from core.proposal_services import (
    approve_proposal,
    create_approval_proposal,
    execute_proposal,
)
from core.tests.helpers import (
    create_administrator_member,
    create_member,
    login_as_member,
)

from workspace.work_item_context import build_member_work_items

FIXED_WORLD_SETTINGS = {"WORLD_ROUTER_FORCE_ID": "wt-wi-test"}


@override_settings(**FIXED_WORLD_SETTINGS)
class WorkItemContextTests(TestCase):
    """Unit tests for build_member_work_items."""

    def setUp(self):
        ensure_builtin_credential_templates()
        now = timezone.now()
        self.resource = Resource.objects.create(
            resource_id="res-wi-grain",
            resource_type=Resource.ResourceType.GRAIN,
            unit=Resource.Unit.KG,
            current_stock=Decimal("100"),
            daily_consumption_estimate=Decimal("0"),
            warning_threshold=Decimal("10"),
            loss_rate=Decimal("0"),
            replenishment_method=Resource.ReplenishmentMethod.PURCHASE,
            updated_at=now,
            rule_version="v1",
        )
        self.governor = create_administrator_member("administrator-wi-1")
        self.supplier = create_member("sup-wi-1", role_name=ROLE_COVENANTER)
        self.regular = create_member("reg-wi-1", role_name=ROLE_COVENANTER)

    def test_governance_sees_pending_approval_proposal(self):
        create_approval_proposal(
            proposal_type=ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE,
            dedupe_key="test:wi:1",
            title="Test approval",
            submitted_by=self.governor,
            approval_tier=ApprovalProposal.Tier.SINGLE,
        )
        items = build_member_work_items(self.governor)
        self.assertGreater(len(items["approval_pending"]), 0)

    def test_governance_sees_approved_execute_item(self):
        p = create_approval_proposal(
            proposal_type=ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE,
            dedupe_key="test:wi:2",
            title="Test execute",
            submitted_by=self.governor,
            approval_tier=ApprovalProposal.Tier.SINGLE,
        )
        approve_proposal(proposal=p, approved_by=self.governor, role="governance")
        items = build_member_work_items(self.governor)
        self.assertGreater(len(items["execute_pending"]), 0)

    def test_accepted_quote_ready_shows_receipt_item(self):
        quote = submit_resource_offer(
            resource=self.resource,
            submitted_by=self.supplier,
            offer_type=SupplierQuote.OfferType.QUOTE,
            available_quantity=Decimal("10"),
            unit_price=Decimal("3"),
        )
        p = ApprovalProposal.objects.get(
            proposal_type=ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE,
            target_type="supplier_quote",
            target_id=quote.quote_id,
        )
        approve_proposal(proposal=p, approved_by=self.governor, role="governance")
        execute_proposal(proposal=p, actor=self.governor)
        items = build_member_work_items(self.governor)
        self.assertGreater(len(items["receipt_pending"]), 0)

    def test_regular_member_sees_no_governance_items(self):
        create_approval_proposal(
            proposal_type=ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE,
            dedupe_key="test:wi:3",
            title="Hidden",
            submitted_by=self.governor,
            approval_tier=ApprovalProposal.Tier.SINGLE,
        )
        items = build_member_work_items(self.regular)
        self.assertEqual(items["total_pending"], 0)

    def test_work_items_no_metadata_leak(self):
        create_approval_proposal(
            proposal_type=ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE,
            dedupe_key="test:wi:4",
            title="Test",
            submitted_by=self.governor,
        )
        items = build_member_work_items(self.governor)
        for item in items["approval_pending"]:
            self.assertNotIn("metadata", str(item))
            self.assertNotIn("operator", str(item))

    def test_member_task_and_dispute_are_projected_by_action_relation(self):
        now = timezone.now()
        task = Task.objects.create(
            task_id="task-matter-active", title="整理事务投影", task_type=Task.TaskType.ADMINISTRATION,
            status=Task.Status.IN_PROGRESS, standard_minutes=30, base_points=5,
            role_coefficient=Decimal("1"), can_be_delayed=True, requires_review=True,
            failure_consequence=Task.FailureConsequence.LOW, assignee_member=self.regular,
            rule_version="v1", created_at=now,
        )
        dispute = Dispute.objects.create(
            dispute_id="dispute-matter-waiting", dispute_type=Dispute.DisputeType.TASK_REVIEW,
            status=Dispute.Status.IN_REVIEW, claimant_member=self.regular, related_task=task,
            facts="等待任务验收复核。", handler={}, reviewer={},
            appeal_path="standard-review-appeal", submitted_at=now,
        )

        matters = build_member_work_items(self.regular)["matters"]

        task_item = next(item for item in matters["action_required"] if item["id"] == f"task:{task.task_id}")
        dispute_item = next(item for item in matters["waiting"] if item["id"] == f"dispute:{dispute.dispute_id}")
        self.assertEqual(task_item["responsible"], self.regular.member_no)
        self.assertEqual(task_item["action_label"], "提交劳动")
        self.assertEqual(dispute_item["current_handler"], "申诉处理角色")
        for item in (task_item, dispute_item):
            self.assertTrue(item["status"])
            self.assertTrue(item["updated_at"])
            self.assertTrue(item["target_url"])

    def test_ended_task_is_recent_and_open_task_is_not_a_matter(self):
        now = timezone.now()
        Task.objects.create(
            task_id="task-matter-open", title="尚未领取", task_type=Task.TaskType.DUTY,
            status=Task.Status.OPEN, standard_minutes=30, base_points=5,
            role_coefficient=Decimal("1"), can_be_delayed=True, requires_review=True,
            failure_consequence=Task.FailureConsequence.LOW, rule_version="v1", created_at=now,
        )
        ended = Task.objects.create(
            task_id="task-matter-ended", title="已经结束", task_type=Task.TaskType.DUTY,
            status=Task.Status.ACCEPTED, standard_minutes=30, base_points=5,
            role_coefficient=Decimal("1"), can_be_delayed=True, requires_review=True,
            failure_consequence=Task.FailureConsequence.LOW, assignee_member=self.regular,
            rule_version="v1", created_at=now, reviewed_at=now,
        )

        matters = build_member_work_items(self.regular)["matters"]
        all_ids = {item["id"] for group in matters.values() if isinstance(group, list) for item in group}
        self.assertIn(f"task:{ended.task_id}", all_ids)
        self.assertNotIn("task:task-matter-open", all_ids)
        ended_matter = next(
            item for item in matters["recently_ended"] if item["id"] == f"task:{ended.task_id}"
        )
        self.assertEqual(ended_matter["target_url"], f"/workspace/tasks/{ended.task_id}/")

    def test_governance_proposal_and_procurement_use_unified_shape(self):
        proposal = create_approval_proposal(
            proposal_type=ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE,
            dedupe_key="test:matter:proposal", title="统一事项审批",
            submitted_by=self.governor, approval_tier=ApprovalProposal.Tier.SINGLE,
        )
        quote = submit_resource_offer(
            resource=self.resource, submitted_by=self.supplier,
            offer_type=SupplierQuote.OfferType.QUOTE,
            available_quantity=Decimal("10"), unit_price=Decimal("3"),
        )
        quote_proposal = ApprovalProposal.objects.get(
            proposal_type=ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE,
            target_type="supplier_quote", target_id=quote.quote_id,
        )
        approve_proposal(proposal=quote_proposal, approved_by=self.governor, role="governance")
        execute_proposal(proposal=quote_proposal, actor=self.governor)

        matters = build_member_work_items(self.governor)["matters"]["action_required"]
        ids = {item["id"] for item in matters}
        self.assertIn(f"approval-proposal:{proposal.proposal_id}", ids)
        self.assertIn(f"supplier-quote:{quote.quote_id}", ids)
        proposal_item = next(item for item in matters if item["id"] == f"approval-proposal:{proposal.proposal_id}")
        self.assertEqual(proposal_item["current_handler"], "提案审批角色")
        self.assertNotEqual(proposal_item["current_handler"], self.governor.member_no)
        for item in matters:
            self.assertNotIn("metadata", item)
            self.assertNotIn("operator", item)

    def test_actionable_proposal_after_one_hundred_ineligible_candidates_is_not_lost(self):
        eligible = None
        for index in range(101):
            proposal = create_approval_proposal(
                proposal_type=ApprovalProposal.ProposalType.INVENTORY_ADJUSTMENT,
                dedupe_key=f"test:matter:limit:proposal:{index}",
                title="第 101 条但可处理" if index == 0 else f"已处理 {index}",
                submitted_by=self.governor,
            )
            if index == 0:
                eligible = proposal
            else:
                ApprovalDecision.objects.create(
                    approval_id=f"approval-limit-{index}", proposal=proposal,
                    approver=self.governor, role="governance",
                    decision=ApprovalDecision.Decision.REJECTED,
                )

        matters = build_member_work_items(self.governor)["matters"]["action_required"]

        self.assertIn(f"approval-proposal:{eligible.proposal_id}", {item["id"] for item in matters})

    def test_ready_quote_after_one_hundred_unready_candidates_is_not_lost(self):
        eligible = None
        for index in range(101):
            quote = SupplierQuote.objects.create(
                quote_id=f"quote-limit-{index:02d}", resource=self.resource,
                submitted_by=self.supplier, decision_status=SupplierQuote.DecisionStatus.ACCEPTED,
                receipt_status=SupplierQuote.ReceiptStatus.PENDING,
                notes="ready" if index == 0 else "not-ready",
            )
            if index == 0:
                eligible = quote
            else:
                ApprovalProposal.objects.create(
                    proposal_id=f"proposal-quote-limit-{index}",
                    proposal_type=ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE,
                    title=f"未执行报价 {index}", dedupe_key=f"quote-limit:{index}",
                    target_type="supplier_quote", target_id=quote.quote_id,
                    submitted_by=self.governor,
                )

        items = build_member_work_items(self.governor)

        self.assertTrue(any(eligible.quote_id in item["summary"] for item in items["receipt_pending"]))

    def test_actionable_sources_load_only_twenty_but_keep_exact_count(self):
        now = timezone.now()
        for index in range(25):
            ApprovalProposal.objects.create(
                proposal_id=f"proposal-source-limit-{index}",
                proposal_type=ApprovalProposal.ProposalType.INVENTORY_ADJUSTMENT,
                title=f"来源限量 {index}", dedupe_key=f"source-limit:{index}",
                submitted_by=self.governor,
                submitted_at=now + timedelta(seconds=index), created_at=now,
            )

        with CaptureQueriesContext(connection) as queries:
            items = build_member_work_items(self.governor)

        self.assertEqual(len(items["approval_pending"]), 20)
        self.assertEqual(items["approval_pending_count"], 25)
        self.assertEqual(items["total_pending"], 25)
        self.assertTrue(any(
            'from "core_approval_proposal"' in query["sql"].lower()
            and "exists" in query["sql"].lower()
            and "limit 20" in query["sql"].lower()
            for query in queries.captured_queries
        ))

    def test_receipt_requires_latest_acceptance_proposal_to_be_executed(self):
        now = timezone.now()
        quote = SupplierQuote.objects.create(
            quote_id="quote-latest-acceptance", resource=self.resource,
            submitted_by=self.supplier,
            decision_status=SupplierQuote.DecisionStatus.ACCEPTED,
            receipt_status=SupplierQuote.ReceiptStatus.PENDING,
        )
        ApprovalProposal.objects.create(
            proposal_id="proposal-acceptance-old-executed",
            proposal_type=ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE,
            title="旧采纳提案", dedupe_key="latest-acceptance:old",
            target_type="supplier_quote", target_id=quote.quote_id,
            submitted_by=self.governor, status=ApprovalProposal.Status.EXECUTED,
            submitted_at=now - timedelta(hours=1), created_at=now - timedelta(hours=1),
        )
        ApprovalProposal.objects.create(
            proposal_id="proposal-acceptance-new-submitted",
            proposal_type=ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE,
            title="新采纳提案", dedupe_key="latest-acceptance:new",
            target_type="supplier_quote", target_id=quote.quote_id,
            submitted_by=self.governor, status=ApprovalProposal.Status.SUBMITTED,
            submitted_at=now, created_at=now,
        )

        items = build_member_work_items(self.governor)

        self.assertFalse(any(
            quote.quote_id in item["summary"] for item in items["receipt_pending"]
        ))
        self.assertNotIn(
            f"supplier-quote:{quote.quote_id}",
            {item["id"] for item in items["matters"]["action_required"]},
        )

    def test_dispute_projection_does_not_lazy_load_claimant_members(self):
        now = timezone.now()
        for index in range(10):
            Dispute.objects.create(
                dispute_id=f"dispute-query-{index}", dispute_type=Dispute.DisputeType.MEMBER_CONFLICT,
                status=Dispute.Status.IN_REVIEW, claimant_member=self.regular,
                respondent_member=self.supplier, facts=f"查询测试 {index}",
                handler={}, reviewer={}, appeal_path="standard-review-appeal", submitted_at=now,
            )

        with CaptureQueriesContext(connection) as queries:
            build_member_work_items(self.regular)

        lazy_member_queries = []
        for query in queries.captured_queries:
            sql = query["sql"].lower()
            if 'from "core_member"' in sql and " join " not in sql:
                lazy_member_queries.append(query["sql"])
        self.assertEqual(lazy_member_queries, [])

    def test_sources_are_combined_before_global_display_limit(self):
        now = timezone.now()
        old_time = now - timedelta(days=1)
        for index in range(10):
            Task.objects.create(
                task_id=f"task-cross-source-{index}", title=f"旧任务 {index}",
                task_type=Task.TaskType.DUTY, status=Task.Status.IN_PROGRESS,
                standard_minutes=30, base_points=0, role_coefficient=Decimal("1"),
                can_be_delayed=True, requires_review=True,
                failure_consequence=Task.FailureConsequence.LOW,
                assignee_member=self.governor, rule_version="v1", created_at=old_time,
            )
            ApprovalProposal.objects.create(
                proposal_id=f"proposal-cross-source-{index}",
                proposal_type=ApprovalProposal.ProposalType.INVENTORY_ADJUSTMENT,
                title=f"旧提案 {index}", dedupe_key=f"cross-source:{index}",
                submitted_by=self.governor, submitted_at=old_time, created_at=old_time,
            )
        quotes = [
            SupplierQuote.objects.create(
                quote_id=f"quote-cross-source-{index}", resource=self.resource,
                submitted_by=self.supplier, decision_status=SupplierQuote.DecisionStatus.ACCEPTED,
                receipt_status=SupplierQuote.ReceiptStatus.PENDING, created_at=now + timedelta(seconds=index),
            )
            for index in range(2)
        ]

        matters = build_member_work_items(self.governor)["matters"]["action_required"]
        ids = {item["id"] for item in matters}

        for quote in quotes:
            self.assertIn(f"supplier-quote:{quote.quote_id}", ids)
        self.assertEqual(len(matters), 20)

    def test_governance_queries_filter_in_sql_without_per_item_decision_queries(self):
        now = timezone.now()
        for index in range(30):
            ApprovalProposal.objects.create(
                proposal_id=f"proposal-query-budget-{index}",
                proposal_type=ApprovalProposal.ProposalType.INVENTORY_ADJUSTMENT,
                title=f"查询预算 {index}", dedupe_key=f"query-budget:{index}",
                submitted_by=self.governor, submitted_at=now, created_at=now,
            )

        with CaptureQueriesContext(connection) as queries:
            build_member_work_items(self.governor)

        sql_statements = [query["sql"].lower() for query in queries.captured_queries]
        standalone_decision_queries = [
            sql for sql in sql_statements
            if 'from "core_approval_decision"' in sql
            and 'from "core_approval_proposal"' not in sql
        ]
        filtered_proposal_queries = [
            sql for sql in sql_statements
            if 'from "core_approval_proposal"' in sql
            and 'status' in sql
            and "exists" in sql
        ]
        self.assertEqual(standalone_decision_queries, [])
        self.assertTrue(filtered_proposal_queries)

    def test_execute_pending_keeps_resolved_at_order(self):
        now = timezone.now()
        recently_resolved = ApprovalProposal.objects.create(
            proposal_id="proposal-resolved-recent", proposal_type=ApprovalProposal.ProposalType.INVENTORY_ADJUSTMENT,
            title="最近批准", dedupe_key="resolved-order:recent", submitted_by=self.governor,
            status=ApprovalProposal.Status.APPROVED,
            submitted_at=now - timedelta(days=10), resolved_at=now,
            created_at=now - timedelta(days=10),
        )
        ApprovalProposal.objects.create(
            proposal_id="proposal-submitted-recent", proposal_type=ApprovalProposal.ProposalType.INVENTORY_ADJUSTMENT,
            title="较早批准", dedupe_key="resolved-order:older", submitted_by=self.governor,
            status=ApprovalProposal.Status.APPROVED,
            submitted_at=now, resolved_at=now - timedelta(days=1), created_at=now,
        )

        items = build_member_work_items(self.governor)["execute_pending"]

        self.assertEqual(items[0]["title"], recently_resolved.title)


@override_settings(**FIXED_WORLD_SETTINGS)
class WorkspaceDashboardTests(TestCase):
    """Integration tests for /workspace/ dashboard."""

    def setUp(self):
        ensure_builtin_credential_templates()
        now = timezone.now()
        self.resource = Resource.objects.create(
            resource_id="res-ws-home",
            resource_type=Resource.ResourceType.GRAIN,
            unit=Resource.Unit.KG,
            current_stock=Decimal("100"),
            daily_consumption_estimate=Decimal("0"),
            warning_threshold=Decimal("10"),
            loss_rate=Decimal("0"),
            replenishment_method=Resource.ReplenishmentMethod.PURCHASE,
            updated_at=now,
            rule_version="v1",
        )
        self.governor = create_administrator_member("administrator-home-1")

    def test_dashboard_shows_pending_items_when_exist(self):
        login_as_member(self.client, self.governor)
        create_approval_proposal(
            proposal_type=ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE,
            dedupe_key="test:home:1",
            title="Pending approval",
            submitted_by=self.governor,
            approval_tier=ApprovalProposal.Tier.SINGLE,
        )
        response = self.client.get("/workspace/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "待处理事项")
        self.assertContains(response, "我的事务")
        self.assertContains(response, "需要我处理")

    def test_dashboard_ok_without_pending_items(self):
        login_as_member(self.client, self.governor)
        response = self.client.get("/workspace/")
        self.assertEqual(response.status_code, 200)

    def test_dashboard_links_point_to_pages(self):
        login_as_member(self.client, self.governor)
        create_approval_proposal(
            proposal_type=ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE,
            dedupe_key="test:home:2",
            title="Link test",
            submitted_by=self.governor,
        )
        response = self.client.get("/workspace/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "待处理事项")

    def test_no_metadata_on_homepage(self):
        login_as_member(self.client, self.governor)
        response = self.client.get("/workspace/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn("metadata", content)

    def test_new_matter_view_precedes_and_preserves_old_modules(self):
        login_as_member(self.client, self.governor)
        create_approval_proposal(
            proposal_type=ApprovalProposal.ProposalType.PROCUREMENT_ACCEPTANCE,
            dedupe_key="test:home:preserve", title="迁移期对照",
            submitted_by=self.governor,
        )
        response = self.client.get("/workspace/")
        content = response.content.decode()
        old_modules = [
            "待处理事项", "近期积分流水", "相关事件", "申诉状态",
        ]
        matter_position = content.index("我的事务")
        for title in old_modules:
            self.assertIn(title, content)
            self.assertLess(matter_position, content.index(title))
        self.assertNotIn("下一步动作", content)
        self.assertNotIn("个人任务历史", content)
        self.assertNotIn("资源预警", content)
        self.assertNotIn("<h2 class=\"card-title\">当前任务</h2>", content)
        self.assertNotIn("<h2 class=\"card-title\">可领取任务</h2>", content)
        self.assertIn("任务中心", content)
        self.assertContains(response, "迁移期说明")
