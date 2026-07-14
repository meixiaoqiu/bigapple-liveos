from __future__ import annotations

from django.test import TestCase

from simulation.zero_start_strategy import (
    STARTUP_CAPABILITY_REQUIREMENTS,
    STARTUP_DOCUMENT_SIGNER_REQUIREMENTS,
    ApplicantSpec,
    applicant_specs_for_hours,
    partner_specs_for_hours,
    screening_decision,
)


class ZeroStartStrategyTests(TestCase):
    """Tests for simulation.zero_start_strategy configuration and functions."""

    # applicant_specs_for_hours

    def test_applicant_specs_for_hours_filters_by_hours(self) -> None:
        specs = applicant_specs_for_hours(168)
        early_count = len([s for s in specs if s.apply_hour < 96])
        later_count = len([s for s in specs if s.apply_hour >= 96])
        self.assertEqual(early_count, 6)
        self.assertGreater(later_count, early_count)

    # partner_specs_for_hours

    def test_partner_specs_for_hours_grows_with_hours(self) -> None:
        early = partner_specs_for_hours(168)
        later = partner_specs_for_hours(720)
        self.assertEqual(len(early), 3)
        self.assertGreater(len(later), 10)
        domains = {
            d
            for s in later
            if s.can_issue_responsibility_documents
            for d in s.responsibility_document_domains
        }
        self.assertIn("structural_safety_document", domains)
        self.assertIn("pv_system_design_document", domains)
        self.assertIn("electrical_grid_document", domains)
        self.assertIn("construction_safety_quality_document", domains)
        self.assertIn("acceptance_archive_document", domains)

    # screening_decision

    def _spec(self, availability: int, capability_scores: dict, withdraw_hour: int | None = None) -> ApplicantSpec:
        return ApplicantSpec(
            index=1,
            apply_hour=0,
            screen_hour=10,
            display_name="test",
            motivation="test",
            capability_scores=capability_scores,
            availability_hours_per_week=availability,
            withdraw_hour=withdraw_hour,
        )

    def test_screening_decision_candidate(self) -> None:
        spec = self._spec(20, {"做饭": 78})
        self.assertEqual(screening_decision(spec=spec, screened_hour=10), "candidate")

    def test_screening_decision_standby(self) -> None:
        spec = self._spec(6, {"做饭": 78})  # matches capability but < 8 hours
        self.assertEqual(screening_decision(spec=spec, screened_hour=10), "standby")

    def test_screening_decision_rejected(self) -> None:
        spec = self._spec(2, {"兴趣": 30})
        self.assertEqual(screening_decision(spec=spec, screened_hour=10), "rejected")

    def test_screening_decision_withdrew(self) -> None:
        spec = self._spec(20, {"做饭": 78}, withdraw_hour=5)
        self.assertEqual(screening_decision(spec=spec, screened_hour=10), "withdrew")

    # requirement constant shapes

    def test_capability_requirements_have_expected_keys(self) -> None:
        for req in STARTUP_CAPABILITY_REQUIREMENTS:
            self.assertIn("code", req)
            self.assertIn("name", req)
            self.assertIn("min_count", req)
            self.assertIn("skill_aliases", req)

    def test_document_signer_requirements_have_expected_keys(self) -> None:
        for req in STARTUP_DOCUMENT_SIGNER_REQUIREMENTS:
            self.assertIn("code", req)
            self.assertIn("name", req)
            self.assertIn("document_examples", req)
            self.assertIn("acceptable_signers", req)
