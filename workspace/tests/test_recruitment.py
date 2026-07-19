"""Tests for workplace recruitment-direction maintenance page."""
from __future__ import annotations

from django.test import TestCase

from core.credential_services import ensure_builtin_credential_templates
from core.models import CredentialGrant, CredentialTemplate, Member
from core.tests.helpers import create_governance_admin_member, create_member, login_as_member


class WorkspaceRecruitmentTests(TestCase):
    """Cover /workspace/recruitment/ access control and config updates."""

    @classmethod
    def setUpTestData(cls):
        ensure_builtin_credential_templates()

    def setUp(self):
        self.gov = create_governance_admin_member("rec-gov")
        self.ordinary = create_member("rec-ord", display_name="普通成员")
        self.applicant = create_member("rec-app", display_name="报名测试者")
        login_as_member(self.client, self.gov)

    # --- 1. access control -------------------------------------------------------

    def test_recruitment_page_requires_login(self):
        self.client.logout()
        response = self.client.get("/workspace/recruitment/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])
        self.assertIn("/workspace/recruitment/", response["Location"])

    def test_recruitment_page_requires_governance_member(self):
        login_as_member(self.client, self.ordinary)
        response = self.client.get("/workspace/recruitment/")
        self.assertEqual(response.status_code, 403)

    def test_governance_member_can_view_recruitment_page(self):
        response = self.client.get("/workspace/recruitment/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "招募方向维护")
        self.assertContains(response, "ai_engineer")
        self.assertContains(response, "life_service")

    # --- 2. config update --------------------------------------------------------

    def test_update_recruitment_config(self):
        t = CredentialTemplate.objects.get(code="ai_engineer")
        t.metadata = {**t.metadata, "custom_key": "custom_value"}
        t.save()

        response = self.client.post(
            "/workspace/recruitment/",
            {
                "action": "update",
                "template_code": "ai_engineer",
                "show_on_application": "on",
                "public_label": "AI 开发方向",
                "public_description": "新的描述。",
                "required_count": "5",
                "sort_order": "55",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "AI 开发方向")
        self.assertNotContains(response, "更新失败")

        t.refresh_from_db()
        recruitment = t.metadata.get("recruitment", {})
        self.assertEqual(recruitment["public_label"], "AI 开发方向")
        self.assertEqual(recruitment["public_description"], "新的描述。")
        self.assertEqual(recruitment["required_count"], 5)
        self.assertEqual(recruitment["sort_order"], 55)
        self.assertEqual(t.metadata.get("custom_key"), "custom_value")

    def test_update_syncs_name_and_description(self):
        t = CredentialTemplate.objects.get(code="ai_engineer")
        self.client.post(
            "/workspace/recruitment/",
            {
                "action": "update",
                "template_code": "ai_engineer",
                "public_label": "新的模板名称",
                "public_description": "新的模板描述",
                "required_count": "2",
                "sort_order": "60",
            },
            follow=True,
        )
        t.refresh_from_db()
        self.assertEqual(t.name, "新的模板名称")
        self.assertEqual(t.description, "新的模板描述")

    def test_cannot_update_formal_member_number_recruitment(self):
        response = self.client.post(
            "/workspace/recruitment/",
            {
                "action": "update",
                "template_code": "formal_member_number",
                "public_label": "不应该成功",
                "required_count": "1",
                "sort_order": "1",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "更新失败")

    def test_required_count_must_be_non_negative(self):
        response = self.client.post(
            "/workspace/recruitment/",
            {
                "action": "update",
                "template_code": "ai_engineer",
                "public_label": "AI",
                "required_count": "-1",
                "sort_order": "1",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "更新失败")

    def test_required_count_must_be_integer(self):
        t = CredentialTemplate.objects.get(code="ai_engineer")
        orig_required = (t.metadata or {}).get("recruitment", {}).get("required_count", 0)
        response = self.client.post(
            "/workspace/recruitment/",
            {
                "action": "update",
                "template_code": "ai_engineer",
                "public_label": "AI",
                "required_count": "abc",
                "sort_order": "1",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "更新失败")
        self.assertContains(response, "需要人数必须是整数")
        t.refresh_from_db()
        self.assertEqual((t.metadata or {}).get("recruitment", {}).get("required_count", 0), orig_required)

    def test_sort_order_must_be_integer(self):
        t = CredentialTemplate.objects.get(code="life_service")
        orig_sort = (t.metadata or {}).get("recruitment", {}).get("sort_order", 0)
        response = self.client.post(
            "/workspace/recruitment/",
            {
                "action": "update",
                "template_code": "life_service",
                "public_label": "生活服务",
                "required_count": "3",
                "sort_order": "abc",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "更新失败")
        self.assertContains(response, "排序必须是整数")
        t.refresh_from_db()
        self.assertEqual((t.metadata or {}).get("recruitment", {}).get("sort_order", 0), orig_sort)

    def test_management_rows_sort_by_sort_order_display_order_code(self):
        from core.credential_services import recruitment_templates_for_management

        t1 = CredentialTemplate.objects.get(code="ai_engineer")
        t1.metadata = {
            **(t1.metadata or {}),
            "recruitment": {
                "show_on_application": True,
                "public_label": "X",
                "required_count": 1,
                "sort_order": 100,
            },
        }
        t1.display_order = 200
        t1.save()
        t2 = CredentialTemplate.objects.get(code="life_service")
        t2.metadata = {
            **(t2.metadata or {}),
            "recruitment": {
                "show_on_application": True,
                "public_label": "Y",
                "required_count": 1,
                "sort_order": 100,
            },
        }
        t2.display_order = 150
        t2.save()

        rows = recruitment_templates_for_management()
        codes = [r["code"] for r in rows if r["code"] in ("life_service", "ai_engineer")]
        self.assertEqual(codes, ["life_service", "ai_engineer"])

    # --- 3. apply-form reflection ------------------------------------------------

    def test_apply_form_reflects_recruitment_config(self):
        t = CredentialTemplate.objects.get(code="ai_engineer")
        current_metadata = dict(t.metadata or {})
        current_metadata["recruitment"] = {
            "show_on_application": True,
            "public_label": "改名后的 AI 方向",
            "public_description": "改名后的描述",
            "required_count": 10,
            "sort_order": 55,
        }
        t.metadata = current_metadata
        t.save()

        login_as_member(self.client, self.applicant)
        response = self.client.get("/workspace/apply/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "改名后的 AI 方向")
        self.assertContains(response, "改名后的描述")

    def test_hidden_recruitment_option_not_shown_on_apply(self):
        t = CredentialTemplate.objects.get(code="medical_support")
        current_metadata = dict(t.metadata or {})
        current_metadata["recruitment"] = {
            "show_on_application": True,
            "public_label": "临时隐藏测试方向",
            "public_description": "测试隐藏",
            "required_count": 1,
            "sort_order": 40,
        }
        t.metadata = current_metadata
        t.save()

        login_as_member(self.client, self.applicant)
        response = self.client.get("/workspace/apply/")
        self.assertContains(response, "临时隐藏测试方向")

        t.metadata = {
            **t.metadata,
            "recruitment": {**t.metadata["recruitment"], "show_on_application": False},
        }
        t.save()
        response = self.client.get("/workspace/apply/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "临时隐藏测试方向")

    # --- 4. no credential issuance -----------------------------------------------

    def test_update_recruitment_does_not_issue_credential(self):
        grant_count_before = CredentialGrant.objects.count()
        self.client.post(
            "/workspace/recruitment/",
            {
                "action": "update",
                "template_code": "life_service",
                "public_label": "生活服务",
                "required_count": "5",
                "sort_order": "99",
            },
            follow=True,
        )
        self.assertEqual(CredentialGrant.objects.count(), grant_count_before)

    # --- 5. nav entry -----------------------------------------------------------

    def test_workspace_nav_shows_recruitment_for_governance_member(self):
        response = self.client.get("/workspace/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "招募方向")
        self.assertContains(response, "/workspace/recruitment/")

    def test_workspace_nav_hides_recruitment_for_ordinary_member(self):
        login_as_member(self.client, self.ordinary)
        response = self.client.get("/workspace/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "招募方向")

    # --- 6. create recruitment template ------------------------------------------

    def test_governance_member_can_create_recruitment_template(self):
        response = self.client.post(
            "/workspace/recruitment/",
            {
                "action": "create",
                "code": "community_gardener",
                "public_label": "社区园艺方向",
                "public_description": "负责社区绿化、种植和维护。",
                "required_count": "2",
                "sort_order": "200",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "社区园艺方向")

        t = CredentialTemplate.objects.get(code="community_gardener")
        self.assertEqual(t.credential_type, CredentialTemplate.CredentialType.CERTIFICATE)
        self.assertEqual(t.status, CredentialTemplate.Status.ACTIVE)
        self.assertEqual(t.visibility, CredentialTemplate.Visibility.PUBLIC)
        self.assertEqual(t.name, "社区园艺方向")
        self.assertEqual(t.description, "负责社区绿化、种植和维护。")
        recruitment = t.metadata.get("recruitment", {})
        self.assertEqual(recruitment["public_label"], "社区园艺方向")
        self.assertEqual(recruitment["required_count"], 2)
        self.assertTrue(recruitment["show_on_application"])

    def test_created_recruitment_template_shows_on_apply_page(self):
        self.client.post(
            "/workspace/recruitment/",
            {
                "action": "create",
                "code": "community_gardener",
                "public_label": "社区园艺方向",
                "required_count": "2",
                "sort_order": "200",
            },
            follow=True,
        )
        login_as_member(self.client, self.applicant)
        response = self.client.get("/workspace/apply/")
        self.assertContains(response, "社区园艺方向")

    def test_create_recruitment_template_does_not_issue_credential(self):
        grant_count = CredentialGrant.objects.count()
        self.client.post(
            "/workspace/recruitment/",
            {
                "action": "create",
                "code": "community_gardener",
                "public_label": "社区园艺方向",
                "required_count": "1",
                "sort_order": "200",
            },
            follow=True,
        )
        self.assertEqual(CredentialGrant.objects.count(), grant_count)

    def test_create_recruitment_template_requires_governance_member(self):
        login_as_member(self.client, self.ordinary)
        response = self.client.post(
            "/workspace/recruitment/",
            {
                "action": "create",
                "code": "test_direction",
                "public_label": "测试",
                "required_count": "1",
                "sort_order": "100",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 403)

    def test_create_recruitment_template_rejects_duplicate_code(self):
        self.client.post(
            "/workspace/recruitment/",
            {
                "action": "create",
                "code": "community_gardener",
                "public_label": "第一次",
                "required_count": "1",
                "sort_order": "100",
            },
            follow=True,
        )
        response = self.client.post(
            "/workspace/recruitment/",
            {
                "action": "create",
                "code": "community_gardener",
                "public_label": "第二次",
                "required_count": "1",
                "sort_order": "100",
            },
            follow=True,
        )
        self.assertContains(response, "编码已存在")

    def test_create_recruitment_template_rejects_formal_member_number_code(self):
        response = self.client.post(
            "/workspace/recruitment/",
            {
                "action": "create",
                "code": "formal_member_number",
                "public_label": "不应该成功",
                "required_count": "1",
                "sort_order": "1",
            },
            follow=True,
        )
        self.assertContains(response, "创建失败")

    def test_create_recruitment_template_rejects_invalid_code_chinese(self):
        code_before = CredentialTemplate.objects.filter(code="中文方向").exists()
        response = self.client.post(
            "/workspace/recruitment/",
            {
                "action": "create",
                "code": "中文方向",
                "public_label": "测试",
                "required_count": "1",
                "sort_order": "100",
            },
            follow=True,
        )
        self.assertContains(response, "创建失败")
        self.assertFalse(
            CredentialTemplate.objects.filter(code="中文方向").exists(),
            "Template with Chinese code must not be created",
        )
        # shouldn't have created anything with normalised code either
        self.assertEqual(code_before, CredentialTemplate.objects.filter(code="中文方向").exists())

    def test_create_recruitment_template_rejects_invalid_code_special_chars(self):
        response = self.client.post(
            "/workspace/recruitment/",
            {
                "action": "create",
                "code": "bad-code!",
                "public_label": "测试",
                "required_count": "1",
                "sort_order": "100",
            },
            follow=True,
        )
        self.assertContains(response, "创建失败")
        self.assertFalse(CredentialTemplate.objects.filter(code="bad_code_").exists())

    def test_create_recruitment_template_requires_label(self):
        response = self.client.post(
            "/workspace/recruitment/",
            {
                "action": "create",
                "code": "test_dir",
                "public_label": "",
                "required_count": "1",
                "sort_order": "100",
            },
            follow=True,
        )
        self.assertContains(response, "创建失败")
        self.assertFalse(CredentialTemplate.objects.filter(code="test_dir").exists())

    def test_update_recruitment_template_rejects_too_long_label(self):
        t = CredentialTemplate.objects.get(code="ai_engineer")
        orig_name = t.name
        orig_metadata = dict(t.metadata or {})
        response = self.client.post(
            "/workspace/recruitment/",
            {
                "action": "update",
                "template_code": "ai_engineer",
                "public_label": "x" * 256,
                "public_description": "desc",
                "required_count": "2",
                "sort_order": "60",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "更新失败")
        self.assertContains(response, "公开名称不能超过 255")
        t.refresh_from_db()
        self.assertEqual(t.name, orig_name)
        self.assertEqual(t.metadata, orig_metadata)

    def test_update_recruitment_template_rejects_too_long_description(self):
        t = CredentialTemplate.objects.get(code="ai_engineer")
        orig_desc = t.description
        orig_metadata = dict(t.metadata or {})
        response = self.client.post(
            "/workspace/recruitment/",
            {
                "action": "update",
                "template_code": "ai_engineer",
                "public_label": "AI",
                "public_description": "x" * 501,
                "required_count": "2",
                "sort_order": "60",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "更新失败")
        self.assertContains(response, "公开说明不能超过 500")
        t.refresh_from_db()
        self.assertEqual(t.description, orig_desc)
        self.assertEqual(t.metadata, orig_metadata)

    def test_no_delete_recruitment_template_endpoint(self):
        t = CredentialTemplate.objects.get(code="ai_engineer")
        orig_status = t.status
        orig_name = t.name
        orig_description = t.description
        orig_metadata = dict(t.metadata or {})
        response = self.client.post(
            "/workspace/recruitment/",
            {
                "action": "delete",
                "template_code": "ai_engineer",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "未知的招募方向操作")
        t.refresh_from_db()
        self.assertEqual(t.status, orig_status)
        self.assertEqual(t.name, orig_name)
        self.assertEqual(t.description, orig_description)
        self.assertEqual(t.metadata, orig_metadata)
