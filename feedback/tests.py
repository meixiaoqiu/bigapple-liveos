"""Tests for community feedback lifecycle."""

from __future__ import annotations

from django.test import TestCase
from django.utils import timezone

from core.exceptions import DomainError
from core.feedback_services import (
    hide_feedback,
    link_feedback_to_proposal,
    respond_to_feedback,
    submit_feedback,
)
from core.models import CommunityFeedback, Event, Member, Organization, Proposal, Role
from core.tests.helpers import create_governance_admin_member, create_member, login_as_member
from observer.event_context import public_event_semantic_summary


class FeedbackServiceTests(TestCase):
    """Cover service-layer authority boundaries."""

    def setUp(self):
        self.member = create_member("fb-author", display_name="反馈作者")

    def test_submit_feedback_success(self):
        fb = submit_feedback(
            author_member=self.member, title="测试", category="suggestion", body="正文",
        )
        self.assertEqual(fb.status, CommunityFeedback.Status.OPEN)
        self.assertEqual(fb.author_member, self.member)

    def test_submit_feedback_creates_public_event(self):
        fb = submit_feedback(
            author_member=self.member, title="事件测试", category="question", body="body",
        )
        event = Event.objects.get(
            event_id=f"community-feedback-submitted-{fb.feedback_id}",
        )
        self.assertEqual(event.payload["source"], "community_feedback")
        self.assertEqual(event.payload["feedback_id"], fb.feedback_id)
        self.assertEqual(event.payload["feedback_category_label"], "问题")
        self.assertEqual(event.payload["public_author_label"], self.member.member_no)

    def test_invalid_category_rejected(self):
        with self.assertRaises(DomainError):
            submit_feedback(
                author_member=self.member, title="x", category="bad-category", body="x",
            )

    def test_suspended_member_cannot_submit(self):
        self.member.status = Member.Status.SUSPENDED
        self.member.save(update_fields=["status"])
        with self.assertRaises(DomainError):
            submit_feedback(author_member=self.member, title="x", category="other", body="x")

    def test_exited_member_cannot_submit(self):
        self.member.status = Member.Status.EXITED
        self.member.save(update_fields=["status"])
        with self.assertRaises(DomainError):
            submit_feedback(author_member=self.member, title="x", category="other", body="x")

    def test_non_governance_cannot_respond(self):
        fb = submit_feedback(author_member=self.member, title="t", category="other", body="b")
        with self.assertRaises(DomainError):
            respond_to_feedback(feedback=fb, responder_member=self.member, response="resp")

    def test_governance_can_respond(self):
        gov = create_governance_admin_member("gov-resp")
        fb = submit_feedback(author_member=self.member, title="t", category="other", body="b")
        fb2 = respond_to_feedback(feedback=fb, responder_member=gov, response="已处理")
        self.assertEqual(fb2.status, CommunityFeedback.Status.ANSWERED)
        self.assertEqual(fb2.responded_by, gov)
        self.assertIsNotNone(fb2.responded_at)
        self.assertIn("已处理", fb2.official_response)

    def test_respond_creates_public_event(self):
        gov = create_governance_admin_member("gov-resp2")
        fb = submit_feedback(author_member=self.member, title="tt", category="other", body="bb")
        respond_to_feedback(feedback=fb, responder_member=gov, response="ok")
        event = Event.objects.get(
            event_id__startswith=f"community-feedback-answered-{fb.feedback_id}-",
        )
        self.assertEqual(event.payload["source"], "community_feedback")
        self.assertEqual(event.payload["feedback_status_label"], "已回应")

    def test_repeated_response_creates_distinct_public_events(self):
        gov = create_governance_admin_member("gov-repeat")
        fb = submit_feedback(author_member=self.member, title="repeat", category="other", body="bb")
        respond_to_feedback(feedback=fb, responder_member=gov, response="first")
        respond_to_feedback(feedback=fb, responder_member=gov, response="second")

        self.assertEqual(
            Event.objects.filter(
                event_id__startswith=f"community-feedback-answered-{fb.feedback_id}-",
            ).count(),
            2,
        )

    def test_invalid_response_status_rejected(self):
        gov = create_governance_admin_member("gov-bad-status")
        fb = submit_feedback(author_member=self.member, title="bad", category="other", body="bb")
        with self.assertRaises(DomainError):
            respond_to_feedback(
                feedback=fb, responder_member=gov, response="x", status="bad-status",
            )

    def test_respond_cannot_hide_feedback(self):
        gov = create_governance_admin_member("gov-hide-status")
        fb = submit_feedback(author_member=self.member, title="bad", category="other", body="bb")
        with self.assertRaises(DomainError):
            respond_to_feedback(
                feedback=fb,
                responder_member=gov,
                response="x",
                status=CommunityFeedback.Status.HIDDEN,
            )

    def test_respond_cannot_link_feedback_without_proposal(self):
        gov = create_governance_admin_member("gov-link-status")
        fb = submit_feedback(author_member=self.member, title="bad", category="other", body="bb")
        with self.assertRaises(DomainError):
            respond_to_feedback(
                feedback=fb,
                responder_member=gov,
                response="x",
                status=CommunityFeedback.Status.LINKED,
            )

    def test_answered_requires_response_text(self):
        gov = create_governance_admin_member("gov-empty-answer")
        fb = submit_feedback(author_member=self.member, title="empty", category="other", body="bb")
        with self.assertRaises(DomainError):
            respond_to_feedback(
                feedback=fb,
                responder_member=gov,
                response=" ",
                status=CommunityFeedback.Status.ANSWERED,
            )

    def test_hide_feedback(self):
        gov = create_governance_admin_member("gov-hide")
        fb = submit_feedback(author_member=self.member, title="hide me", category="other", body="bad")
        hide_feedback(feedback=fb, actor_member=gov, reason="违规")
        fb.refresh_from_db()
        self.assertEqual(fb.status, CommunityFeedback.Status.HIDDEN)

    def test_hide_does_not_write_public_event(self):
        gov = create_governance_admin_member("gov-hide2")
        fb = submit_feedback(author_member=self.member, title="x", category="other", body="y")
        before = Event.objects.count()
        hide_feedback(feedback=fb, actor_member=gov)
        self.assertEqual(Event.objects.count(), before)

    def test_hide_feedback_removes_existing_public_events(self):
        gov = create_governance_admin_member("gov-hide-events")
        fb = submit_feedback(author_member=self.member, title="hide event", category="other", body="bad")

        hide_feedback(feedback=fb, actor_member=gov)

        self.assertFalse(
            Event.objects.filter(
                event_id__contains=fb.feedback_id,
                visibility=Event.Visibility.PUBLIC,
            ).exists()
        )

    def test_link_feedback_to_proposal(self):
        gov = create_governance_admin_member("gov-link")
        fb = submit_feedback(author_member=self.member, title="link", category="proposal_seed", body="p")
        org = Organization.objects.create(name="TestOrg")
        role = Role.objects.create(name="Test", organization=org, status=Role.Status.ACTIVE)
        proposal = Proposal.objects.create(
            title="提案", proposal_type=Proposal.ProposalType.POLICY,
            status=Proposal.Status.VOTING, proposer_member=gov,
            start_at=timezone.now(), deadline_at=timezone.now() + timezone.timedelta(days=7),
            pass_ratio=50, proposal_no="0001",
        )
        link_feedback_to_proposal(feedback=fb, proposal=proposal, actor_member=gov)
        fb.refresh_from_db()
        self.assertEqual(fb.status, CommunityFeedback.Status.LINKED)
        self.assertEqual(fb.linked_proposal, proposal)

    def test_non_governance_cannot_hide(self):
        fb = submit_feedback(author_member=self.member, title="x", category="other", body="y")
        with self.assertRaises(DomainError):
            hide_feedback(feedback=fb, actor_member=self.member)


