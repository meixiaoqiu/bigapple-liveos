from __future__ import annotations

from django.test import TestCase

from core.governance_setup import ensure_administrator_role
from core.identity_display import member_identity_display
from core.member_roles import ROLE_DELIBERATOR, ROLE_COVENANTER, ROLE_ADMINISTRATOR, ensure_catalog_role
from core.models import Organization, Role
from core.professional_qualification_services import (
    ensure_professional_domain,
    record_external_professional_qualification,
)
from core.role_assignment_services import create_role_assignment, revoke_role_assignment
from core.tests.helpers import create_member


class MemberIdentityDisplayTests(TestCase):
    def setUp(self) -> None:
        self.covenanter_role = ensure_catalog_role(ROLE_COVENANTER)
        self.deliberator_role = ensure_catalog_role(ROLE_DELIBERATOR)
        self.administrator_role = ensure_administrator_role()["role"]
        self.member = create_member("display-member")
        self.confirmed_by = create_member("display-confirmed-by")
        create_role_assignment(member=self.confirmed_by, role=self.covenanter_role)
        create_role_assignment(member=self.confirmed_by, role=self.administrator_role)

    def test_contributor_is_a_derived_status_not_a_role(self) -> None:
        display = member_identity_display(self.member)

        self.assertEqual(display["derived_status"], {"code": "contributor", "name": "贡献者"})
        self.assertIsNone(display["membership"])
        self.assertEqual(display["duties"], [])

    def test_independent_deliberator_and_administrator_duties_are_displayed_together(self) -> None:
        create_role_assignment(member=self.member, role=self.covenanter_role)
        create_role_assignment(member=self.member, role=self.deliberator_role)
        create_role_assignment(member=self.member, role=self.administrator_role)

        display = member_identity_display(self.member)

        self.assertEqual(display["membership"]["name"], "守约者")
        self.assertEqual({item["name"] for item in display["duties"]}, {"执衡者", "管理员"})
        self.assertIsNone(display["derived_status"])

    def test_current_professional_qualification_is_separate_from_duties(self) -> None:
        create_role_assignment(member=self.member, role=self.covenanter_role)
        domain = ensure_professional_domain(code="finance", name="财务")
        record_external_professional_qualification(
            member=self.member,
            domain=domain,
            confirmed_by=self.confirmed_by,
            external_confirmation_source="外部财务资格核验",
        )

        display = member_identity_display(self.member)

        self.assertEqual(display["professional_qualifications"][0]["name"], "财务")
        self.assertEqual(display["duties"], [])

    def test_lost_covenantership_hides_dependent_duties_but_preserves_records(self) -> None:
        covenanter_assignment = create_role_assignment(member=self.member, role=self.covenanter_role)
        deliberator_assignment = create_role_assignment(member=self.member, role=self.deliberator_role)
        administrator_assignment = create_role_assignment(member=self.member, role=self.administrator_role)
        revoke_role_assignment(assignment=covenanter_assignment, revoked_by=self.confirmed_by)

        display = member_identity_display(self.member)

        self.assertIsNone(display["membership"])
        self.assertEqual(display["duties"], [])
        self.assertEqual(display["restriction_reason"], "尚未取得当前有效的守约者资格。")
        self.assertTrue(type(deliberator_assignment).objects.filter(pk=deliberator_assignment.pk).exists())
        self.assertTrue(type(administrator_assignment).objects.filter(pk=administrator_assignment.pk).exists())

    def test_unknown_dynamic_role_never_becomes_an_identity_label(self) -> None:
        create_role_assignment(member=self.member, role=self.covenanter_role)
        unknown_role = Role.objects.create(
            organization=Organization.objects.create(name="未分类职责组织"),
            name="未分类职责",
            status=Role.Status.ACTIVE,
        )
        create_role_assignment(member=self.member, role=unknown_role)

        display = member_identity_display(self.member)

        self.assertEqual(display["membership"]["name"], "守约者")
        self.assertEqual(display["duties"], [])
