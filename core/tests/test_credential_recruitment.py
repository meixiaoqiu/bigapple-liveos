"""Tests for credential-based recruitment system."""

from __future__ import annotations

from django.test import TestCase

from core.credential_services import (
    credential_recruitment_gap,
    ensure_builtin_credential_templates,
    recruitment_credential_options,
    recruitment_option_for_code,
)
from core.models import CredentialGrant, CredentialTemplate, Member
from core.tests.helpers import create_member


class CredentialRecruitmentTests(TestCase):

    def setUp(self):
        ensure_builtin_credential_templates()

    def test_builtin_recruitment_templates_exist(self):
        opts = recruitment_credential_options()
        self.assertGreater(len(opts), 0)

    def test_formal_member_number_not_in_recruitment(self):
        opts = recruitment_credential_options()
        codes = [o["code"] for o in opts]
        self.assertNotIn("formal_member_number", codes)

    def test_recruitment_option_has_current_and_missing_counts(self):
        opt = recruitment_option_for_code("medical_support")
        self.assertIsNotNone(opt)
        self.assertIn("current_count", opt)
        self.assertIn("missing_count", opt)

    def test_gap_counts_active_grants(self):
        t = CredentialTemplate.objects.get(code="medical_support")
        gap0 = credential_recruitment_gap(t)
        self.assertEqual(gap0["current_count"], 0)

        member = create_member("gap-member", display_name="GapUser")
        CredentialGrant.objects.create(template=t, member=member, status=CredentialGrant.Status.ACTIVE)
        gap1 = credential_recruitment_gap(t)
        self.assertEqual(gap1["current_count"], 1)

    def test_revoked_grants_not_counted(self):
        t = CredentialTemplate.objects.get(code="company_legal_representative")
        member = create_member("revoked-gap", display_name="Revoked")
        g = CredentialGrant.objects.create(template=t, member=member, status=CredentialGrant.Status.ACTIVE)
        g.status = CredentialGrant.Status.REVOKED
        g.save()
        gap = credential_recruitment_gap(t)
        self.assertEqual(gap["current_count"], 0)

    def test_archived_grants_not_counted(self):
        t = CredentialTemplate.objects.get(code="ai_engineer")
        member = create_member("archived-gap", display_name="Archived")
        g = CredentialGrant.objects.create(template=t, member=member, status=CredentialGrant.Status.ACTIVE)
        g.status = CredentialGrant.Status.ARCHIVED
        g.save()
        gap = credential_recruitment_gap(t)
        self.assertEqual(gap["current_count"], 0)

    def test_missing_count_floor_zero(self):
        t = CredentialTemplate.objects.get(code="life_service")
        gap = credential_recruitment_gap(t)
        self.assertEqual(gap["missing_count"], gap["required_count"])
        for i in range(gap["required_count"] + 2):
            m = create_member(f"overfill-{i}", display_name=f"Over{i}")
            CredentialGrant.objects.create(template=t, member=m, status=CredentialGrant.Status.ACTIVE)
        gap2 = credential_recruitment_gap(t)
        self.assertEqual(gap2["missing_count"], 0)

    def test_recruitment_option_for_code(self):
        opt = recruitment_option_for_code("medical_support")
        self.assertIsNotNone(opt)
        self.assertEqual(opt["code"], "medical_support")
        self.assertIn("current_count", opt)

    def test_recruitment_option_for_unknown_code(self):
        self.assertIsNone(recruitment_option_for_code("nonexistent"))

    def test_is_open_unlimited(self):
        """required_count<=0 means is_open=True."""
        t = CredentialTemplate.objects.get(code="medical_support")
        t.metadata = {"recruitment": {"show_on_application": True, "required_count": 0, "public_label": "test"}}
        t.save()
        gap = credential_recruitment_gap(t)
        self.assertTrue(gap["is_open"])
        # restore
        t.metadata = {"recruitment": {"show_on_application": True, "required_count": 1, "public_label": "医生/健康支持方向", "public_description": "健康支持", "sort_order": 40}}
        t.save()

    def test_options_sorted_by_sort_order(self):
        opts = recruitment_credential_options()
        self.assertGreater(len(opts), 1)
        orders = [o["sort_order"] for o in opts]
        self.assertEqual(orders, sorted(orders))

    def test_old_static_code_rejected(self):
        from core.application_services import submit_member_application
        from core.exceptions import DomainError
        with self.assertRaises(DomainError):
            submit_member_application(
                applicant_name="test", contact="test@test.test", motivation="test",
                role_gap="developer_ai_engineer",
            )