class FeedbackViewTests(TestCase):
    """Cover view-layer boundaries."""

    def setUp(self):
        self.author = create_member("fb-view-author", display_name="视图作者")
        self.fb = submit_feedback(author_member=self.author, title="公开反馈", category="suggestion", body="正文内容")

    def test_list_unauthenticated_200(self):
        self.assertEqual(self.client.get("/feedback/").status_code, 200)

    def test_list_shows_feedback(self):
        response = self.client.get("/feedback/")
        self.assertContains(response, "公开反馈")

    def test_new_redirects_unauthenticated(self):
        response = self.client.get("/feedback/new/")
        self.assertEqual(response.status_code, 302)

    def test_new_authenticated_200(self):
        login_as_member(self.client, self.author)
        self.assertEqual(self.client.get("/feedback/new/").status_code, 200)

    def test_new_authenticated_post_creates(self):
        login_as_member(self.client, self.author)
        response = self.client.post("/feedback/new/", {
            "title": "新反馈", "category": "question", "body": "请问",
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "新反馈")

    def test_detail_shows_content(self):
        response = self.client.get(f"/feedback/{self.fb.feedback_id}/")
        self.assertContains(response, "公开反馈")
        self.assertContains(response, "正文内容")

    def test_detail_shows_author_link(self):
        response = self.client.get(f"/feedback/{self.fb.feedback_id}/")
        self.assertContains(response, f"/u/{self.author.member_no}/")

    def test_hidden_feedback_404_for_normal_user(self):
        gov = create_governance_admin_member("gov-hide-view")
        fb = submit_feedback(author_member=self.author, title="hidden", category="other", body="h")
        hide_feedback(feedback=fb, actor_member=gov)
        response = self.client.get(f"/feedback/{fb.feedback_id}/")
        self.assertEqual(response.status_code, 404)

    def test_governance_sees_response_form(self):
        gov = create_governance_admin_member("gov-view-form")
        login_as_member(self.client, gov)
        response = self.client.get(f"/feedback/{self.fb.feedback_id}/")
        self.assertContains(response, "发布回应")

    def test_normal_user_does_not_see_response_form(self):
        login_as_member(self.client, self.author)
        response = self.client.get(f"/feedback/{self.fb.feedback_id}/")
        self.assertNotContains(response, "发布回应")

    def test_respond_normal_user_403(self):
        login_as_member(self.client, self.author)
        response = self.client.post(f"/feedback/{self.fb.feedback_id}/respond/", {
            "action": "respond", "status": "answered", "official_response": "resp",
        })
        self.assertEqual(response.status_code, 403)

    def test_respond_governance_success(self):
        gov = create_governance_admin_member("gov-respond-view")
        login_as_member(self.client, gov)
        response = self.client.post(f"/feedback/{self.fb.feedback_id}/respond/", {
            "action": "respond", "status": "answered", "official_response": "已处理",
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "已处理")

    def test_respond_answered_without_text_shows_error(self):
        gov = create_governance_admin_member("gov-empty-view")
        login_as_member(self.client, gov)
        response = self.client.post(f"/feedback/{self.fb.feedback_id}/respond/", {
            "action": "respond", "status": "answered", "official_response": " ",
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "发布正式回应时必须填写回应内容")
        self.fb.refresh_from_db()
        self.assertEqual(self.fb.status, CommunityFeedback.Status.OPEN)

    def test_page_does_not_leak_sensitive_fields(self):
        response = self.client.get(f"/feedback/{self.fb.feedback_id}/")
        content = response.content.decode().lower()
        self.assertNotIn("email", content)
        self.assertNotIn("contact", content)
        self.assertNotIn("password", content)
        self.assertNotIn("user_id", content)
        self.assertNotIn("member_id", content)
        self.assertNotIn("proposal_id", content)

    def test_page_uses_runtime_header(self):
        response = self.client.get("/feedback/")
        self.assertNotContains(response, 'href="/logout/"')

    def test_feedback_pages_do_not_use_inline_onclick(self):
        list_response = self.client.get("/feedback/")
        detail_response = self.client.get(f"/feedback/{self.fb.feedback_id}/")
        self.assertNotContains(list_response, "onclick=")
        self.assertNotContains(detail_response, "onclick=")

    def test_feedback_list_has_explicit_detail_link(self):
        response = self.client.get("/feedback/")
        self.assertContains(response, "查看详情")
        self.assertContains(response, f'/feedback/{self.fb.feedback_id}/')

    def test_feedback_event_has_semantic_summary(self):
        event = Event.objects.get(
            event_id=f"community-feedback-submitted-{self.fb.feedback_id}",
        )

        summary = public_event_semantic_summary(event)

        self.assertIn({"label": "事项", "value": "收到公开反馈"}, summary)
        self.assertIn({"label": "反馈人", "value": self.author.member_no}, summary)
        self.assertIn({"label": "类别", "value": "建议"}, summary)

    def test_homepage_shows_feedback(self):
        response = self.client.get("/")
        self.assertContains(response, "社区反馈")
        self.assertContains(response, "公开反馈")

    def test_hidden_not_in_feedback_list(self):
        """Hidden feedback 不进入 /feedback/ 公开列表。"""
        gov = create_governance_admin_member("gov-list-hide")
        fb2 = submit_feedback(author_member=self.author, title="隐藏条目", category="other", body="h")
        hide_feedback(feedback=fb2, actor_member=gov)
        response = self.client.get("/feedback/")
        self.assertNotContains(response, "隐藏条目")

    def test_hidden_feedback_event_not_in_public_event_stream(self):
        gov = create_governance_admin_member("gov-event-hide")
        fb2 = submit_feedback(author_member=self.author, title="事件隐藏条目", category="other", body="h")
        hide_feedback(feedback=fb2, actor_member=gov)

        response = self.client.get("/events/")

        self.assertNotContains(response, "事件隐藏条目")
