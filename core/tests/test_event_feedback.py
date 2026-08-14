from concurrent.futures import ThreadPoolExecutor
from unittest import skipUnless
from unittest.mock import patch

from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from core.event_feedback_services import (
    can_view_submitter_identity, close_event_feedback, conclude_event_feedback,
    request_event_feedback_response, respond_to_event_feedback,
    start_event_feedback_verification, submit_event_feedback, withdraw_event_feedback,
)
from core.exceptions import DomainError
from core.models import Event, EventFeedback, SystemEvent
from core.tests.helpers import create_member


class EventFeedbackServiceTests(TestCase):
    def setUp(self):
        self.submitter = create_member("feedback-submitter")
        self.subject = create_member("feedback-subject")
        self.handler = create_member("feedback-handler")
        self.other = create_member("feedback-other")
        self.event = Event.objects.create(
            event_id="event-feedback-target", event_type=Event.EventType.SYSTEM,
            simulation_day=1, severity=Event.Severity.INFO, title="公开事件", summary="公开事实",
            occurred_at=timezone.now(), generated_by=Event.GeneratedBy.LIVE_OS,
            visibility=Event.Visibility.PUBLIC,
        )

    def test_non_public_identity_requires_reason(self):
        with self.assertRaisesMessage(DomainError, "必须说明理由"):
            submit_event_feedback(
                related_event=self.event, submitted_by=self.submitter,
                feedback_type=EventFeedback.FeedbackType.REPORT, statement="需要核实。",
                submitter_visibility=EventFeedback.SubmitterVisibility.HANDLERS_ONLY,
            )

    @patch("core.event_feedback_services.member_can_administer", return_value=False)
    def test_identity_scope_is_independent_from_public_feedback_content(self, _can_administer):
        feedback = submit_event_feedback(
            related_event=self.event, submitted_by=self.submitter, subject_member=self.subject,
            feedback_type=EventFeedback.FeedbackType.COMPLAINT, statement="需要核实。",
            submitter_visibility=EventFeedback.SubmitterVisibility.PARTIES_AND_HANDLERS,
            privacy_reason="担心现实关系干扰核实。",
        )
        self.assertFalse(can_view_submitter_identity(feedback, None))
        self.assertFalse(can_view_submitter_identity(feedback, self.other))
        self.assertTrue(can_view_submitter_identity(feedback, self.submitter))
        self.assertTrue(can_view_submitter_identity(feedback, self.subject))

    @patch("core.event_feedback_services.member_can_administer", return_value=True)
    def test_full_lifecycle_appends_ledger_and_preserves_original_event(self, _can_administer):
        original_summary = self.event.summary
        feedback = submit_event_feedback(
            related_event=self.event, submitted_by=self.submitter, subject_member=self.subject,
            feedback_type=EventFeedback.FeedbackType.CORRECTION, statement="事件记录有误。",
        )
        start_event_feedback_verification(feedback=feedback, handler=self.handler)
        request_event_feedback_response(feedback=feedback, handler=self.handler)
        respond_to_event_feedback(feedback=feedback, responder=self.subject, response_statement="已提供说明。")
        conclude_event_feedback(
            feedback=feedback, handler=self.handler,
            conclusion=EventFeedback.Conclusion.PARTLY_CONFIRMED,
            conclusion_reason="部分记录需要通过领域流程纠正。",
        )
        close_event_feedback(feedback=feedback, handler=self.handler)
        feedback.refresh_from_db(); self.event.refresh_from_db()
        self.assertEqual(feedback.status, EventFeedback.Status.CLOSED)
        self.assertEqual(self.event.summary, original_summary)
        self.assertEqual(SystemEvent.objects.filter(aggregate_type="EventFeedback", aggregate_id=feedback.pk).count(), 6)

    def test_submitter_can_only_withdraw_unprocessed_feedback(self):
        feedback = submit_event_feedback(
            related_event=self.event, submitted_by=self.submitter,
            feedback_type=EventFeedback.FeedbackType.OPINION, statement="建议补充说明。",
        )
        withdraw_event_feedback(feedback=feedback, submitted_by=self.submitter)
        feedback.refresh_from_db()
        self.assertEqual(feedback.status, EventFeedback.Status.WITHDRAWN)
        with self.assertRaises(DomainError):
            withdraw_event_feedback(feedback=feedback, submitted_by=self.submitter)


@skipUnless(connection.vendor == "mysql", "并发行锁语义仅在 MySQL 测试数据库执行。")
class EventFeedbackConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.submitter = create_member("feedback-race-submitter")
        self.handler_a = create_member("feedback-race-handler-a")
        self.handler_b = create_member("feedback-race-handler-b")
        self.event = Event.objects.create(
            event_id="event-feedback-race", event_type=Event.EventType.SYSTEM,
            simulation_day=1, severity=Event.Severity.INFO, title="并发事件", summary="并发事件",
            occurred_at=timezone.now(), generated_by=Event.GeneratedBy.LIVE_OS,
            visibility=Event.Visibility.PUBLIC,
        )
        self.feedback = submit_event_feedback(
            related_event=self.event, submitted_by=self.submitter,
            feedback_type=EventFeedback.FeedbackType.REPORT, statement="并发核实测试。",
        )

    def _start(self, handler):
        close_old_connections()
        try:
            current = EventFeedback.objects.get(pk=self.feedback.pk)
            start_event_feedback_verification(feedback=current, handler=handler)
            return "ok"
        except DomainError:
            return "rejected"
        finally:
            close_old_connections()

    @patch("core.event_feedback_services.member_can_administer", return_value=True)
    def test_concurrent_verification_creates_one_transition_fact(self, _can_administer):
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(self._start, [self.handler_a, self.handler_b]))

        self.assertCountEqual(results, ["ok", "rejected"])
        self.feedback.refresh_from_db()
        self.assertIn(self.feedback.assigned_handler_id, {self.handler_a.pk, self.handler_b.pk})
        self.assertEqual(
            SystemEvent.objects.filter(
                aggregate_type="EventFeedback",
                aggregate_id=self.feedback.pk,
                event_type=SystemEvent.EventType.EVENT_FEEDBACK_VERIFICATION_STARTED,
            ).count(),
            1,
        )
