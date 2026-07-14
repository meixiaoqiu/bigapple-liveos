from __future__ import annotations

from django.test import TestCase

from simulation.zero_start_observations import (
    build_hour_payload,
    combined_next_actions,
    observation_window_summary,
    observation_window_title,
    pre_engineering_blockers,
    startup_gate_blockers,
)


class ZeroStartObservationsTests(TestCase):
    """Tests for simulation.zero_start_observations."""

    def _gate(self, missing_caps=None, missing_docs=None, satisfied=False):
        return {
            "startup_gate_satisfied": satisfied,
            "project_phase": "ready_to_start" if satisfied else "preparation",
            "missing_capabilities": missing_caps or [],
            "missing_document_signers": missing_docs or [],
        }

    def _pe(self, completed=False):
        return {"status": "completed" if completed else "running", "completed": completed}

    # startup_gate_blockers

    def test_startup_gate_blockers_lists_missing_capabilities_and_signers(self):
        gate = self._gate(
            missing_caps=[{"code": "cooking", "name": "做饭"}],
            missing_docs=[{"code": "structural", "name": "结构安全"}],
        )
        blockers = startup_gate_blockers(gate)
        kinds = {b["kind"] for b in blockers}
        self.assertEqual(kinds, {"capability", "document_signer"})
        self.assertEqual(len(blockers), 2)

    def test_startup_gate_blockers_empty_when_nothing_missing(self):
        gate = self._gate()
        blockers = startup_gate_blockers(gate)
        self.assertEqual(blockers, [])

    # pre_engineering_blockers

    def test_pre_engineering_blockers_lists_incomplete_items(self):
        milestones = [
            {"code": "grid", "name": "并网预筛", "completed": True},
            {"code": "legal", "name": "法律审查", "completed": False},
        ]
        blockers = pre_engineering_blockers(milestones)
        self.assertEqual(len(blockers), 1)
        self.assertEqual(blockers[0]["code"], "legal")
        self.assertEqual(blockers[0]["kind"], "pre_engineering")

    # combined_next_actions

    def test_combined_next_actions_prefers_gate_over_pe(self):
        gate = self._gate(
            missing_caps=[{"code": "cooking", "name": "做饭"}],
        )
        pe = self._pe(completed=False)
        actions = combined_next_actions(gate, pe)
        # gate not satisfied, so gate actions take precedence
        self.assertIn("继续通过自媒体报名", actions[0])

    def test_combined_next_actions_uses_pe_actions_when_gate_satisfied(self):
        gate = self._gate(satisfied=True)
        pe = {"status": "running", "next_actions": ["完成并网预筛。"]}
        actions = combined_next_actions(gate, pe)
        self.assertEqual(actions, ["完成并网预筛。"])

    # observation window

    def test_observation_window_title_and_summary_gate_not_satisfied(self):
        gate = self._gate()
        pe = {}
        self.assertIn("报名筛选观察窗口结束", observation_window_title(gate=gate, pre_engineering=pe))
        self.assertIn("继续停留在筹备阶段", observation_window_summary(gate=gate, pre_engineering=pe))

    def test_observation_window_title_and_summary_pre_engineering_completed(self):
        gate = self._gate(satisfied=True)
        pe = self._pe(completed=True)
        self.assertIn("责任闭环观察窗口结束", observation_window_title(gate=gate, pre_engineering=pe))
        self.assertIn("责任文件取得", observation_window_summary(gate=gate, pre_engineering=pe))

    # build_hour_payload

    def test_build_hour_payload_keeps_existing_shape(self):
        class FakeRun:
            run_id = "sim-run-test-observations"

        fake_run = FakeRun()
        gate = self._gate()
        pe = {}
        summary = {"registered_applicants": 3, "candidate_members": 1}

        payload = build_hour_payload(
            run=fake_run,
            hour=10,
            applied=[],
            partner_applied=[],
            screening_rows=[],
            partner_screening_rows=[],
            candidate_summary=summary,
            startup_gate=gate,
            pre_engineering=pe,
            simulation_day=1,
            driver_mode="form",
            candidate_status="candidate",
        )
        self.assertEqual(payload["scenario"], "zero_start")
        self.assertEqual(payload["simulation_hour"], 10)
        self.assertEqual(payload["driver_mode"], "form")
        self.assertIn("virtual_time", payload)
        self.assertIn("funnel_delta", payload)
        self.assertIn("candidate_summary", payload)
        self.assertIn("startup_gate", payload)
        self.assertIn("blockers", payload)
        self.assertIn("next_actions", payload)
        self.assertIn("state_machine", payload)
