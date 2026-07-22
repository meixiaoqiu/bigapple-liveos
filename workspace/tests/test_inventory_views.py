"""Tests for workspace inventory maintenance views."""

from __future__ import annotations

from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone

from core.member_roles import ROLE_FORMAL_MEMBER
from core.models import Member, Resource, ResourceTransaction
from core.tests.helpers import create_governance_admin_member, create_member, login_as_member


FIXED_WORLD_SETTINGS = dict(
    SITE_FIXED_WORLD=True,
    SITE_WORLD_ID="simulation0001",
    SITE_WORLD_TYPE="simulation",
    SITE_WORLD_DATABASE_ALIAS="default",
    SITE_WORLD_DATABASE_NAME="test",
)


@override_settings(**FIXED_WORLD_SETTINGS)
class InventoryPermissionTests(TestCase):
    """普通成员不能访问库存维护入口。"""

    def setUp(self) -> None:
        now = timezone.now()
        self.member = create_member(
            "mem-inv-001",
            role_name=ROLE_FORMAL_MEMBER,
            status=Member.Status.ADMITTED,
            batch_id="batch-op",
            joined_simulation_day=1,
            credit_floor=-100,
            created_at=now,
        )
        login_as_member(self.client, self.member)
        Resource.objects.create(
            resource_id="res-inv-001",
            resource_type=Resource.ResourceType.GRAIN,
            unit=Resource.Unit.KG,
            current_stock=Decimal("50"),
            daily_consumption_estimate=Decimal("0"),
            warning_threshold=Decimal("20"),
            loss_rate=Decimal("0"),
            replenishment_method=Resource.ReplenishmentMethod.PURCHASE,
            updated_at=now,
            rule_version="v1",
        )

    def test_regular_member_cannot_access_inventory_list(self):
        response = self.client.get("/workspace/inventory/")
        self.assertEqual(response.status_code, 403)


    def test_regular_member_cannot_post_adjustment(self):
        response = self.client.post("/workspace/inventory/res-inv-001/adjust/", {
            "delta": "100", "reason": "test", "replenishment_method": "purchase",
        })
        self.assertEqual(response.status_code, 403)

    def test_regular_member_cannot_access_new_resource_page(self):
        response = self.client.get("/workspace/inventory/new/")
        self.assertEqual(response.status_code, 403)

    def test_regular_member_cannot_post_new_resource(self):
        response = self.client.post("/workspace/inventory/new/", {
            "resource_id": "res-test-001", "resource_type": "grain", "unit": "kg",
            "replenishment_method": "purchase", "rule_version": "v1",
        })
        self.assertEqual(response.status_code, 403)

    def test_regular_member_cannot_access_edit_page(self):
        response = self.client.get("/workspace/inventory/res-inv-001/edit/")
        self.assertEqual(response.status_code, 403)

    def test_regular_member_cannot_post_edit(self):
        response = self.client.post("/workspace/inventory/res-inv-001/edit/", {
            "resource_type": "grain", "unit": "kg",
            "replenishment_method": "purchase", "rule_version": "v1",
        })
        self.assertEqual(response.status_code, 403)



