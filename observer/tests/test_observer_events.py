from __future__ import annotations

from django.test import TestCase
from django.utils import timezone

from core.event_ledger import append_event
from core.models import Member, SystemEvent
from core.tests.helpers import create_member


class PublicEventsBrowserTests(TestCase):
    """Cover observer public system event browser list and detail pages."""

    def events_list_url(self) -> str:
        return "/observer/events/"

    def event_detail_url(self, seq: int) -> str:
        return f"/observer/events/{seq}/"

    def setUp(self) -> None:
        self.member = create_member(
            member_no="mem-evts-0001",
            role_name="contributor",
            status=Member.Status.ADMITTED,
            profile={"display_name": "测试人"},
            created_at=timezone.now(),
        )

    def _create_event(
        self,
        event_type: str = SystemEvent.EventType.MEMBER_CREATED,
        aggregate_type: str = "Member",
        aggregate_id: str = "mem-evts-0001",
        payload_json: dict | None = None,
        occurred_at=None,
    ) -> SystemEvent:
        return append_event(
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            actor_member=self.member,
            payload_json=payload_json or {},
            occurred_at=occurred_at or timezone.now(),
        )

    # ---- list page -------------------------------------------------------

    def test_events_list_accessible(self):
        self._create_event()
        response = self.client.get(self.events_list_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "公共事件浏览器")
        self.assertContains(response, "公开展示治理和运行事件的脱敏审计记录")

    def test_events_list_shows_event_row(self):
        event = self._create_event()
        response = self.client.get(self.events_list_url())
        self.assertEqual(response.status_code, 200)
        seq_str = str(event.seq)
        self.assertContains(response, seq_str)
        self.assertContains(response, event.get_event_type_display())

    def test_events_list_has_detail_link(self):
        event = self._create_event()
        response = self.client.get(self.events_list_url())
        self.assertContains(response, f'/observer/events/{event.seq}/"')

    def test_events_list_empty(self):
        # Clean up events created by setUp signals first.
        SystemEvent.objects.all().delete()
        response = self.client.get(self.events_list_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "暂无公开审计事件")

    # ---- detail page -----------------------------------------------------

    def test_event_detail_accessible(self):
        event = self._create_event()
        response = self.client.get(self.event_detail_url(event.seq))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"事件 #{event.seq}")
        self.assertContains(response, event.event_hash)
        self.assertContains(response, event.payload_hash)
        self.assertContains(response, event.prev_hash)

    def test_event_detail_not_found(self):
        response = self.client.get(self.event_detail_url(99999))
        self.assertEqual(response.status_code, 404)

    # ---- payload sanitisation --------------------------------------------

    def test_payload_sensitive_fields_hidden(self):
        payload = {
            "contact": "test@example.com",
            "email": "someone@example.com",
            "username": "admin",
            "password": "s3cret",
            "password1": "abc",
            "password2": "def",
            "account_user_id": "uuid-sensitive",
            "member_id": 42,
            "target_member_id": 7,
            "voter_member_id": 3,
            "actor_member_id": 1,
            "application_id": "app-123",
            "stage": "screening",
            "public_member_label": "张*三",
        }
        event = self._create_event(payload_json=payload)
        response = self.client.get(self.event_detail_url(event.seq))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "test@example.com")
        self.assertNotContains(response, "someone@example.com")
        self.assertNotContains(response, "s3cret")
        self.assertNotContains(response, "uuid-sensitive")
        self.assertNotContains(response, "admin")
        # Whitelist keys should appear.
        self.assertContains(response, "app-123")
        self.assertContains(response, "screening")
        self.assertContains(response, "张*三")

    def test_payload_reason_truncated(self):
        long_reason = "A" * 300
        payload = {"reason": long_reason}
        event = self._create_event(payload_json=payload)
        response = self.client.get(self.event_detail_url(event.seq))
        self.assertContains(response, "A" * 200 + "…")
        self.assertNotContains(response, "A" * 201)

    # ---- actor member de-identification ----------------------------------

    def test_actor_member_deidentified(self):
        self.member.display_name = "张三丰"
        self.member.save()
        event = self._create_event()
        response = self.client.get(self.event_detail_url(event.seq))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "张**丰")
        self.assertNotContains(response, self.member.member_no)

    # ---- navigation ------------------------------------------------------

    def test_previous_next_navigation_links(self):
        e1 = self._create_event()
        e2 = self._create_event()
        response = self.client.get(self.event_detail_url(e2.seq))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'上一条 #{e1.seq}')
        # e2 is the latest (assuming no other events); next should be disabled.
        self.assertContains(response, "下一条 →")

    def test_first_event_no_previous_link(self):
        # setUp signals already create events; seq=1 is the true first event.
        first_event = SystemEvent.objects.order_by("seq").first()
        response = self.client.get(self.event_detail_url(first_event.seq))
        self.assertContains(response, "← 上一条")
        self.assertNotContains(response, f"/observer/events/{first_event.seq - 1}/")

    # ---- chain verification -----------------------------------------------

    def test_chain_valid(self):
        event = self._create_event()
        response = self.client.get(self.event_detail_url(event.seq))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "整体校验")
        self.assertContains(response, "通过")

    def test_chain_invalid_payload_hash(self):
        event = self._create_event(payload_json={"reason": "original"})
        # Tamper with payload_hash via queryset update (bypasses append-only guard).
        SystemEvent.objects.filter(seq=event.seq).update(payload_hash="deadbeef")
        response = self.client.get(self.event_detail_url(event.seq))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "未通过")

    def test_chain_invalid_prev_hash(self):
        e1 = self._create_event()
        e2 = self._create_event()
        # Tamper with prev_hash.
        SystemEvent.objects.filter(seq=e2.seq).update(prev_hash="deadbeef")
        response = self.client.get(self.event_detail_url(e2.seq))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "未通过")

    # ---- observer homepage includes link -----------------------------------

    def test_homepage_includes_events_browser_link(self):
        response = self.client.get("/observer/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "事件浏览器")
        self.assertContains(response, "/observer/events/")

    def test_homepage_event_timeline_has_events_browser_link(self):
        response = self.client.get("/observer/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "事件时间线")
        self.assertContains(response, "查看全部")
        self.assertContains(response, "/observer/events/")
