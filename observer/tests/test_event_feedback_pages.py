from django.test import TestCase
from django.utils import timezone

from core.models import Event, EventFeedback
from core.tests.helpers import create_member, login_as_member


class EventFeedbackPageTests(TestCase):
    def setUp(self):
        self.member = create_member("feedback-page-member")
        self.event = Event.objects.create(
            event_id="event-feedback-page", event_type=Event.EventType.SYSTEM,
            simulation_day=1, severity=Event.Severity.INFO, title="公开事件", summary="事件正文",
            occurred_at=timezone.now(), generated_by=Event.GeneratedBy.LIVE_OS,
            visibility=Event.Visibility.PUBLIC,
        )

    def test_anonymous_event_detail_is_read_only(self):
        response = self.client.get(f"/events/{self.event.event_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "登录后可反馈此事件")
        self.assertNotContains(response, "反馈此事件</button>")

    def test_logged_in_member_submits_feedback_fixed_to_event(self):
        login_as_member(self.client, self.member)
        response = self.client.post(f"/events/{self.event.event_id}/", {
            "feedback_type": EventFeedback.FeedbackType.RISK,
            "statement": "该事件反映了未来风险。",
            "requested_outcome": "请制定预防措施。",
            "submitter_visibility": EventFeedback.SubmitterVisibility.PUBLIC,
        })
        feedback = EventFeedback.objects.get()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(feedback.related_event, self.event)
        self.assertEqual(response.headers["Location"], f"/event-feedbacks/{feedback.feedback_id}/")

    def test_old_disputes_api_and_workspace_route_do_not_exist(self):
        self.assertEqual(self.client.post("/api/v0.1/disputes", data="{}", content_type="application/json").status_code, 404)
        self.assertEqual(self.client.post("/workspace/disputes/").status_code, 404)

    def test_raw_member_content_is_hidden_from_public_but_visible_to_party(self):
        subject = create_member("feedback-page-subject")
        feedback = EventFeedback.objects.create(
            feedback_id="feedback-private-content", related_event=self.event,
            feedback_type=EventFeedback.FeedbackType.REPORT,
            status=EventFeedback.Status.AWAITING_RESPONSE,
            submitted_by=self.member, subject_member=subject,
            statement="第三方张某患有某疾病，凭据 secret-123。",
            requested_outcome="公开张某全部资料。",
            response_statement="回应中也包含医疗隐私。",
            submitted_at=timezone.now(),
        )

        anonymous = self.client.get(f"/event-feedbacks/{feedback.feedback_id}/")
        self.assertContains(anonymous, "详细内容仅相关方和处理人可见")
        self.assertNotContains(anonymous, "张某")
        self.assertNotContains(anonymous, "secret-123")
        event_page = self.client.get(f"/events/{self.event.event_id}/")
        self.assertNotContains(event_page, "secret-123")

        login_as_member(self.client, subject)
        party = self.client.get(f"/event-feedbacks/{feedback.feedback_id}/")
        self.assertContains(party, "secret-123")
        self.assertContains(party, "回应中也包含医疗隐私")

    def test_public_conclusion_displays_named_responsible_member(self):
        handler = create_member("feedback-public-concluder")
        feedback = EventFeedback.objects.create(
            feedback_id="feedback-public-conclusion", related_event=self.event,
            feedback_type=EventFeedback.FeedbackType.CORRECTION,
            status=EventFeedback.Status.CONCLUDED,
            submitted_by=self.member, statement="原始内容不公开。",
            conclusion=EventFeedback.Conclusion.CONFIRMED,
            conclusion_reason="经核实，事件摘要需要后续纠正。",
            concluded_by=handler,
            concluded_at=timezone.now(), submitted_at=timezone.now(),
        )

        response = self.client.get(f"/event-feedbacks/{feedback.feedback_id}/")

        self.assertContains(response, "结论责任人")
        self.assertContains(response, handler.member_no)
        self.assertContains(response, "经核实，事件摘要需要后续纠正")
        self.assertNotContains(response, "原始内容不公开")
