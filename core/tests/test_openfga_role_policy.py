from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from core.authorization_services import (
    AuthorizationService,
    OPENFGA_AUTHORIZATION_MODEL_VERSION,
    openfga_professional_domain_object,
    openfga_proposal_object,
)
from core.governance_setup import ensure_administrator_role
from core.electorate_rules import (
    TEMPLATE_COVENANTER,
    TEMPLATE_PROFESSIONAL,
    current_electorate_rule_version,
    ensure_electorate_rule_baseline,
)
from core.management.commands.openfga_rebuild_tuples import _project_authorization_tuples, _unique_tuples
from core.member_roles import ROLE_DELIBERATOR, ROLE_COVENANTER, ROLE_ADMINISTRATOR, ensure_catalog_role
from core.models import Proposal
from core.professional_qualification_services import (
    ensure_professional_domain,
    record_external_professional_qualification,
)
from core.proposals.lifecycle import create_proposal
from core.role_assignment_services import create_role_assignment, revoke_role_assignment
from core.tests.helpers import create_member


class OpenFGARolePolicyTests(TestCase):
    def setUp(self) -> None:
        self.covenanter_role = ensure_catalog_role(ROLE_COVENANTER)
        self.deliberator_role = ensure_catalog_role(ROLE_DELIBERATOR)
        self.administrator_role = ensure_administrator_role()["role"]
        self.deliberator = create_member("fga-deliberator")
        self.administrator = create_member("fga-administrator")
        self.finance_domain = ensure_professional_domain(code="finance", name="财务")
        ensure_electorate_rule_baseline()
        self._assign(self.deliberator, self.covenanter_role)
        self._assign(self.deliberator, self.deliberator_role)
        self._assign(self.administrator, self.covenanter_role)
        self._assign(self.administrator, self.administrator_role)
        self.qualification = record_external_professional_qualification(
            member=self.deliberator,
            domain=self.finance_domain,
            confirmed_by=self.administrator,
            external_confirmation_source="外部财务资格核验",
        )
        now = timezone.now()
        self.general_proposal = create_proposal(
            title="普通议事",
            proposal_type=Proposal.ProposalType.RULE,
            electorate_rule_version=current_electorate_rule_version(TEMPLATE_COVENANTER),
            start_at=now,
            deadline_at=now + timedelta(days=7),
        )
        self.professional_proposal = create_proposal(
            title="财务议事",
            proposal_type=Proposal.ProposalType.BUDGET,
            electorate_rule_version=current_electorate_rule_version(TEMPLATE_PROFESSIONAL),
            professional_domain=self.finance_domain,
            start_at=now,
            deadline_at=now + timedelta(days=7),
        )

    def _assign(self, member, role) -> None:
        create_role_assignment(member=member, role=role)

    def test_model_version_and_tuple_projection_only_contains_new_direct_facts(self) -> None:
        tuples = {
            (item["user"], item["relation"], item["object"])
            for item in _unique_tuples(_project_authorization_tuples(platform_object="platform:test"))
        }

        self.assertEqual(OPENFGA_AUTHORIZATION_MODEL_VERSION, "2026-08-12-administrator-role-v1")
        self.assertIn((f"member:{self.deliberator.pk}", "covenanter", "platform:test"), tuples)
        self.assertIn((f"member:{self.deliberator.pk}", "deliberator", "platform:test"), tuples)
        self.assertNotIn((f"member:{self.deliberator.pk}", "administrator", "platform:test"), tuples)
        self.assertIn((f"member:{self.administrator.pk}", "administrator", "platform:test"), tuples)
        self.assertNotIn((f"member:{self.administrator.pk}", "deliberator", "platform:test"), tuples)
        self.assertIn(
            (f"member:{self.deliberator.pk}", "qualified_member", openfga_professional_domain_object(self.finance_domain)),
            tuples,
        )
        self.assertIn(
            ("platform:test", "platform", openfga_proposal_object(self.general_proposal)),
            tuples,
        )
        self.assertIn(
            ("platform:test", "platform", openfga_proposal_object(self.professional_proposal)),
            tuples,
        )
        self.assertIn((f"member:{self.deliberator.pk}", "eligible_member", openfga_proposal_object(self.professional_proposal)), tuples)
        self.assertFalse(any("投票者" in user or "voter" in user for user, _relation, _object in tuples))

    @override_settings(
        BIG_APPLE_AUTHORIZATION_BACKEND="openfga",
        OPENFGA_SIM_STORE_ID="store-id",
        OPENFGA_SIM_AUTHORIZATION_MODEL_ID="model-id",
    )
    def test_authorization_service_checks_general_proposal_capability(self) -> None:
        with patch("core.authorization_services.OpenFGAClient") as client_class:
            client_class.return_value.check.return_value = True

            allowed = AuthorizationService().member_can_vote_on_proposal(
                member=self.deliberator,
                proposal=self.general_proposal,
            )

        self.assertTrue(allowed)
        client_class.return_value.check.assert_called_once_with(
            store_id="store-id",
            authorization_model_id="model-id",
            user=f"member:{self.deliberator.pk}",
            relation="can_vote",
            object_=openfga_proposal_object(self.general_proposal),
        )

    @override_settings(BIG_APPLE_AUTHORIZATION_BACKEND="openfga", OPENFGA_SIM_STORE_ID="")
    def test_authorization_service_fails_closed_for_unconfigured_proposal_check(self) -> None:
        self.assertFalse(
            AuthorizationService().member_can_vote_on_proposal(
                member=self.deliberator,
                proposal=self.professional_proposal,
            )
        )

    def test_expired_or_revoked_direct_facts_are_not_projected(self) -> None:
        deliberator_assignment = self.deliberator.role_assignments.get(role=self.deliberator_role)
        revoke_role_assignment(assignment=deliberator_assignment, revoked_by=self.administrator)
        self.qualification.status = self.qualification.Status.REVOKED
        self.qualification.save(update_fields=["status", "updated_at"])

        tuples = {
            (item["user"], item["relation"], item["object"])
            for item in _unique_tuples(_project_authorization_tuples(platform_object="platform:test"))
        }

        self.assertNotIn((f"member:{self.deliberator.pk}", "deliberator", "platform:test"), tuples)
        self.assertNotIn(
            (f"member:{self.deliberator.pk}", "qualified_member", openfga_professional_domain_object(self.finance_domain)),
            tuples,
        )
