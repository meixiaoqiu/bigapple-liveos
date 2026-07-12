from __future__ import annotations

from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.models import (
    PartnerApplication,
    PlanNode,
    PlanRequirement,
    PlanRevision,
    ProjectPlan,
    Resource,
    SupplierQuote,
)
from core.resource_matching import resource_gap_rows


class ResourceMatchingTests(TestCase):
    def setUp(self) -> None:
        now = timezone.now()
        self.resource = Resource.objects.create(
            resource_id="res-cement",
            name="水泥",
            resource_type=Resource.ResourceType.MATERIAL,
            unit=Resource.Unit.BAG,
            current_stock=Decimal("20"),
            daily_consumption_estimate=Decimal("0"),
            replenishment_method=Resource.ReplenishmentMethod.PURCHASE,
            loss_rate=Decimal("0.00000"),
            warning_threshold=Decimal("10"),
            shortage_impact={"construction_delay": True},
            updated_at=now,
            rule_version="ruleset-v0.1.0",
        )
        plan = ProjectPlan.objects.create(
            plan_id="plan-resource-match",
            name="资源匹配测试计划",
            status=ProjectPlan.Status.ACTIVE,
            created_at=now,
        )
        revision = PlanRevision.objects.create(
            revision_id="revision-resource-match",
            plan=plan,
            revision_code="v0.1.0",
            status=PlanRevision.Status.PUBLISHED,
            title="资源匹配测试版本",
            change_summary="测试资源缺口计算。",
            created_at=now,
            published_at=now,
        )
        node = PlanNode.objects.create(
            node_id="node-resource-match",
            revision=revision,
            code="B1",
            title="建设临时公共食堂",
            sequence=1,
            node_type=PlanNode.NodeType.WORK_PACKAGE,
            planned_duration_days=3,
            required_people_min=1,
            required_people_max=3,
            required_person_days=Decimal("3"),
            created_at=now,
        )
        self.requirement = PlanRequirement.objects.create(
            requirement_id="req-cement",
            node=node,
            resource=self.resource,
            requirement_type=PlanRequirement.RequirementType.MATERIAL,
            name="水泥",
            quantity=Decimal("100"),
            unit="袋",
            unit_cost=Decimal("22"),
            total_cost_estimate=Decimal("2200"),
            notes="临时食堂基础材料。",
        )
        self.partner_a = PartnerApplication.objects.create(
            application_id="partner-cement-a",
            organization_name="甲方建材供应商",
            contact_name="张三",
            contact="13800000001",
            service_domains=["建材供应"],
            quote_summary="22 元/袋，两天送达。",
            status=PartnerApplication.Status.QUALIFIED,
            submitted_at=now,
        )
        self.partner_b = PartnerApplication.objects.create(
            application_id="partner-cement-b",
            organization_name="乙方建材供应商",
            contact_name="李四",
            contact="13800000002",
            service_domains=["建材供应"],
            quote_summary="19 元/袋，七天送达。",
            status=PartnerApplication.Status.QUALIFIED,
            submitted_at=now,
        )

    def test_resource_gap_matches_plan_requirement_stock_and_best_quote(self) -> None:
        SupplierQuote.objects.create(
            quote_id="quote-cement-a",
            partner_application=self.partner_a,
            resource=self.resource,
            unit_price=Decimal("22"),
            available_quantity=Decimal("100"),
            lead_time_days=2,
            quality_grade=SupplierQuote.QualityGrade.STANDARD,
        )
        SupplierQuote.objects.create(
            quote_id="quote-cement-b",
            partner_application=self.partner_b,
            resource=self.resource,
            unit_price=Decimal("19"),
            available_quantity=Decimal("80"),
            lead_time_days=7,
            quality_grade=SupplierQuote.QualityGrade.LOW_RISK,
        )

        rows = resource_gap_rows()

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.resource, self.resource)
        self.assertEqual(row.required_quantity, Decimal("100.000"))
        self.assertEqual(row.current_stock, Decimal("20.000"))
        self.assertEqual(row.shortage_quantity, Decimal("80.000"))
        self.assertEqual(row.active_quote_count, 2)
        self.assertEqual(row.quoted_available_quantity, Decimal("180.000"))
        self.assertEqual(row.coverage_status, "quoted_cover")
        self.assertEqual(row.best_quote.quote_id, "quote-cement-b")
        self.assertEqual(row.estimated_best_cost, Decimal("1520.00000"))

    def test_unqualified_partner_quote_does_not_cover_gap(self) -> None:
        self.partner_a.status = PartnerApplication.Status.REJECTED
        self.partner_a.save(update_fields=["status"])
        SupplierQuote.objects.create(
            quote_id="quote-cement-rejected",
            partner_application=self.partner_a,
            resource=self.resource,
            unit_price=Decimal("12"),
            available_quantity=Decimal("100"),
            lead_time_days=1,
            quality_grade=SupplierQuote.QualityGrade.RISKY,
        )

        row = resource_gap_rows()[0]

        self.assertEqual(row.coverage_status, "no_quote")
        self.assertEqual(row.active_quote_count, 0)
        self.assertIsNone(row.best_quote)
