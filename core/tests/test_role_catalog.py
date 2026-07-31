from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model

from core.exceptions import DomainError
from core.role_catalog import (
    DERIVED_CONCEPT_DEFINITIONS,
    MAINTAINER_PERMISSION_CODES,
    ROLE_CATALOG_ORGANIZATION_NAME,
    ROLE_CATALOG_ORGANIZATION_KEY,
    ROLE_DEFINITIONS,
    ROLE_DELIBERATOR,
    ROLE_FORMAL_MEMBER,
    ROLE_MAINTAINER,
    RoleDimension,
    TermRule,
    catalog_role_definition_for_role,
    ensure_catalog_roles,
    role_definition_for_name,
    validate_role_catalog,
)
from core.models import CredentialGrant, Member, Organization, Role, RoleAssignment
from core.member_roles import ensure_catalog_role, member_has_role, participation_status
from core.role_assignment_services import create_role_assignment, revoke_role_assignment


class RoleCatalogTests(TestCase):
    def test_catalog_contains_only_the_three_direct_new_system_facts(self):
        self.assertEqual(
            {(item.code, item.display_name) for item in ROLE_DEFINITIONS},
            {
                ("formal_member", ROLE_FORMAL_MEMBER),
                ("deliberator", ROLE_DELIBERATOR),
                ("maintainer", ROLE_MAINTAINER),
            },
        )
        self.assertEqual(validate_role_catalog(), [])

    def test_direct_facts_are_independent_dimensions_with_expected_prerequisites(self):
        formal_member = role_definition_for_name(ROLE_FORMAL_MEMBER)
        deliberator = role_definition_for_name(ROLE_DELIBERATOR)
        maintainer = role_definition_for_name(ROLE_MAINTAINER)

        self.assertIsNotNone(formal_member)
        self.assertIsNotNone(deliberator)
        self.assertIsNotNone(maintainer)
        self.assertEqual(formal_member.dimension, RoleDimension.MEMBER_QUALIFICATION)
        self.assertFalse(formal_member.requires_formal_member)
        self.assertEqual(deliberator.dimension, RoleDimension.DELIBERATION_DUTY)
        self.assertTrue(deliberator.requires_formal_member)
        self.assertEqual(deliberator.term_rule, TermRule.ONE_YEAR_SELF_APPLICATION)
        self.assertEqual(maintainer.dimension, RoleDimension.MAINTENANCE_DUTY)
        self.assertTrue(maintainer.requires_formal_member)
        self.assertNotEqual(deliberator.dimension, maintainer.dimension)

    def test_derived_concepts_are_not_direct_roles(self):
        direct_codes = {item.code for item in ROLE_DEFINITIONS}
        direct_names = {item.display_name for item in ROLE_DEFINITIONS}

        self.assertEqual({item.code for item in DERIVED_CONCEPT_DEFINITIONS}, {
            "contributor",
            "anonymous_observation",
            "formal_member_application",
        })
        self.assertFalse(direct_codes.intersection(item.code for item in DERIVED_CONCEPT_DEFINITIONS))
        self.assertFalse(direct_names.intersection(item.display_name for item in DERIVED_CONCEPT_DEFINITIONS))

    def test_catalog_setup_creates_only_direct_role_definitions(self):
        roles = ensure_catalog_roles()

        self.assertEqual(set(roles), {"formal_member", "deliberator", "maintainer"})
        self.assertEqual(
            set(
                Role.objects.filter(organization__role_catalog_key=ROLE_CATALOG_ORGANIZATION_KEY)
                .values_list("name", flat=True)
            ),
            {ROLE_FORMAL_MEMBER, ROLE_DELIBERATOR, ROLE_MAINTAINER},
        )
        self.assertTrue(MAINTAINER_PERMISSION_CODES)
        self.assertEqual(
            roles["formal_member"].organization.role_catalog_key,
            ROLE_CATALOG_ORGANIZATION_KEY,
        )

    def test_same_name_role_outside_catalog_is_rejected_without_credential(self):
        member = Member.objects.create(
            member_no="catalog-impostor-role",
            status=Member.Status.ACTIVE,
            credit_floor=-100,
            created_at=timezone.now(),
        )
        impostor_role = Role.objects.create(
            organization=Organization.objects.create(name="其他组织"),
            name=ROLE_FORMAL_MEMBER,
            status=Role.Status.ACTIVE,
        )

        self.assertIsNone(catalog_role_definition_for_role(impostor_role))
        with self.assertRaisesRegex(DomainError, "规范成员资格与职责目录"):
            create_role_assignment(member=member, role=impostor_role)

        self.assertFalse(member_has_role(member, ROLE_FORMAL_MEMBER))
        self.assertFalse(CredentialGrant.objects.filter(member=member).exists())

    def test_contributor_is_derived_and_never_creates_a_role_assignment(self):
        member = Member.objects.create(
            member_no="catalog-contributor",
            status=Member.Status.ACTIVE,
            credit_floor=-100,
            created_at=timezone.now(),
        )

        self.assertEqual(participation_status(member), "contributor")
        self.assertFalse(RoleAssignment.objects.filter(member=member).exists())

    def test_current_fact_query_vetoes_expired_assignments_and_inactive_users(self):
        user = get_user_model().objects.create_user(
            username="catalog-user",
            password="test-password",
            is_active=True,
        )
        member = Member.objects.create(
            member_no="catalog-user",
            user=user,
            status=Member.Status.ADMITTED,
            credit_floor=-100,
            created_at=timezone.now(),
        )
        role = ensure_catalog_role(ROLE_FORMAL_MEMBER)
        create_role_assignment(member=member, role=role, end_at=timezone.now() + timedelta(days=1))

        self.assertTrue(member_has_role(member, ROLE_FORMAL_MEMBER))
        user.is_active = False
        user.save(update_fields=["is_active"])
        member.refresh_from_db()
        self.assertFalse(member_has_role(member, ROLE_FORMAL_MEMBER))

    def test_deliberator_and_maintainer_are_independent_current_facts(self):
        member = Member.objects.create(
            member_no="catalog-independent-duties",
            status=Member.Status.ACTIVE,
            credit_floor=-100,
            created_at=timezone.now(),
        )
        create_role_assignment(member=member, role=ensure_catalog_role(ROLE_FORMAL_MEMBER))
        create_role_assignment(member=member, role=ensure_catalog_role(ROLE_DELIBERATOR))
        create_role_assignment(member=member, role=ensure_catalog_role(ROLE_MAINTAINER))

        self.assertTrue(member_has_role(member, ROLE_FORMAL_MEMBER))
        self.assertTrue(member_has_role(member, ROLE_DELIBERATOR))
        self.assertTrue(member_has_role(member, ROLE_MAINTAINER))

    def test_expired_and_revoked_assignments_are_not_current_facts(self):
        member = Member.objects.create(
            member_no="catalog-expired-duty",
            status=Member.Status.ACTIVE,
            credit_floor=-100,
            created_at=timezone.now(),
        )
        formal = create_role_assignment(member=member, role=ensure_catalog_role(ROLE_FORMAL_MEMBER))
        expired = create_role_assignment(
            member=member,
            role=ensure_catalog_role(ROLE_DELIBERATOR),
            start_at=timezone.now() - timedelta(days=2),
            end_at=timezone.now() - timedelta(days=1),
        )

        self.assertFalse(member_has_role(member, ROLE_DELIBERATOR))
        self.assertTrue(member_has_role(member, ROLE_FORMAL_MEMBER))
        revoke_role_assignment(assignment=formal)
        self.assertFalse(member_has_role(member, ROLE_FORMAL_MEMBER))
        self.assertEqual(expired.status, RoleAssignment.Status.ACTIVE)

    def test_unknown_role_name_cannot_be_used_as_a_catalog_fact(self):
        with self.assertRaisesRegex(ValueError, "不是可直接授予的规范角色"):
            ensure_catalog_role("未分类职责")
