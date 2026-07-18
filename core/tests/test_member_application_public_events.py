"""Test public observer Event creation for member application lifecycle."""

from __future__ import annotations

from django.test import TestCase

from core.application_services import (
    admit_member_application_from_proposal,
    reject_member_application_from_failed_proposal,
    submit_member_application,
)
from core.event_payloads import public_member_label
from core.models import Event, MemberApplication, Proposal, ProposalVote
from core.tests.helpers import create_governance_admin_member, login_as_member


def _submit(governance_member, **overrides):
    """Helper that submits and returns the application with a logged-in governance member."""
    defaults = {
        "applicant_name": "测试公开事件报名者",
        "contact": "pub-event@example.test",
        "motivation": "希望加入社区。",
        "role_gap": "community_contributor",
        "availability_slots": ["weekend"],
        "requested_member_no": "pub-event-member",
        "account_username": "",
        "account_password": "",
        "metadata": {},
    }
    defaults.update(overrides)
    application = submit_member_application(**defaults)
    # Ensure governance can vote by setting eligible voters
    proposal = application.admission_proposal
    governance_pk = str(governance_member.pk)
    proposal.eligible_voters_snapshot_json = [governance_pk]
    proposal.save(update_fields=["eligible_voters_snapshot_json"])
    return application


class MemberApplicationPublicEventsTests(TestCase):
    """Public Event creation for submitted / admitted / rejected stages."""

    def setUp(self) -> None:
        self.governance = create_governance_admin_member("pub-event-gov")
        login_as_member(self.client, self.governance)

    # --- desensitization -------------------------------------------------------

    def test_public_member_label_one_char(self):
        self.assertEqual(public_member_label("a"), "*")

    def test_public_member_label_two_chars(self):
        self.assertEqual(public_member_label("张三"), "张*")

    def test_public_member_label_three_chars(self):
        self.assertEqual(public_member_label("wzy"), "w**y")

    def test_public_member_label_four_chars(self):
        label = public_member_label("测试成员")
        self.assertNotEqual(label, "测试成员")
        self.assertEqual(label[0], "测")
        self.assertEqual(label[-1], "员")

    # --- submitted -------------------------------------------------------------

    def test_submit_creates_public_event(self):
        application = _submit(self.governance)
        event_id = f"member-application-submitted-{application.application_id}"
        event = Event.objects.filter(event_id=event_id).first()
        self.assertIsNotNone(event)
        self.assertEqual(event.visibility, Event.Visibility.PUBLIC)
        self.assertEqual(event.generated_by, Event.GeneratedBy.LIVE_OS)
        self.assertEqual(event.title, "收到成员报名")
        self.assertEqual(event.payload.get("stage"), "submitted")
        self.assertNotIn("contact", event.payload)
        label = event.payload.get("public_applicant_label", "")
        self.assertNotEqual(label, application.applicant_name)

    def test_submit_public_event_is_idempotent(self):
        application = _submit(self.governance)
        event_id = f"member-application-submitted-{application.application_id}"
        count_before = Event.objects.filter(event_id=event_id).count()
        self.assertEqual(count_before, 1)
        # Re-invoke the helper indirectly by checking it again
        from core.application_services import _append_member_application_public_event_once
        _append_member_application_public_event_once(
            event_id=event_id, title="x", summary="x",
            severity=Event.Severity.INFO, payload={},
        )
        self.assertEqual(Event.objects.filter(event_id=event_id).count(), 1)

    # --- admitted --------------------------------------------------------------

    def test_admit_creates_public_event(self):
        application = _submit(self.governance)
        proposal = application.admission_proposal
        # Cast only yes vote so proposal passes
        ProposalVote.objects.create(
            proposal=proposal, voter_member=self.governance,
            choice=ProposalVote.Choice.YES, voted_at=proposal.start_at,
        )
        proposal.status = Proposal.Status.PASSED
        proposal.passed_at = proposal.start_at
        proposal.save()
        application = admit_member_application_from_proposal(
            application=application, proposal=proposal, executor_member=self.governance,
        )
        event_id = f"member-application-admitted-{application.application_id}"
        event = Event.objects.filter(event_id=event_id).first()
        self.assertIsNotNone(event)
        self.assertEqual(event.title, "新成员已加入")
        self.assertEqual(event.visibility, Event.Visibility.PUBLIC)
        self.assertIn("已通过准入表决", event.summary)
        self.assertNotIn("contact", event.payload)
        self.assertNotIn("username", event.payload)
        self.assertNotIn("account_user_id", event.payload)

    def test_admit_public_event_is_idempotent(self):
        application = _submit(self.governance)
        proposal = application.admission_proposal
        ProposalVote.objects.create(
            proposal=proposal, voter_member=self.governance,
            choice=ProposalVote.Choice.YES, voted_at=proposal.start_at,
        )
        proposal.status = Proposal.Status.PASSED
        proposal.passed_at = proposal.start_at
        proposal.save()
        application = admit_member_application_from_proposal(
            application=application, proposal=proposal, executor_member=self.governance,
        )
        event_id = f"member-application-admitted-{application.application_id}"
        self.assertEqual(Event.objects.filter(event_id=event_id).count(), 1)
        # Re-invoke the helper
        from core.application_services import _append_member_application_public_event_once
        _append_member_application_public_event_once(
            event_id=event_id, title="x", summary="x",
            severity=Event.Severity.INFO, payload={},
        )
        self.assertEqual(Event.objects.filter(event_id=event_id).count(), 1)

    # --- rejected --------------------------------------------------------------

    def test_reject_creates_public_event(self):
        application = _submit(self.governance)
        proposal = application.admission_proposal
        proposal.status = Proposal.Status.FAILED
        proposal.failed_at = proposal.start_at
        proposal.save()
        application = reject_member_application_from_failed_proposal(
            application=application, proposal=proposal,
        )
        event_id = f"member-application-rejected-{application.application_id}"
        event = Event.objects.filter(event_id=event_id).first()
        self.assertIsNotNone(event)
        self.assertEqual(event.title, "成员报名未通过")
        self.assertEqual(event.severity, Event.Severity.WARNING)
        reason = event.payload.get("reason", "")
        self.assertLessEqual(len(reason), 200)

    # --- observer context can see admitted event -------------------------------

    def test_observer_context_includes_admitted_event(self):
        application = _submit(self.governance)
        proposal = application.admission_proposal
        ProposalVote.objects.create(
            proposal=proposal, voter_member=self.governance,
            choice=ProposalVote.Choice.YES, voted_at=proposal.start_at,
        )
        proposal.status = Proposal.Status.PASSED
        proposal.passed_at = proposal.start_at
        proposal.save()
        admit_member_application_from_proposal(
            application=application, proposal=proposal, executor_member=self.governance,
        )
        from observer.page_context import observer_context
        context = observer_context()
        # theme-level events still contain the raw public Event (model instances)
        titles = {event.title for event in context["events"]}
        self.assertIn("新成员已加入", titles)

        # timeline_events now has aggregated member-app cards, not raw stage events
        timeline = context["command_dashboard"]["timeline_events"]
        ma_rows = [r for r in timeline if r.get("_member_application_detail_url")]
        self.assertTrue(len(ma_rows) > 0, "timeline must include a member application aggregated card")
        ma = ma_rows[0]
        self.assertEqual(ma["title"], "成员报名")
        self.assertEqual(
            ma["_member_application_detail_url"],
            f"/member-applications/{application.application_id}/",
        )
        self.assertEqual(ma["metric_value"], "已通过")