@override_settings(**FIXED_WORLD_SETTINGS)
class InventoryGovernanceTests(TestCase):
    """治理角色可以访问库存维护并调整库存。"""

    def setUp(self) -> None:
        now = timezone.now()
        self.member = create_governance_admin_member("mem-gov-001")
        login_as_member(self.client, self.member)
        self.resource = Resource.objects.create(
            resource_id="res-gov-001",
            resource_type=Resource.ResourceType.GRAIN,
            unit=Resource.Unit.KG,
            current_stock=Decimal("50"),
            daily_consumption_estimate=Decimal("0"),
            warning_threshold=Decimal("20"),
            loss_rate=Decimal("0"),
            replenishment_method=Resource.ReplenishmentMethod.PURCHASE,
            updated_at=now,
            rule_version="v1",
        )

    def test_governance_user_can_access_inventory_list(self):
        response = self.client.get("/workspace/inventory/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "资源库存维护")
        self.assertContains(response, "res-gov-001")

    def test_inventory_list_shows_low_stock_warning(self):
        Resource.objects.create(
            resource_id="res-gov-002",
            resource_type=Resource.ResourceType.WATER,
            unit=Resource.Unit.LITER,
            current_stock=Decimal("5"),
            daily_consumption_estimate=Decimal("0"),
            warning_threshold=Decimal("10"),
            loss_rate=Decimal("0"),
            replenishment_method=Resource.ReplenishmentMethod.PURCHASE,
            updated_at=timezone.now(),
            rule_version="v1",
        )
        response = self.client.get("/workspace/inventory/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "低库存预警")
        self.assertContains(response, "res-gov-002")

    def test_adjust_page_shows_resource_info(self):
        response = self.client.get("/workspace/inventory/res-gov-001/adjust/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "库存调整")
        self.assertContains(response, "res-gov-001")

    def test_adjust_creates_resource_transaction(self):
        response = self.client.post(
            "/workspace/inventory/res-gov-001/adjust/",
            {"delta": "100", "reason": "采购入库", "replenishment_method": "purchase"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

        self.resource.refresh_from_db()
        self.assertEqual(self.resource.current_stock, Decimal("150"))

        txn = ResourceTransaction.objects.filter(resource=self.resource).first()
        self.assertIsNotNone(txn)
        self.assertEqual(txn.quantity_delta, Decimal("100"))
        self.assertEqual(txn.reason, "采购入库")

    def test_negative_stock_rejected_by_service(self):
        response = self.client.post(
            "/workspace/inventory/res-gov-001/adjust/",
            {"delta": "-100", "reason": "过度消耗", "replenishment_method": "purchase"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("不能调整", response.content.decode())

        self.resource.refresh_from_db()
        self.assertEqual(self.resource.current_stock, Decimal("50"))

    def test_empty_reason_rejected(self):
        response = self.client.post(
            "/workspace/inventory/res-gov-001/adjust/",
            {"delta": "10", "reason": "", "replenishment_method": "purchase"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("原因不能为空", response.content.decode())

    def test_invalid_replenishment_method_rejected(self):
        response = self.client.post(
            "/workspace/inventory/res-gov-001/adjust/",
            {"delta": "10", "reason": "test", "replenishment_method": "invalid"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("补充方式无效", response.content.decode())

    def test_observer_dashboard_shows_resources(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "资源库存")
        self.assertContains(response, "res-gov-001")

    def test_governance_user_can_access_new_resource_page(self):
        response = self.client.get("/workspace/inventory/new/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "新增资源")

    def test_governance_user_can_create_resource(self):
        count_before = Resource.objects.count()
        response = self.client.post(
            "/workspace/inventory/new/",
            {
                "resource_id": "res-new-001",
                "name": "测试资源",
                "resource_type": "grain",
                "unit": "kg",
                "replenishment_method": "purchase",
                "rule_version": "v1",
                "current_stock": "100",
                "warning_threshold": "20",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Resource.objects.count(), count_before + 1)
        new_res = Resource.objects.get(resource_id="res-new-001")
        self.assertEqual(new_res.current_stock, Decimal("100"))
        self.assertEqual(new_res.name, "测试资源")
        # 新增资源不创建 ResourceTransaction
        self.assertEqual(
            ResourceTransaction.objects.filter(resource=new_res).count(), 0,
        )

    def test_duplicate_resource_id_rejected(self):
        response = self.client.post(
            "/workspace/inventory/new/",
            {"resource_id": "res-gov-001", "resource_type": "grain", "unit": "kg",
             "replenishment_method": "purchase", "rule_version": "v1"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("已存在", response.content.decode())

    def test_invalid_decimal_rejected(self):
        response = self.client.post(
            "/workspace/inventory/new/",
            {"resource_id": "res-dec-001", "resource_type": "grain", "unit": "kg",
             "replenishment_method": "purchase", "rule_version": "v1",
             "current_stock": "not-a-number"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("必须是数字", response.content.decode())

    def test_negative_current_stock_rejected_on_new(self):
        count_before = Resource.objects.count()
        response = self.client.post(
            "/workspace/inventory/new/",
            {"resource_id": "res-neg-001", "resource_type": "grain", "unit": "kg",
             "replenishment_method": "purchase", "rule_version": "v1",
             "current_stock": "-1"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("不能为负数", response.content.decode())
        self.assertEqual(Resource.objects.count(), count_before)

    def test_dashboard_no_resources_shows_empty_state(self):
        # Delete all resources to test empty state
        Resource.objects.all().delete()
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "资源库存")
        self.assertContains(response, "暂无资源记录")

    def test_dashboard_resource_does_not_expose_private_payload(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn("metadata", content)
        self.assertNotIn("operator", content)

    # --- inventory edit tests ---

    def test_governance_user_can_access_edit_page(self):
        response = self.client.get("/workspace/inventory/res-gov-001/edit/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "编辑资源资料")
        self.assertContains(response, "res-gov-001")

    def test_governance_user_can_see_edit_button_in_list(self):
        response = self.client.get("/workspace/inventory/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "编辑")

    def test_edit_updates_text_fields(self):
        response = self.client.post(
            "/workspace/inventory/res-gov-001/edit/",
            {
                "name": "更新名称",
                "resource_type": "water",
                "status": "maintenance",
                "unit": "liter",
                "replenishment_method": "donation",
                "location": "新仓库",
                "description": "更新后的描述",
                "rule_version": "v2",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.resource.refresh_from_db()
        self.assertEqual(self.resource.name, "更新名称")
        self.assertEqual(self.resource.resource_type, "water")
        self.assertEqual(self.resource.status, "maintenance")
        self.assertEqual(self.resource.unit, "liter")
        self.assertEqual(self.resource.replenishment_method, "donation")
        self.assertEqual(self.resource.location, "新仓库")
        self.assertEqual(self.resource.description, "更新后的描述")
        self.assertEqual(self.resource.rule_version, "v2")

    def test_edit_updates_decimal_fields(self):
        response = self.client.post(
            "/workspace/inventory/res-gov-001/edit/",
            {
                "resource_type": "grain",
                "unit": "kg",
                "replenishment_method": "purchase",
                "rule_version": "v1",
                "warning_threshold": "30",
                "daily_consumption_estimate": "5.5",
                "loss_rate": "0.02",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.resource.refresh_from_db()
        self.assertEqual(self.resource.warning_threshold, Decimal("30"))
        self.assertEqual(self.resource.daily_consumption_estimate, Decimal("5.5"))
        self.assertEqual(self.resource.loss_rate, Decimal("0.02"))

    def test_edit_updates_updated_at(self):
        old_updated = self.resource.updated_at
        response = self.client.post(
            "/workspace/inventory/res-gov-001/edit/",
            {
                "resource_type": "grain",
                "unit": "kg",
                "replenishment_method": "purchase",
                "rule_version": "v1",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.resource.refresh_from_db()
        self.assertGreater(self.resource.updated_at, old_updated)

    def test_edit_does_not_create_resource_transaction(self):
        txn_before = ResourceTransaction.objects.count()
        response = self.client.post(
            "/workspace/inventory/res-gov-001/edit/",
            {
                "resource_type": "grain",
                "unit": "kg",
                "replenishment_method": "purchase",
                "rule_version": "v1",
                "location": "新位置",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ResourceTransaction.objects.count(), txn_before)

    def test_edit_preserves_current_stock(self):
        original_stock = self.resource.current_stock
        response = self.client.post(
            "/workspace/inventory/res-gov-001/edit/",
            {
                "name": "改名后",
                "resource_type": "grain",
                "unit": "kg",
                "replenishment_method": "purchase",
                "rule_version": "v1",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.resource.refresh_from_db()
        self.assertEqual(self.resource.current_stock, original_stock)

    def test_edit_ignores_current_stock_sneaked_in_post(self):
        """POST with current_stock=9999 must not change the actual stock."""
        original_stock = self.resource.current_stock
        self.assertNotEqual(original_stock, Decimal("9999"))
        txn_before = ResourceTransaction.objects.count()
        response = self.client.post(
            "/workspace/inventory/res-gov-001/edit/",
            {
                "name": "尝试篡改库存",
                "resource_type": "grain",
                "unit": "kg",
                "replenishment_method": "purchase",
                "rule_version": "v1",
                "current_stock": "9999",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.resource.refresh_from_db()
        self.assertEqual(self.resource.current_stock, original_stock)
        self.assertEqual(ResourceTransaction.objects.count(), txn_before)

    def test_edit_invalid_warning_threshold_returns_400(self):
        response = self.client.post(
            "/workspace/inventory/res-gov-001/edit/",
            {
                "resource_type": "grain",
                "unit": "kg",
                "replenishment_method": "purchase",
                "rule_version": "v1",
                "warning_threshold": "abc",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("必须是数字", response.content.decode())

    def test_edit_negative_warning_threshold_returns_400(self):
        response = self.client.post(
            "/workspace/inventory/res-gov-001/edit/",
            {
                "resource_type": "grain",
                "unit": "kg",
                "replenishment_method": "purchase",
                "rule_version": "v1",
                "warning_threshold": "-5",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("不能为负数", response.content.decode())

    def test_edit_invalid_daily_consumption_returns_400(self):
        response = self.client.post(
            "/workspace/inventory/res-gov-001/edit/",
            {
                "resource_type": "grain",
                "unit": "kg",
                "replenishment_method": "purchase",
                "rule_version": "v1",
                "daily_consumption_estimate": "xyz",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("必须是数字", response.content.decode())

    def test_edit_negative_daily_consumption_returns_400(self):
        response = self.client.post(
            "/workspace/inventory/res-gov-001/edit/",
            {
                "resource_type": "grain",
                "unit": "kg",
                "replenishment_method": "purchase",
                "rule_version": "v1",
                "daily_consumption_estimate": "-1",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("不能为负数", response.content.decode())

    def test_edit_invalid_loss_rate_returns_400(self):
        response = self.client.post(
            "/workspace/inventory/res-gov-001/edit/",
            {
                "resource_type": "grain",
                "unit": "kg",
                "replenishment_method": "purchase",
                "rule_version": "v1",
                "loss_rate": "not-a-number",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("必须是数字", response.content.decode())

    def test_edit_negative_loss_rate_returns_400(self):
        response = self.client.post(
            "/workspace/inventory/res-gov-001/edit/",
            {
                "resource_type": "grain",
                "unit": "kg",
                "replenishment_method": "purchase",
                "rule_version": "v1",
                "loss_rate": "-0.1",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("不能为负数", response.content.decode())

    def test_edit_invalid_resource_type_returns_400(self):
        response = self.client.post(
            "/workspace/inventory/res-gov-001/edit/",
            {
                "resource_type": "invalid_type",
                "unit": "kg",
                "replenishment_method": "purchase",
                "rule_version": "v1",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("值无效", response.content.decode())

    def test_edit_invalid_unit_returns_400(self):
        response = self.client.post(
            "/workspace/inventory/res-gov-001/edit/",
            {
                "resource_type": "grain",
                "unit": "invalid_unit",
                "replenishment_method": "purchase",
                "rule_version": "v1",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("值无效", response.content.decode())

    def test_edit_invalid_replenishment_method_returns_400(self):
        response = self.client.post(
            "/workspace/inventory/res-gov-001/edit/",
            {
                "resource_type": "grain",
                "unit": "kg",
                "replenishment_method": "invalid",
                "rule_version": "v1",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("值无效", response.content.decode())

    def test_edit_invalid_status_returns_400(self):
        response = self.client.post(
            "/workspace/inventory/res-gov-001/edit/",
            {
                "resource_type": "grain",
                "unit": "kg",
                "status": "ghost",
                "replenishment_method": "purchase",
                "rule_version": "v1",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("值无效", response.content.decode())

    def test_edit_empty_rule_version_returns_400(self):
        response = self.client.post(
            "/workspace/inventory/res-gov-001/edit/",
            {
                "resource_type": "grain",
                "unit": "kg",
                "replenishment_method": "purchase",
                "rule_version": "",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("不能为空", response.content.decode())

    def test_edit_nonexistent_resource_returns_404(self):
        response = self.client.get("/workspace/inventory/nonexistent-999/edit/")
        self.assertEqual(response.status_code, 404)
