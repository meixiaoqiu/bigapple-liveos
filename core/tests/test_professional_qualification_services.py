from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from core.exceptions import DomainError
from core.governance_setup import ensure_maintainer_role
from core.member_roles import ROLE_COVENANTER, ensure_catalog_role
from core.models import Member, MemberProfessionalQualification
from core.professional_qualification_services import (
    ensure_professional_domain,
    expire_elapsed_professional_qualifications,
    has_current_professional_qualification,
    record_external_professional_qualification,
    revoke_professional_qualification,
)
from core.role_assignment_services import create_role_assignment


class ProfessionalQualificationServiceTests(TestCase):
    def create_member(self, member_no: str, *, user=None) -> Member:
        return Member.objects.create(
            member_no=member_no,
            user=user,
            status=Member.Status.ACTIVE,
            credit_floor=-100,
            created_at=timezone.now(),
        )

    def admit_covenanter(self, member: Member, *, start_at=None) -> None:
        create_role_assignment(
            member=member,
            role=ensure_catalog_role(ROLE_COVENANTER),
            start_at=start_at,
        )

    def admit_qualification_maintainer(self, member: Member) -> None:
        self.admit_covenanter(member)
        create_role_assignment(member=member, role=ensure_maintainer_role()["role"])

    def test_external_confirmation_records_authority_without_credential(self):
        domain = ensure_professional_domain(code="finance", name="财务")
        member = self.create_member("qualification-finance")
        confirmer = self.create_member("qualification-confirmer")
        self.admit_covenanter(member)
        self.admit_qualification_maintainer(confirmer)
        qualification = record_external_professional_qualification(
            member=member,
            domain=domain,
            confirmed_by=confirmer,
            external_confirmation_source="外部执照核验记录 FIN-001",
        )

        self.assertEqual(qualification.status, MemberProfessionalQualification.Status.ACTIVE)
        self.assertEqual(qualification.domain, domain)
        self.assertEqual(qualification.confirmed_by, confirmer)
        self.assertTrue(has_current_professional_qualification(member, domain=domain))

    def test_non_covenanter_cannot_receive_professional_qualification(self):
        domain = ensure_professional_domain(code="construction", name="建设")
        member = self.create_member("qualification-non-covenanter")
        confirmer = self.create_member("qualification-non-covenanter-confirmer")

        with self.assertRaisesRegex(DomainError, "守约者"):
            record_external_professional_qualification(
                member=member,
                domain=domain,
                confirmed_by=confirmer,
                external_confirmation_source="外部面试记录",
            )

    def test_regular_member_cannot_confirm_professional_qualification(self):
        domain = ensure_professional_domain(code="law", name="法律")
        member = self.create_member("qualification-subject")
        regular_member = self.create_member("qualification-regular-member")
        self.admit_covenanter(member)

        with self.assertRaisesRegex(DomainError, "专业资格维护权限"):
            record_external_professional_qualification(
                member=member,
                domain=domain,
                confirmed_by=regular_member,
                external_confirmation_source="外部资格核验",
            )

        self.assertFalse(MemberProfessionalQualification.objects.filter(member=member).exists())

    def test_expired_qualification_is_not_current_and_is_retained(self):
        domain = ensure_professional_domain(code="operations", name="运营")
        member = self.create_member("qualification-expired")
        confirmer = self.create_member("qualification-expired-confirmer")
        starts_at = timezone.now() - timedelta(days=3)
        self.admit_covenanter(member, start_at=starts_at)
        self.admit_qualification_maintainer(confirmer)
        qualification = record_external_professional_qualification(
            member=member,
            domain=domain,
            confirmed_by=confirmer,
            external_confirmation_source="外部实践考核记录",
            valid_from=starts_at,
            valid_until=timezone.now() - timedelta(days=1),
        )

        self.assertFalse(has_current_professional_qualification(member, domain=domain))
        self.assertEqual(expire_elapsed_professional_qualifications(member=member), 1)
        qualification.refresh_from_db()
        self.assertEqual(qualification.status, MemberProfessionalQualification.Status.EXPIRED)

    def test_revoked_qualification_is_not_current(self):
        domain = ensure_professional_domain(code="safety", name="安全")
        member = self.create_member("qualification-revoked")
        confirmer = self.create_member("qualification-revoked-confirmer")
        self.admit_covenanter(member)
        self.admit_qualification_maintainer(confirmer)
        qualification = record_external_professional_qualification(
            member=member,
            domain=domain,
            confirmed_by=confirmer,
            external_confirmation_source="外部资质复核记录",
        )

        regular_member = self.create_member("qualification-revoked-regular")
        with self.assertRaisesRegex(DomainError, "专业资格维护权限"):
            revoke_professional_qualification(qualification=qualification, revoked_by=regular_member)
        qualification.refresh_from_db()
        self.assertEqual(qualification.status, MemberProfessionalQualification.Status.ACTIVE)

        revoke_professional_qualification(qualification=qualification, revoked_by=confirmer)

        self.assertFalse(has_current_professional_qualification(member, domain_code="safety"))

    def test_disabled_member_account_vetoes_professional_qualification(self):
        domain = ensure_professional_domain(code="planning", name="规划")
        user = get_user_model().objects.create_user(username="qualification-disabled", password="test-password")
        member = self.create_member("qualification-disabled", user=user)
        confirmer = self.create_member("qualification-disabled-confirmer")
        self.admit_covenanter(member)
        self.admit_qualification_maintainer(confirmer)
        record_external_professional_qualification(
            member=member,
            domain=domain,
            confirmed_by=confirmer,
            external_confirmation_source="外部资质档案",
        )
        user.is_active = False
        user.save(update_fields=["is_active"])
        member.refresh_from_db()

        self.assertFalse(has_current_professional_qualification(member, domain=domain))
