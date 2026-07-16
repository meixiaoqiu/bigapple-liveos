from __future__ import annotations

from django.test import TestCase
from django.utils import timezone

from core.event_ledger import PUBLIC_LEDGER_SCHEMA, append_event
from core.models import Event, Member, SystemEvent
from core.tests.helpers import create_member


def _v2_payload(**facts: dict) -> dict:
    return {
        "schema": PUBLIC_LEDGER_SCHEMA,
        "subject": {"type": "test", "ref": "test-1", "label": "测试"},
        "action": "test",
        "stage": "test",
        "summary": "测试事件。",
        "public_facts": dict(facts),
        "private_commitments": [],
    }


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
        aggregate_type: str = "MemberApplication",
        aggregate_id: str = "app-evts",
        payload_json: dict | None = None,
        occurred_at=None,
    ) -> SystemEvent:
        return append_event(
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            actor_member=self.member,
            payload_json=payload_json or _v2_payload(),
            occurred_at=occurred_at or timezone.now(),
        )

    # ---- public Event stream --------------------------------------------

    def test_events_list_accessible(self):
        event = self._create_public_event()
        response = self.client.get(self.events_list_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "公共事件流")
        self.assertContains(response, event.title)

    def test_events_list_only_shows_public_events(self):
        self._create_public_event(title="公开事件")
        self._create_public_event(
            event_id="internal-event-1",
            title="内部事件",
            visibility=Event.Visibility.INTERNAL,
        )
        response = self.client.get(self.events_list_url())
        self.assertContains(response, "公开事件")
        self.assertNotContains(response, "内部事件")

    def test_events_list_empty(self):
        response = self.client.get(self.events_list_url())
        self.assertContains(response, "暂无公开事件")

    def test_event_detail_accessible(self):
        event = self._create_public_event(payload={"stage": "admitted"})
        response = self.client.get(self.event_detail_url(event.event_id))
        self.assertContains(response, "事件概要")
        self.assertContains(response, event.event_id)

    def test_event_detail_not_found(self):
        response = self.client.get(self.event_detail_url("missing-event"))
        self.assertEqual(response.status_code, 404)

    def test_event_detail_rejects_internal_event(self):
        event = self._create_public_event(visibility=Event.Visibility.INTERNAL)
        response = self.client.get(self.event_detail_url(event.event_id))
        self.assertEqual(response.status_code, 404)

    def test_homepage_event_card_links_to_public_event_detail(self):
        event = self._create_public_event()
        response = self.client.get("/observer/")
        self.assertContains(response, "事件时间线")
        self.assertContains(response, event.title)
        self.assertContains(response, f'/observer/events/{event.event_id}/"')

    # ---- semantic summary -----------------------------------------------

    def test_member_application_semantic_summary(self):
        self._create_ledger_event(
            aggregate_type="MemberApplication",
            aggregate_id="member-application-abc123",
            payload_json=_v2_payload(
                public_applicant_label="w**y",
                role_gap_label="系统开发与 AI 工程",
                proposal_no="0007",
                stage="submitted",
            ),
        )
        self._create_public_event(
            event_id="member-application-submitted-app-abc123",
            title="成员报名已提交",
            summary="w**y 报名意向角色。",
            payload={
                "source": "member_application",
                "stage": "submitted",
                "application_id": "member-application-abc123",
                "proposal_no": "0007",
                "public_applicant_label": "w**y",
                "role_gap": "developer_ai_engineer",
                "role_gap_label": "系统开发与 AI 工程",
            },
        )
        response = self.client.get("/observer/member-applications/member-application-abc123/")
        self.assertContains(response, "报名者")
        self.assertContains(response, "w**y")
        self.assertContains(response, "意向角色")
        self.assertContains(response, "系统开发与 AI 工程")
        self.assertContains(response, "准入提案")
        self.assertContains(response, "0007")
        self.assertContains(response, "治理时间线")

    # ---- audit proof (new schema) ---------------------------------------

    def test_audit_proof_default_expanded(self):
        self._create_ledger_event(payload_json=_v2_payload(application_id="app-dfe"))
        event = self._create_public_event(payload={"application_id": "app-dfe"})
        response = self.client.get(self.event_detail_url(event.event_id))
        self.assertContains(response, "审计证明")
        self.assertContains(response, "<details")

    def test_new_schema_audit_shows_public_payload(self):
        self._create_ledger_event(
            payload_json=_v2_payload(application_id="app-ns1", status="submitted"),
            aggregate_type="MemberApplication",
            aggregate_id="app-ns1",
        )
        event = self._create_public_event(payload={"application_id": "app-ns1"})
        response = self.client.get(self.event_detail_url(event.event_id))
        self.assertContains(response, "现场复算哈希链")
        self.assertNotContains(response, "公开摘要 hash")

    def test_old_schema_audit_displays_legacy(self):
        old = SystemEvent(
            seq=9999,
            event_type=SystemEvent.EventType.MEMBER_CREATED,
            aggregate_type="MemberApplication",
            aggregate_id="app-old",
            actor_member=self.member,
            payload_json={"application_id": "app-old", "status": "old"},
            payload_hash="000000",
            prev_hash="000000",
            event_hash="000000",
            occurred_at=timezone.now(),
        )
        old._allow_append = True
        old.save(force_insert=True)
        event = self._create_public_event(payload={"application_id": "app-old"})
        response = self.client.get(self.event_detail_url(event.event_id))
        self.assertContains(response, "旧格式")

    def test_audit_proof_verify_button(self):
        self._create_ledger_event(
            payload_json=_v2_payload(application_id="app-456"),
            aggregate_type="MemberApplication",
            aggregate_id="app-456",
        )
        event = self._create_public_event(payload={"application_id": "app-456"})
        response = self.client.get(self.event_detail_url(event.event_id))
        self.assertContains(response, "现场复算哈希链")
        self.assertContains(response, "modal")
        self.assertContains(response, "mockup-code")

    def test_subject_ref_shown_aggregate_id_hidden(self):
        """Page must show public subject_ref, not internal aggregate_id."""
        payload = _v2_payload(proposal_no="0007")
        payload["subject"]["ref"] = "proposal:0007"
        self._create_ledger_event(
            payload_json=payload,
            aggregate_type="Proposal",
            aggregate_id="internal-proposal-pk-123",
        )
        event = self._create_public_event(payload={"proposal_no": "0007"})
        response = self.client.get(self.event_detail_url(event.event_id))
        self.assertContains(response, "proposal:0007")
        self.assertNotContains(response, "internal-proposal-pk-123")

    # ---- JS hash verification (no JSON.stringify re-encoding) ----------

    def test_js_hash_verification_no_json_stringify_re_encode(self):
        self._create_ledger_event(
            payload_json=_v2_payload(application_id="app-jsv"),
            aggregate_type="MemberApplication",
            aggregate_id="app-jsv",
        )
        event = self._create_public_event(payload={"application_id": "app-jsv"})
        response = self.client.get(self.event_detail_url(event.event_id))
        content = response.content.decode()
        self.assertNotIn("JSON.stringify(payloadCanonical)", content)
        self.assertNotIn("JSON.stringify(eventHashInput)", content)
        self.assertIn("encoder.encode(payloadCanonical)", content)
        self.assertIn("encoder.encode(eventHashInputCanonical)", content)

    # ---- XSS safety -----------------------------------------------------

    def test_audit_proof_json_script_escapes_xss(self):
        payload = _v2_payload(application_id="app-x", reason="</script><img src=x onerror=alert(1)>")
        self._create_ledger_event(
            payload_json=payload,
            aggregate_type="MemberApplication",
            aggregate_id="app-x",
        )
        event = self._create_public_event(payload={"application_id": "app-x"})
        response = self.client.get(self.event_detail_url(event.event_id))
        self.assertNotContains(response, "</script><img")

    # ---- sensitive fields hidden ----------------------------------------

    def test_unsafe_v2_payload_bypassing_append_event_not_browser_verifiable(self):
        """A v2 payload with denylist keys inserted via bypassed write
        must not expose raw canonical JSON or verification button."""
        from core.event_ledger import validate_public_ledger_payload

        malformed = {
            "schema": PUBLIC_LEDGER_SCHEMA,
            "subject": {"type": "test", "ref": "secret-subject-ref", "label": "secret-subject-label"},
            "action": "created",
            "stage": "created",
            "summary": "secret-summary-phone",
            "public_facts": {
                "contact": "should-not-appear",
                "proposal_id": "secret-proposal-pk",
                "contact_info": "secret-contact",
                "application_id": "app-unsafe",
            },
            "private_commitments": [],
        }
        # Validate directly: must raise
        with self.assertRaises(ValueError):
            validate_public_ledger_payload(malformed)

        # Bypass append_event to simulate old/dirty data in DB
        se = SystemEvent(
            seq=88888,
            event_type=SystemEvent.EventType.MEMBER_CREATED,
            aggregate_type="MemberApplication",
            aggregate_id="app-unsafe",
            actor_member=self.member,
            payload_json=malformed,
            payload_hash="000000",
            prev_hash="000000",
            event_hash="000000",
            occurred_at=timezone.now(),
        )
        se._allow_append = True
        se.save(force_insert=True)

        event = self._create_public_event(payload={"application_id": "app-unsafe"})
        response = self.client.get(self.event_detail_url(event.event_id))
        response_text = response.content.decode()
        # Observer must detect unsafe payload
        self.assertContains(response, "未通过公开安全校验")
        # No raw canonical JSON json_script injected into page
        self.assertNotIn("audit-payload-json-88888", response_text)
        # No leaked sensitive values from public_facts
        self.assertNotIn("should-not-appear", response_text)
        self.assertNotIn("secret-proposal-pk", response_text)
        self.assertNotIn("secret-contact", response_text)
        # No denylist key names in visible content
        self.assertNotIn("proposal_id", response_text)
        self.assertNotIn("contact_info", response_text)

    def test_unsafe_proof_row_context_has_no_leaked_values(self):
        """Proof row dict must not leak subject_ref or raw payload when can_browser_verify=False."""
        from observer.event_context import public_event_detail

        malformed = {
            "schema": PUBLIC_LEDGER_SCHEMA,
            "subject": {"type": "test", "ref": "secret-subject-ref", "label": "测试"},
            "action": "created",
            "stage": "created",
            "summary": "测试。",
            "public_facts": {"contact": "secret-contact"},
            "private_commitments": [],
        }
        se = SystemEvent(
            seq=77777,
            event_type=SystemEvent.EventType.MEMBER_CREATED,
            aggregate_type="MemberApplication",
            aggregate_id="app-unsafe-direct",
            payload_json=malformed,
            payload_hash="0",
            prev_hash="0",
            event_hash="0",
            occurred_at=timezone.now(),
        )
        se._allow_append = True
        se.save(force_insert=True)

        event = self._create_public_event(payload={"application_id": "app-unsafe-direct"})
        detail = public_event_detail(event)
        rows = detail["audit_events"]
        self.assertTrue(len(rows) >= 1)
        row = rows[0]

        self.assertFalse(row["can_browser_verify"])
        self.assertEqual(row["subject_ref"], "")
        self.assertEqual(row["event_hash_input"], {})
        self.assertEqual(row["event_hash_input_canonical_json"], "")
        self.assertEqual(row["payload_json"], {})
        self.assertIn("unsafe_status", row["payload_public_display"])

        row_flat = str(row)
        self.assertNotIn("secret-subject-ref", row_flat)
        self.assertNotIn("secret-contact", row_flat)

    def test_public_system_event_payload_returns_unsafe_status_for_bad_v2(self):
        """public_system_event_payload must return unsafe_status for invalid v2 payload."""
        from observer.event_context import public_system_event_payload

        malformed = {
            "schema": PUBLIC_LEDGER_SCHEMA,
            "subject": {"type": "test", "ref": "t", "label": "t"},
            "action": "a",
            "stage": "s",
            "summary": "secret-phone-1234",
            "public_facts": {"contact": "secret-contact-val"},
            "private_commitments": [],
        }
        se = SystemEvent(
            seq=77777,
            event_type=SystemEvent.EventType.MEMBER_CREATED,
            aggregate_type="Test",
            aggregate_id="t",
            payload_json=malformed,
            payload_hash="0",
            prev_hash="0",
            event_hash="0",
            occurred_at=timezone.now(),
        )
        se._allow_append = True
        se.save(force_insert=True)
        result = public_system_event_payload(se)
        self.assertIn("unsafe_status", result)
        self.assertNotIn("subject", result)
        self.assertNotIn("summary", result)
        self.assertNotIn("public_facts", result)
        self.assertNotIn("secret-phone-1234", str(result))

    def test_real_builder_does_not_expose_member_privacy(self):
        """Actual payload builders must not put member_no/display_name into public payload."""
        from core.models import LedgerEntry

        m = self.member
        m.display_name = "真实张三"
        m.member_no = "secret-member-no-001"
        m.save()

        # Check member_creation_payload directly
        from core.identity_services import member_creation_payload
        p = member_creation_payload(m)
        flat = str(p)
        self.assertNotIn("secret-member-no-001", flat)
        self.assertNotIn("真实张三", flat)
        self.assertIn("真**三", flat)

    # ---- no ledger links on public pages --------------------------------

    def test_homepage_no_ledger_link(self):
        response = self.client.get("/observer/")
        self.assertContains(response, "事件流")
        self.assertNotContains(response, "/observer/event-ledger/")

    def test_events_list_no_ledger_link(self):
        self._create_public_event()
        response = self.client.get(self.events_list_url())
        self.assertNotContains(response, "/observer/event-ledger/")

    def test_event_detail_no_ledger_link(self):
        self._create_ledger_event(
            payload_json=_v2_payload(application_id="app-nl1"),
            aggregate_type="MemberApplication",
            aggregate_id="app-nl1",
        )
        event = self._create_public_event(payload={"application_id": "app-nl1"})
        response = self.client.get(self.event_detail_url(event.event_id))
        self.assertNotContains(response, "/observer/event-ledger/")

    # ---- member application page -----------------------------------------

    def test_member_application_stage_event_404(self):
        ev = self._create_public_event(
            event_id="member-application-submitted-app-404-test",
            payload={"source": "member_application", "stage": "submitted", "application_id": "app-404-test"},
        )
        response = self.client.get(self.event_detail_url(ev.event_id))
        self.assertEqual(response.status_code, 404)

    def test_member_application_rejected_stage_event_404(self):
        ev = self._create_public_event(
            event_id="member-application-rejected-app-404-r",
            payload={"source": "member_application", "stage": "rejected", "application_id": "app-404-r"},
        )
        response = self.client.get(self.event_detail_url(ev.event_id))
        self.assertEqual(response.status_code, 404)

    def test_member_application_detail_page_accessible(self):
        self._create_ledger_event(
            aggregate_type="MemberApplication",
            aggregate_id="app-detail-1",
            payload_json=_v2_payload(stage="submitted"),
        )
        self._create_public_event(
            event_id="member-application-submitted-app-detail",
            payload={
                "source": "member_application", "stage": "submitted",
                "application_id": "app-detail-1",
                "public_applicant_label": "张**三",
                "role_gap_label": "开发",
            },
        )
        self._create_public_event(
            event_id="member-application-rejected-app-detail",
            payload={
                "source": "member_application", "stage": "rejected",
                "application_id": "app-detail-1",
                "public_applicant_label": "张**三",
                "role_gap_label": "开发",
            },
        )
        response = self.client.get("/observer/member-applications/app-detail-1/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "治理时间线")
        self.assertContains(response, "哈希证明")

    def test_member_application_detail_no_sensitive_leak(self):
        self._create_ledger_event(
            aggregate_type="MemberApplication",
            aggregate_id="app-sens-1",
            payload_json=_v2_payload(stage="submitted", role_gap_label="开发"),
        )
        self._create_public_event(
            event_id="member-application-submitted-app-sens",
            payload={
                "source": "member_application", "stage": "submitted",
                "application_id": "app-sens-1",
                "public_applicant_label": "w**y",
                "contact": "real-contact@secret.com",
                "username": "secret_user",
                "account_user_id": "uuid-secret",
                "role_gap_label": "开发",
            },
        )
        response = self.client.get("/observer/member-applications/app-sens-1/")
        self.assertNotContains(response, "real-contact@secret.com")
        self.assertNotContains(response, "secret_user")
        self.assertNotContains(response, "uuid-secret")

    def test_member_application_detail_404_not_found(self):
        response = self.client.get("/observer/member-applications/nonexistent-app/")
        self.assertEqual(response.status_code, 404)

    def test_events_list_aggregates_member_application_cards(self):
        self._create_public_event(
            event_id="member-application-submitted-app-el",
            payload={"source": "member_application", "stage": "submitted", "application_id": "app-el-1",
                     "public_applicant_label": "王**五", "role_gap_label": "厨艺"},
        )
        self._create_public_event(
            event_id="member-application-rejected-app-el",
            payload={"source": "member_application", "stage": "rejected", "application_id": "app-el-1",
                     "public_applicant_label": "王**五", "role_gap_label": "厨艺"},
        )
        response = self.client.get("/observer/events/")
        response_text = response.content.decode()
        self.assertContains(response, "/observer/member-applications/app-el-1/")
        self.assertNotIn("/observer/events/member-application-submitted-app-el/", response_text)

    def test_homepage_aggregates_member_application_cards(self):
        self._create_public_event(
            event_id="member-application-submitted-app-hp",
            payload={"source": "member_application", "stage": "submitted", "application_id": "app-hp-1",
                     "public_applicant_label": "李**四", "role_gap_label": "开发"},
        )
        self._create_public_event(
            event_id="member-application-rejected-app-hp",
            payload={"source": "member_application", "stage": "rejected", "application_id": "app-hp-1",
                     "public_applicant_label": "李**四", "role_gap_label": "开发"},
        )
        response = self.client.get("/observer/")
        response_text = response.content.decode()
        # Must link to aggregated page, not raw stage events
        self.assertContains(response, "/observer/member-applications/app-hp-1/")
        self.assertNotIn("/observer/events/member-application-submitted-app-hp/", response_text)
        self.assertNotIn("/observer/events/member-application-rejected-app-hp/", response_text)

    def test_timeline_events_sorted_by_occurred_at_desc(self):
        """Newer normal event must appear before older member application card."""
        from django.utils import timezone
        from observer.dashboard_context import observer_command_dashboard_context
        old_time = timezone.now() - timezone.timedelta(hours=24)
        new_time = timezone.now()
        self._create_public_event(
            event_id="member-application-submitted-app-sort",
            payload={"source": "member_application", "stage": "submitted", "application_id": "app-sort-1",
                     "public_applicant_label": "李**四"},
            occurred_at=old_time,
        )
        self._create_public_event(
            payload={"stage": "admitted"},
            occurred_at=new_time,
        )
        ctx = observer_command_dashboard_context()
        timeline = ctx["timeline_events"]
        # The newer normal event should come before the older MA card
        normal_idx = None
        ma_idx = None
        for i, ev in enumerate(timeline):
            if ev["event_id"].startswith("ma-"):
                ma_idx = i
            elif not ev["event_id"].startswith("member-application-"):
                normal_idx = i
        self.assertIsNotNone(normal_idx)
        self.assertIsNotNone(ma_idx)
        self.assertLess(normal_idx, ma_idx, "Newer normal event must sort before older MA card")

    def test_timeline_events_at_most_8(self):
        """Even with many MA cards, timeline_events must cap at 8."""
        from django.utils import timezone
        from observer.dashboard_context import observer_command_dashboard_context
        for i in range(10):
            self._create_public_event(
                event_id=f"member-application-submitted-ma-{i}",
                payload={"source": "member_application", "stage": "submitted",
                         "application_id": f"app-overflow-{i}",
                         "public_applicant_label": f"U**{i}"},
                occurred_at=timezone.now(),
            )
        ctx = observer_command_dashboard_context()
        self.assertLessEqual(len(ctx["timeline_events"]), 8)

    def test_events_list_excludes_prefix_stage_event_without_source(self):
        self._create_public_event(
            event_id="member-application-submitted-nosource",
            payload={"stage": "submitted", "application_id": "app-nosource-1"},
        )
        response = self.client.get("/observer/events/")
        response_text = response.content.decode()
        self.assertNotIn("/observer/events/member-application-submitted-nosource/", response_text)

    def test_payload_source_member_app_without_prefix_404(self):
        ev = self._create_public_event(
            event_id="some-other-event-id",
            payload={"source": "member_application", "stage": "rejected", "application_id": "app-noprefix"},
        )
        response = self.client.get(self.event_detail_url(ev.event_id))
        self.assertEqual(response.status_code, 404)

    def test_non_member_app_with_app_id_and_stage_still_accessible(self):
        ev = self._create_public_event(
            payload={"application_id": "some-id", "stage": "submitted"},
        )
        response = self.client.get(self.event_detail_url(ev.event_id))
        self.assertEqual(response.status_code, 200)

    def test_audit_timeline_deduplicated_by_seq(self):
        from observer.event_context import public_member_application_detail
        # Create a shared SystemEvent
        shared_ledger = self._create_ledger_event(
            payload_json=_v2_payload(),
            aggregate_type="MemberApplication",
            aggregate_id="app-dedup-1",
        )
        self._create_public_event(
            event_id="member-application-submitted-app-dedup",
            payload={"source": "member_application", "stage": "submitted", "application_id": "app-dedup-1"},
        )
        self._create_public_event(
            event_id="member-application-rejected-app-dedup",
            payload={"source": "member_application", "stage": "rejected", "application_id": "app-dedup-1"},
        )
        detail = public_member_application_detail("app-dedup-1")
        self.assertIsNotNone(detail)
        items = detail["timeline_items"]
        self.assertTrue(len(items) > 0, "timeline_items must not be empty")
        seqs = [r["seq"] for r in items]
        self.assertEqual(len(seqs), len(set(seqs)), f"duplicate seqs found: {seqs}")

    def test_timeline_items_have_unified_structure(self):
        """Timeline items must embed audit proof, have semantic titles."""
        self._create_ledger_event(
            payload_json=_v2_payload(),
            aggregate_type="MemberApplication",
            aggregate_id="app-timeline-1",
        )
        self._create_public_event(
            event_id="member-application-submitted-app-timeline",
            payload={"source": "member_application", "stage": "submitted", "application_id": "app-timeline-1"},
        )
        response = self.client.get("/observer/member-applications/app-timeline-1/")
        self.assertContains(response, "治理时间线")
        self.assertContains(response, "哈希证明")
        # No separate stage-list or audit section titles
        self.assertNotContains(response, "阶段时间线")

    def test_timeline_shows_voter_public_identity(self):
        """Vote audit payload must show voter public name and choice."""
        payload = _v2_payload()
        payload["public_facts"]["vote_choice_label"] = "反对"
        payload["public_facts"]["voter_public_name"] = "wzy"
        payload["public_facts"]["reason"] = "能力不匹配"
        self._create_ledger_event(
            payload_json=payload,
            event_type=SystemEvent.EventType.PROPOSAL_VOTE_CAST,
            aggregate_type="MemberApplication",
            aggregate_id="app-vote-1",
        )
        self._create_public_event(
            event_id="member-application-submitted-app-vote",
            payload={"source": "member_application", "stage": "submitted", "application_id": "app-vote-1"},
        )
        response = self.client.get("/observer/member-applications/app-vote-1/")
        self.assertContains(response, "wzy")
        self.assertContains(response, "反对")
        self.assertContains(response, "能力不匹配")

    def test_timeline_applicant_remains_deidentified(self):
        """Applicant must stay de-identified in timeline display."""
        payload = _v2_payload()
        payload["public_facts"]["public_applicant_label"] = "w**y"
        self._create_ledger_event(
            payload_json=payload,
            aggregate_type="MemberApplication",
            aggregate_id="app-deid-1",
        )
        self._create_public_event(
            event_id="member-application-submitted-app-deid",
            payload={"source": "member_application", "stage": "submitted",
                     "application_id": "app-deid-1", "public_applicant_label": "w**y"},
        )
        response = self.client.get("/observer/member-applications/app-deid-1/")
        self.assertContains(response, "w**y")

    def test_event_detail_still_works_for_non_member_app(self):
        ev = self._create_public_event(payload={"stage": "admitted"})
        response = self.client.get(self.event_detail_url(ev.event_id))
        self.assertEqual(response.status_code, 200)

    # ---- layout -----------------------------------------------------------

    def test_timeline_uses_compact_layout(self):
        self._create_ledger_event(aggregate_id="app-compact-1")
        self._create_public_event(
            event_id="member-application-submitted-app-compact",
            payload={"source": "member_application", "stage": "submitted",
                     "application_id": "app-compact-1"},
        )
        response = self.client.get("/observer/member-applications/app-compact-1/")
        self.assertContains(response, "timeline-compact")
        self.assertContains(response, "max-w-6xl")

    # ---- proposal_no linkage ----------------------------------------------

    def test_proposal_no_links_vote_system_event_to_timeline(self):
        """Vote SystemEvent with only proposal_no (no application_id) must appear."""
        vote_payload = _v2_payload(vote_choice_label="反对", voter_public_name="wzy", reason="理由测试")
        vote_payload["public_facts"]["proposal_no"] = "0007"
        self._create_ledger_event(
            event_type=SystemEvent.EventType.PROPOSAL_VOTE_CAST,
            aggregate_type="ProposalVote",
            aggregate_id="vote-no-app",
            payload_json=vote_payload,
        )
        self._create_public_event(
            event_id="member-application-rejected-app-link",
            payload={"source": "member_application", "stage": "rejected",
                     "application_id": "app-legacy-link", "proposal_no": "0007"},
        )
        response = self.client.get("/observer/member-applications/app-legacy-link/")
        self.assertContains(response, "治理成员已投票")
        self.assertContains(response, "wzy")
        self.assertContains(response, "反对")
        self.assertContains(response, "理由测试")

    def test_dedup_when_event_matches_multiple_conditions(self):
        """SystemEvent matching both application_id and proposal_no must not duplicate."""
        payload = _v2_payload(vote_choice_label="反对", voter_public_name="wzy")
        payload["public_facts"]["application_id"] = "app-dup-1"
        payload["public_facts"]["proposal_no"] = "0009"
        self._create_ledger_event(
            event_type=SystemEvent.EventType.PROPOSAL_VOTE_CAST,
            aggregate_type="MemberApplication",
            aggregate_id="app-dup-1",
            payload_json=payload,
        )
        self._create_public_event(
            event_id="member-application-submitted-app-dup",
            payload={"source": "member_application", "stage": "submitted",
                     "application_id": "app-dup-1", "proposal_no": "0009"},
        )
        response = self.client.get("/observer/member-applications/app-dup-1/")
        content = response.content.decode()
        self.assertEqual(content.count("治理成员已投票"), 1,
                         "Vote event must appear exactly once")

    def test_event_id_prefix_triggers_proposal_no_linkage(self):
        """Stage Event without source but with member-application-rejected- prefix
        and proposal_no must still link vote SystemEvent."""
        vote_payload = _v2_payload(vote_choice_label="反对", voter_public_name="wzy")
        vote_payload["public_facts"]["proposal_no"] = "0010"
        self._create_ledger_event(
            event_type=SystemEvent.EventType.PROPOSAL_VOTE_CAST,
            aggregate_type="ProposalVote",
            aggregate_id="vote-nosource",
            payload_json=vote_payload,
        )
        self._create_public_event(
            event_id="member-application-rejected-app-nosource",
            payload={"application_id": "app-nosource", "proposal_no": "0010", "stage": "rejected"},
        )
        response = self.client.get("/observer/member-applications/app-nosource/")
        self.assertContains(response, "wzy")

    def test_proposal_id_linkage_hides_pk_in_page(self):
        """proposal_id used for internal linkage must not appear in HTML."""
        prop_payload = _v2_payload(proposal_no="0011")
        self._create_ledger_event(
            event_type=SystemEvent.EventType.PROPOSAL_CREATED,
            aggregate_type="Proposal",
            aggregate_id="prop-pk-999",
            payload_json=prop_payload,
        )
        self._create_public_event(
            event_id="member-application-submitted-app-pid",
            payload={"source": "member_application", "stage": "submitted",
                     "application_id": "app-pid", "proposal_id": "prop-pk-999",
                     "proposal_no": "0011"},
        )
        response = self.client.get("/observer/member-applications/app-pid/")
        content = response.content.decode()
        self.assertNotIn("prop-pk-999", content)
        self.assertNotIn("proposal_id", content)

    # ---- proposal_id hiding ---------------------------------------------

    def test_real_member_admission_flow_shows_timeline_with_proposal_and_vote(self):
        """End-to-end: submit → proposal created → timeline shows core events."""
        from core.application_services import submit_member_application
        from core.member_roles import ROLE_GOVERNANCE_MEMBER, ensure_member_role, ensure_role_assignment

        # Ensure governance voter exists before application (needed for eligible_voter_snapshot)
        gov_role = ensure_member_role(ROLE_GOVERNANCE_MEMBER)
        ensure_role_assignment(self.member, gov_role)

        # Submit real member application
        app = submit_member_application(
            applicant_name="Integration Test Applicant",
            contact="int-test@example.com",
            motivation="Integration test.",
            role_gap="cooking",
            account_username="inttestuser",
            account_password="TestPass123!",
        )
        proposal = app.admission_proposal

        response = self.client.get(f"/observer/member-applications/{app.application_id}/")
        self.assertEqual(response.status_code, 200)

        # Core timeline entries
        self.assertContains(response, "收到成员报名")
        self.assertContains(response, "准入提案已创建")
        # No duplicate "准入提案已创建" (would indicate duplicate PROPOSAL_CREATED events)
        content = response.content.decode()
        self.assertEqual(content.count("准入提案已创建"), 1,
                         "准入提案已创建 must appear exactly once in timeline")

    def test_proposal_id_hidden(self):
        event = self._create_public_event(payload={"proposal_id": "pk-123", "proposal_no": "0007"})
        response = self.client.get(self.event_detail_url(event.event_id))
        self.assertContains(response, "0007")
        self.assertNotContains(response, "proposal_id")

    # ---- hidden advanced ledger routes ----------------------------------

    def test_event_ledger_list_accessible(self):
        event = self._create_ledger_event()
        response = self.client.get(self.ledger_list_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "事件审计账本")

    def test_event_ledger_detail_accessible(self):
        event = self._create_ledger_event()
        response = self.client.get(self.ledger_detail_url(event.seq))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, str(event.seq))

    def test_ledger_detail_not_found(self):
        response = self.client.get(self.ledger_detail_url(99999))
        self.assertEqual(response.status_code, 404)

    def test_ledger_actor_member_deidentified(self):
        self.member.display_name = "张三丰"
        self.member.save()
        event = self._create_ledger_event()
        response = self.client.get(self.ledger_detail_url(event.seq))
        self.assertContains(response, "张**丰")
        self.assertNotContains(response, self.member.member_no)

    def test_ledger_previous_next_navigation_links(self):
        e1 = self._create_ledger_event()
        e2 = self._create_ledger_event()
        response = self.client.get(self.ledger_detail_url(e2.seq))
        self.assertContains(response, f"上一条 #{e1.seq}")

    def test_first_ledger_event_has_no_previous_link(self):
        first = SystemEvent.objects.order_by("seq").first()
        response = self.client.get(self.ledger_detail_url(first.seq))
        self.assertNotContains(response, f"/observer/event-ledger/{first.seq - 1}/")

    def test_ledger_chain_invalid_payload_hash(self):
        event = self._create_ledger_event(payload_json=_v2_payload(reason="original"))
        SystemEvent.objects.filter(seq=event.seq).update(payload_hash="deadbeef")
        response = self.client.get(self.ledger_detail_url(event.seq))
        self.assertContains(response, "未通过")

    def test_ledger_chain_invalid_prev_hash(self):
        self._create_ledger_event()
        second = self._create_ledger_event()
        SystemEvent.objects.filter(seq=second.seq).update(prev_hash="deadbeef")
        response = self.client.get(self.ledger_detail_url(second.seq))
        self.assertContains(response, "未通过")

    # ---- ledger pages hide aggregate_id, show subject_ref ----------------

    def test_ledger_list_shows_subject_ref_hides_aggregate_id(self):
        payload = _v2_payload(proposal_no="0007")
        payload["subject"]["ref"] = "proposal:0007"
        self._create_ledger_event(
            payload_json=payload,
            aggregate_type="Proposal",
            aggregate_id="internal-proposal-pk-123",
        )
        response = self.client.get(self.ledger_list_url())
        self.assertContains(response, "proposal:0007")
        self.assertNotContains(response, "internal-proposal-pk-123")

    def test_ledger_detail_shows_subject_ref_hides_aggregate_id(self):
        payload = _v2_payload(proposal_no="0007")
        payload["subject"]["ref"] = "proposal:0007"
        event = self._create_ledger_event(
            payload_json=payload,
            aggregate_type="Proposal",
            aggregate_id="internal-proposal-pk-123",
        )
        response = self.client.get(self.ledger_detail_url(event.seq))
        self.assertContains(response, "proposal:0007")
        self.assertNotContains(response, "internal-proposal-pk-123")

    def test_ledger_detail_unsafe_v2_hides_subject_ref_and_raw_values(self):
        malformed = {
            "schema": PUBLIC_LEDGER_SCHEMA,
            "subject": {"type": "test", "ref": "secret-subject-ref", "label": "测试"},
            "action": "created",
            "stage": "created",
            "summary": "测试。",
            "public_facts": {"contact": "secret-contact"},
            "private_commitments": [],
        }
        se = SystemEvent(
            seq=66666,
            event_type=SystemEvent.EventType.MEMBER_CREATED,
            aggregate_type="Test",
            aggregate_id="unsafe-detail",
            payload_json=malformed,
            payload_hash="0",
            prev_hash="0",
            event_hash="0",
            occurred_at=timezone.now(),
        )
        se._allow_append = True
        se.save(force_insert=True)
        response = self.client.get(self.ledger_detail_url(se.seq))
        response_text = response.content.decode()
        self.assertNotIn("secret-subject-ref", response_text)
        self.assertNotIn("secret-contact", response_text)
        self.assertContains(response, "unsafe_status")
