from __future__ import annotations

from django.test import TestCase
from django.utils import timezone

from core.event_ledger import append_event
from core.models import Event, Member, SystemEvent
from core.tests.helpers import create_member


class PublicEventsBrowserTests(TestCase):
    """Cover public Event pages and the SystemEvent ledger browser."""

    def events_list_url(self) -> str:
        return "/observer/events/"

    def event_detail_url(self, event_id: str) -> str:
        return f"/observer/events/{event_id}/"

    def ledger_list_url(self) -> str:
        return "/observer/event-ledger/"

    def ledger_detail_url(self, seq: int) -> str:
        return f"/observer/event-ledger/{seq}/"

    def setUp(self) -> None:
        self.member = create_member(
            member_no="mem-evts-0001",
            role_name="contributor",
            status=Member.Status.ADMITTED,
            profile={"display_name": "测试人"},
            created_at=timezone.now(),
        )

    def _create_public_event(
        self,
        *,
        event_id: str = "public-event-1",
        title: str = "新成员已加入",
        summary: str = "一名新成员已通过准入表决并加入社区。",
        payload: dict | None = None,
        visibility: str = Event.Visibility.PUBLIC,
        occurred_at=None,
    ) -> Event:
        return Event.objects.create(
            event_id=event_id,
            event_type=Event.EventType.GOVERNANCE,
            simulation_day=0,
            severity=Event.Severity.INFO,
            title=title,
            summary=summary,
            occurred_at=occurred_at or timezone.now(),
            generated_by=Event.GeneratedBy.LIVE_OS,
            visibility=visibility,
            payload=payload or {},
        )

    def _create_ledger_event(
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

    # ---- public Event stream --------------------------------------------

    def test_events_list_accessible(self):
        event = self._create_public_event()
        response = self.client.get(self.events_list_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "公共事件流")
        self.assertContains(response, event.title)
        self.assertContains(response, event.summary)
        self.assertContains(response, f'/observer/events/{event.event_id}/"')

    def test_events_list_only_shows_public_events(self):
        self._create_public_event(title="公开事件")
        self._create_public_event(
            event_id="internal-event-1",
            title="内部事件",
            visibility=Event.Visibility.INTERNAL,
        )
        response = self.client.get(self.events_list_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "公开事件")
        self.assertNotContains(response, "内部事件")

    def test_events_list_empty(self):
        response = self.client.get(self.events_list_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "暂无公开事件")

    def test_event_detail_accessible(self):
        event = self._create_public_event(payload={"stage": "admitted"})
        response = self.client.get(self.event_detail_url(event.event_id))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "事件详情")
        self.assertContains(response, event.title)
        self.assertContains(response, event.summary)
        self.assertContains(response, event.event_id)
        self.assertContains(response, "admitted")

    def test_event_detail_not_found(self):
        response = self.client.get(self.event_detail_url("missing-event"))
        self.assertEqual(response.status_code, 404)

    def test_event_detail_rejects_internal_event(self):
        event = self._create_public_event(visibility=Event.Visibility.INTERNAL)
        response = self.client.get(self.event_detail_url(event.event_id))
        self.assertEqual(response.status_code, 404)

    def test_public_event_payload_proposal_id_hidden_proposal_no_shown(self):
        """proposal_id (internal PK) must not appear in public payload;
        proposal_no (human-readable) may appear."""
        event = self._create_public_event(
            payload={
                "proposal_id": "internal-proposal-id-123",
                "proposal_no": "0007",
            },
        )
        response = self.client.get(self.event_detail_url(event.event_id))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "0007")
        self.assertNotContains(response, "internal-proposal-id-123")
        self.assertNotContains(response, "proposal_id")

    def test_public_event_payload_sensitive_fields_hidden(self):
        event = self._create_public_event(
            payload={
                "contact": "test@example.com",
                "password": "secret",
                "member_id": 42,
                "application_id": "app-123",
                "public_member_label": "张**三",
            }
        )
        response = self.client.get(self.event_detail_url(event.event_id))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "test@example.com")
        self.assertNotContains(response, "secret")
        self.assertNotContains(response, "member_id")
        self.assertContains(response, "app-123")
        self.assertContains(response, "张**三")

    def test_event_detail_shows_related_ledger_proof(self):
        ledger = self._create_ledger_event(
            event_type=SystemEvent.EventType.MEMBER_APPLICATION_REVIEWED,
            aggregate_type="MemberApplication",
            aggregate_id="app-123",
            payload_json={"application_id": "app-123", "stage": "admitted"},
        )
        event = self._create_public_event(payload={"application_id": "app-123"})
        response = self.client.get(self.event_detail_url(event.event_id))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "审计证明")
        self.assertContains(response, str(ledger.seq))
        self.assertContains(response, ledger.event_hash[:12])
        self.assertContains(response, ledger.get_event_type_display())
        # Public event detail page must not expose raw ledger URLs.
        self.assertNotContains(response, "/observer/event-ledger/")

    def test_homepage_includes_event_stream_link_no_ledger_link(self):
        response = self.client.get("/observer/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "事件流")
        self.assertContains(response, "/observer/events/")
        self.assertNotContains(response, "/observer/event-ledger/")

    def test_events_list_does_not_expose_event_ledger_link(self):
        self._create_public_event()
        response = self.client.get(self.events_list_url())
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "/observer/event-ledger/")

    def test_event_detail_does_not_expose_event_ledger_link(self):
        event = self._create_public_event(payload={"application_id": "app-1"})
        self._create_ledger_event(
            aggregate_type="MemberApplication",
            aggregate_id="app-1",
            payload_json={"application_id": "app-1"},
        )
        response = self.client.get(self.event_detail_url(event.event_id))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "/observer/event-ledger/")

    def test_homepage_event_card_links_to_public_event_detail(self):
        event = self._create_public_event()
        response = self.client.get("/observer/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "事件时间线")
        self.assertContains(response, event.title)
        self.assertContains(response, f'/observer/events/{event.event_id}/"')

    # ---- SystemEvent ledger (hidden advanced audit routes) ------------

    def test_event_ledger_list_accessible(self):
        event = self._create_ledger_event()
        response = self.client.get(self.ledger_list_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "事件审计账本")
        self.assertContains(response, event.get_event_type_display())

    def test_event_ledger_list_has_detail_link(self):
        event = self._create_ledger_event()
        response = self.client.get(self.ledger_list_url())
        self.assertContains(response, f'/observer/event-ledger/{event.seq}/"')

    def test_event_ledger_detail_accessible(self):
        event = self._create_ledger_event()
        response = self.client.get(self.ledger_detail_url(event.seq))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"账本事件 #{event.seq}")
        self.assertContains(response, event.event_hash)
        self.assertContains(response, event.payload_hash)
        self.assertContains(response, event.prev_hash)

    def test_event_ledger_detail_not_found(self):
        response = self.client.get(self.ledger_detail_url(99999))
        self.assertEqual(response.status_code, 404)

    def test_ledger_payload_sensitive_fields_hidden(self):
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
            "public_member_label": "张**三",
        }
        event = self._create_ledger_event(payload_json=payload)
        response = self.client.get(self.ledger_detail_url(event.seq))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "test@example.com")
        self.assertNotContains(response, "someone@example.com")
        self.assertNotContains(response, "s3cret")
        self.assertNotContains(response, "uuid-sensitive")
        self.assertNotContains(response, "admin")
        self.assertContains(response, "app-123")
        self.assertContains(response, "screening")
        self.assertContains(response, "张**三")

    def test_ledger_payload_reason_truncated(self):
        long_reason = "A" * 300
        event = self._create_ledger_event(payload_json={"reason": long_reason})
        response = self.client.get(self.ledger_detail_url(event.seq))
        self.assertContains(response, "A" * 200 + "…")
        self.assertNotContains(response, "A" * 201)

    def test_ledger_actor_member_deidentified(self):
        self.member.display_name = "张三丰"
        self.member.save()
        event = self._create_ledger_event()
        response = self.client.get(self.ledger_detail_url(event.seq))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "张**丰")
        self.assertNotContains(response, self.member.member_no)

    def test_ledger_previous_next_navigation_links(self):
        e1 = self._create_ledger_event()
        e2 = self._create_ledger_event()
        response = self.client.get(self.ledger_detail_url(e2.seq))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"上一条 #{e1.seq}")
        self.assertContains(response, "下一条 →")

    def test_first_ledger_event_has_no_previous_link(self):
        first_event = SystemEvent.objects.order_by("seq").first()
        response = self.client.get(self.ledger_detail_url(first_event.seq))
        self.assertContains(response, "← 上一条")
        self.assertNotContains(response, f"/observer/event-ledger/{first_event.seq - 1}/")

    def test_ledger_chain_valid(self):
        event = self._create_ledger_event()
        response = self.client.get(self.ledger_detail_url(event.seq))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "整体校验")
        self.assertContains(response, "通过")

    def test_ledger_chain_invalid_payload_hash(self):
        event = self._create_ledger_event(payload_json={"reason": "original"})
        SystemEvent.objects.filter(seq=event.seq).update(payload_hash="deadbeef")
        response = self.client.get(self.ledger_detail_url(event.seq))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "未通过")

    def test_ledger_chain_invalid_prev_hash(self):
        self._create_ledger_event()
        second = self._create_ledger_event()
        SystemEvent.objects.filter(seq=second.seq).update(prev_hash="deadbeef")
        response = self.client.get(self.ledger_detail_url(second.seq))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "未通过")
