from __future__ import annotations

from decimal import Decimal

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase
from django.utils import timezone

from core.admin import SystemEventAdmin
from core.event_ledger import PUBLIC_LEDGER_SCHEMA, append_event, hash_json, verify_event_chain

_v2 = lambda s="manual": {
    "schema": PUBLIC_LEDGER_SCHEMA,
    "subject": {"type": "test", "ref": s, "label": "测试"},
    "action": s,
    "stage": "test",
    "summary": "测试事件。",
    "public_facts": {},
    "private_commitments": [],
}
from core.models import (
    SystemEvent,
    Member,
    Organization,
    Permission,
    Resource,
    Role,
    RoleAssignment,
    RolePermission,
)
from core.permission_services import member_has_permission
from core.role_assignment_services import create_role_assignment, revoke_role_assignment
from core.tests.helpers import create_member


class GovernanceKernelTests(TestCase):
    def create_governance_basics(self):
        organization = Organization.objects.create(
            name="大苹果运营委员会",
        )
        member = create_member("mem-governance-1", display_name="张三")
        grantor = create_member("mem-governance-admin", display_name="治理管理员")
        role = Role.objects.create(
            organization=organization,
            name="仓库管理员",
            description="负责仓库出入和工具间管理。",
        )
        permission = Permission.objects.create(
            code="access.warehouse",
            name="进入仓库",
            category="access",
            description="允许进入仓库。",
        )
        resource = Resource.objects.create(
            resource_id="res-warehouse-1",
            name="一号仓库",
            resource_type=Resource.ResourceType.ROOM,
            location="A区",
            description="仓储空间。",
            unit=Resource.Unit.COUNT,
            current_stock=Decimal("1"),
            daily_consumption_estimate=Decimal("0"),
            replenishment_method=Resource.ReplenishmentMethod.MANUAL_ADJUSTMENT,
            loss_rate=Decimal("0"),
            warning_threshold=Decimal("0"),
            updated_at=timezone.now(),
            rule_version="ruleset-v0.1.0",
        )
        return organization, member, grantor, role, permission, resource

    def event_count(self, event_type, aggregate_type, aggregate_id):
        return SystemEvent.objects.filter(
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=str(aggregate_id),
        ).count()

    def test_governance_models_can_be_created(self):
        organization, member, grantor, role, permission, _resource = self.create_governance_basics()
        assignment = RoleAssignment.objects.create(
            member=member,
            role=role,
            granted_by=grantor,
            end_at=timezone.now() + timezone.timedelta(days=365),
        )

        self.assertEqual(organization.name, "大苹果运营委员会")
        self.assertEqual(member.status, Member.Status.ACTIVE)
        self.assertEqual(role.organization, organization)
        self.assertEqual(permission.code, "access.warehouse")
        self.assertEqual(assignment.status, RoleAssignment.Status.ACTIVE)

    def test_role_permission_grants_member_permission(self):
        _organization, member, grantor, role, permission, resource = self.create_governance_basics()
        create_role_assignment(member=member, role=role, granted_by=grantor)
        RolePermission.objects.create(role=role, permission=permission, scope="global")

        self.assertTrue(member_has_permission(member, "access.warehouse", resource=resource))

    def test_role_assignment_end_at_is_required(self):
        _organization, member, grantor, role, _permission, _resource = self.create_governance_basics()

        with self.assertRaises(ValidationError):
            RoleAssignment.objects.create(member=member, role=role, granted_by=grantor)

    def test_create_role_assignment_defaults_to_long_but_finite_end_at(self):
        _organization, member, grantor, role, _permission, _resource = self.create_governance_basics()

        assignment = create_role_assignment(member=member, role=role, granted_by=grantor)

        self.assertIsNotNone(assignment.end_at)
        self.assertGreater(assignment.end_at, assignment.start_at)
        self.assertEqual(assignment.source_type, RoleAssignment.SourceType.DIRECT)

    def test_revoked_role_assignment_removes_role_permission(self):
        _organization, member, grantor, role, permission, resource = self.create_governance_basics()
        assignment = create_role_assignment(member=member, role=role, granted_by=grantor)
        RolePermission.objects.create(role=role, permission=permission, scope="global")

        self.assertTrue(member_has_permission(member, "access.warehouse", resource=resource))
        revoke_role_assignment(assignment=assignment, revoked_by=grantor)

        self.assertFalse(member_has_permission(member, "access.warehouse", resource=resource))
    def test_role_assignment_is_time_limited_and_resource_specific(self):
        _organization, member, grantor, _role, permission, resource = self.create_governance_basics()
        role = Role.objects.create(
            organization=Organization.objects.create(name="临时资源角色组"),
            name="临时仓库访问者",
        )
        other_resource = Resource.objects.create(
            resource_id="res-tools-room",
            name="工具间",
            resource_type=Resource.ResourceType.ROOM,
            location="B区",
            description="工具存放空间。",
            unit=Resource.Unit.COUNT,
            current_stock=Decimal("1"),
            daily_consumption_estimate=Decimal("0"),
            replenishment_method=Resource.ReplenishmentMethod.MANUAL_ADJUSTMENT,
            loss_rate=Decimal("0"),
            warning_threshold=Decimal("0"),
            updated_at=timezone.now(),
            rule_version="ruleset-v0.1.0",
        )
        now = timezone.now()
        create_role_assignment(
            member=member,
            role=role,
            granted_by=grantor,
            start_at=now - timezone.timedelta(minutes=10),
            end_at=now + timezone.timedelta(minutes=10),
        )
        RolePermission.objects.create(
            role=role,
            permission=permission,
            scope="resource",
            constraints_json={"resource_id": resource.pk},
        )

        self.assertTrue(member_has_permission(member, "access.warehouse", resource=resource, at_time=now))
        self.assertFalse(member_has_permission(member, "access.warehouse", resource=other_resource, at_time=now))
        self.assertFalse(
            member_has_permission(
                member,
                "access.warehouse",
                resource=resource,
                at_time=now + timezone.timedelta(minutes=30),
            )
        )

    def test_system_event_chain_verifies_and_detects_payload_tampering(self):
        _organization, member, grantor, role, _permission, _resource = self.create_governance_basics()
        create_role_assignment(member=member, role=role, granted_by=grantor)

        self.assertTrue(verify_event_chain())
        event = SystemEvent.objects.order_by("seq").first()
        SystemEvent.objects.filter(pk=event.pk).update(payload_json={"tampered": True})
        self.assertFalse(verify_event_chain())

    def test_role_assignment_events_are_appended_on_create_and_revoke(self):
        _organization, member, grantor, role, _permission, _resource = self.create_governance_basics()
        assignment = create_role_assignment(member=member, role=role, granted_by=grantor)

        assigned_event = SystemEvent.objects.get(
            event_type=SystemEvent.EventType.ROLE_ASSIGNED,
            aggregate_type="RoleAssignment",
            aggregate_id=str(assignment.pk),
        )
        self.assertEqual(assigned_event.payload_json["public_facts"]["source_type"], RoleAssignment.SourceType.DIRECT)

        revoke_role_assignment(assignment=assignment, revoked_by=grantor)

        self.assertTrue(
            SystemEvent.objects.filter(
                event_type=SystemEvent.EventType.ROLE_REVOKED,
                aggregate_type="RoleAssignment",
                aggregate_id=str(assignment.pk),
            ).exists()
        )

    def test_repeated_role_assignment_saves_do_not_duplicate_assignment_events(self):
        _organization, member, grantor, role, _permission, _resource = self.create_governance_basics()
        assignment = create_role_assignment(member=member, role=role, granted_by=grantor)

        assignment.end_at = timezone.now() + timezone.timedelta(days=1)
        assignment.save(update_fields=["end_at", "updated_at"])
        assignment.start_at = timezone.now() - timezone.timedelta(days=1)
        assignment.save(update_fields=["start_at", "updated_at"])

        self.assertEqual(
            self.event_count(SystemEvent.EventType.ROLE_ASSIGNED, "RoleAssignment", assignment.pk),
            1,
        )
        self.assertEqual(
            self.event_count(SystemEvent.EventType.ROLE_REVOKED, "RoleAssignment", assignment.pk),
            0,
        )

    def test_role_assignment_revocation_event_is_emitted_once(self):
        _organization, member, grantor, role, _permission, _resource = self.create_governance_basics()
        assignment = create_role_assignment(member=member, role=role, granted_by=grantor)

        revoke_role_assignment(assignment=assignment, revoked_by=grantor)
        assignment.refresh_from_db()
        assignment.end_at = timezone.now()
        assignment.save(update_fields=["end_at", "updated_at"])

        self.assertEqual(
            self.event_count(SystemEvent.EventType.ROLE_REVOKED, "RoleAssignment", assignment.pk),
            1,
        )

    def test_non_active_role_assignment_to_revoked_does_not_emit_revocation_event(self):
        _organization, member, grantor, role, _permission, _resource = self.create_governance_basics()
        assignment = create_role_assignment(member=member, role=role, granted_by=grantor)

        assignment.status = RoleAssignment.Status.SUSPENDED
        assignment.save(update_fields=["status", "updated_at"])
        assignment.status = RoleAssignment.Status.REVOKED
        assignment.save(update_fields=["status", "updated_at"])

        self.assertEqual(
            self.event_count(SystemEvent.EventType.ROLE_REVOKED, "RoleAssignment", assignment.pk),
            0,
        )

    def test_system_event_admin_is_view_only(self):
        _organization, _member, grantor, _role, _permission, _resource = self.create_governance_basics()
        event = append_event(
            event_type=SystemEvent.EventType.ROLE_ASSIGNED,
            aggregate_type="RoleAssignment",
            aggregate_id="manual",
            actor_member=grantor,
            payload_json=_v2(),
        )
        admin = SystemEventAdmin(SystemEvent, AdminSite())
        user = get_user_model().objects.create_superuser("governance-admin", "admin@example.com", "password")
        request = RequestFactory().get("/admin/core/systemevent/")
        request.user = user

        self.assertFalse(admin.has_add_permission(request))
        self.assertFalse(admin.has_change_permission(request, event))
        self.assertFalse(admin.has_delete_permission(request, event))
        self.assertTrue(admin.has_view_permission(request, event))

    def test_system_event_model_save_is_append_only(self):
        _organization, _member, grantor, _role, _permission, _resource = self.create_governance_basics()
        event = append_event(
            event_type=SystemEvent.EventType.ROLE_ASSIGNED,
            aggregate_type="RoleAssignment",
            aggregate_id="manual",
            actor_member=grantor,
            payload_json=_v2(),
        )

        event.payload_json = {"tampered": True}
        with self.assertRaises(ValueError):
            event.save()

        with self.assertRaises(ValueError):
            SystemEvent.objects.create(
                seq=999,
                event_type=SystemEvent.EventType.ROLE_ASSIGNED,
                aggregate_type="RoleAssignment",
                aggregate_id="direct",
                payload_json={},
                payload_hash=hash_json({}),
                prev_hash="",
                event_hash=hash_json({"direct": True}),
                occurred_at=timezone.now(),
            )

    def test_payload_hash_uses_canonical_json_key_order(self):
        self.assertEqual(hash_json({"a": 1, "b": 2}), hash_json({"b": 2, "a": 1}))
        p = dict(_v2(), **{"b": 2, "a": 1})
        event = append_event(
            event_type=SystemEvent.EventType.ROLE_ASSIGNED,
            aggregate_type="RoleAssignment",
            aggregate_id="manual",
            payload_json=p,
        )
        # Update with same content but different key order; must preserve schema.
        ordered = dict(_v2(), **{"a": 1, "b": 2})
        SystemEvent.objects.filter(pk=event.pk).update(payload_json=ordered)

        self.assertTrue(verify_event_chain())

    def test_system_event_chain_detects_event_hash_tampering(self):
        event = append_event(
            event_type=SystemEvent.EventType.ROLE_ASSIGNED,
            aggregate_type="RoleAssignment",
            aggregate_id="manual",
            payload_json=_v2(),
        )

        SystemEvent.objects.filter(pk=event.pk).update(event_hash="0" * 64)

        self.assertFalse(verify_event_chain())

    def test_system_event_chain_detects_prev_hash_tampering(self):
        append_event(
            event_type=SystemEvent.EventType.ROLE_ASSIGNED,
            aggregate_type="RoleAssignment",
            aggregate_id="first",
            payload_json=_v2("first"),
        )
        second = append_event(
            event_type=SystemEvent.EventType.ROLE_REVOKED,
            aggregate_type="RoleAssignment",
            aggregate_id="second",
            payload_json=_v2("second"),
        )

        SystemEvent.objects.filter(pk=second.pk).update(prev_hash="bad-prev-hash")

        self.assertFalse(verify_event_chain())

    def test_resource_none_matches_any_active_role_permission_scope(self):
        _organization, member, grantor, _role, permission, resource = self.create_governance_basics()
        role = Role.objects.create(
            organization=Organization.objects.create(name="资源角色组"),
            name="仓库访问者",
        )
        now = timezone.now()
        create_role_assignment(
            member=member,
            role=role,
            granted_by=grantor,
            start_at=now - timezone.timedelta(minutes=10),
            end_at=now + timezone.timedelta(minutes=10),
        )
        RolePermission.objects.create(
            role=role,
            permission=permission,
            scope="resource",
            constraints_json={"resource_id": resource.pk},
        )

        self.assertTrue(member_has_permission(member, "access.warehouse", resource=None, at_time=now))

    def test_inactive_role_assignments_do_not_grant_permission(self):
        _organization, member, grantor, role, permission, resource = self.create_governance_basics()
        assignment = create_role_assignment(member=member, role=role, granted_by=grantor)
        RolePermission.objects.create(role=role, permission=permission, scope="global")

        assignment.status = RoleAssignment.Status.SUSPENDED
        assignment.save(update_fields=["status", "updated_at"])

        self.assertFalse(member_has_permission(member, "access.warehouse", resource=resource))

    # ---- v2 payload validation ------------------------------------------

    def _v2_payload(self, **extra) -> dict:
        return {
            "schema": PUBLIC_LEDGER_SCHEMA,
            "subject": {"type": "test", "ref": "test:1", "label": "测试"},
            "action": "created",
            "stage": "created",
            "summary": "测试事件。",
            "public_facts": {"status": "ok"},
            "private_commitments": [{"name": "contact", "present": True, "reason": "联系方式不公开"}],
            **extra,
        }

    def test_append_event_accepts_legal_v2_payload(self):
        payload = self._v2_payload()
        event = append_event(
            event_type=SystemEvent.EventType.ROLE_ASSIGNED,
            aggregate_type="RoleAssignment",
            aggregate_id="manual",
            payload_json=payload,
        )
        self.assertEqual(event.payload_json, payload)

    def test_append_event_rejects_denylist_key_in_public_facts(self):
        payload = self._v2_payload()
        payload["public_facts"]["contact"] = "should-not-appear"
        with self.assertRaisesMessage(ValueError, "contact"):
            append_event(
                event_type=SystemEvent.EventType.ROLE_ASSIGNED,
                aggregate_type="RoleAssignment",
                aggregate_id="manual",
                payload_json=payload,
            )

    def test_append_event_rejects_denylist_key_at_top_level(self):
        payload = self._v2_payload()
        payload["member_no"] = "secret-member-no"
        with self.assertRaisesMessage(ValueError, "member_no"):
            append_event(
                event_type=SystemEvent.EventType.ROLE_ASSIGNED,
                aggregate_type="RoleAssignment",
                aggregate_id="manual",
                payload_json=payload,
            )

    def test_append_event_rejects_denylist_key_in_subject(self):
        payload = self._v2_payload()
        payload["subject"]["member_no"] = "secret-member-no"
        with self.assertRaisesMessage(ValueError, "member_no"):
            append_event(
                event_type=SystemEvent.EventType.ROLE_ASSIGNED,
                aggregate_type="RoleAssignment",
                aggregate_id="manual",
                payload_json=payload,
            )

    def test_append_event_rejects_extra_key_in_private_commitments(self):
        payload = self._v2_payload()
        payload["private_commitments"] = [
            {"name": "contact", "present": True, "reason": "x", "raw_value": "secret"}
        ]
        with self.assertRaisesMessage(ValueError, "raw_value"):
            append_event(
                event_type=SystemEvent.EventType.ROLE_ASSIGNED,
                aggregate_type="RoleAssignment",
                aggregate_id="manual",
                payload_json=payload,
            )

    def test_append_event_allows_denylist_name_in_private_commitments(self):
        payload = self._v2_payload()
        payload["private_commitments"] = [
            {"name": "contact", "present": True, "reason": "联系方式不公开"},
            {"name": "email", "present": True, "reason": "邮箱不公开"},
            {"name": "member_no", "present": True, "reason": "成员编号不公开"},
            {"name": "proposal_id", "present": True, "reason": "提案内部ID"},
            {"name": "role_id", "present": True, "reason": "角色内部ID"},
            {"name": "contact_info", "present": True, "reason": "联系方式不公开"},
        ]
        event = append_event(
            event_type=SystemEvent.EventType.ROLE_ASSIGNED,
            aggregate_type="RoleAssignment",
            aggregate_id="manual",
            payload_json=payload,
        )
        self.assertEqual(len(event.payload_json["private_commitments"]), 6)

    def test_append_event_rejects_proposal_id_in_public_facts(self):
        payload = self._v2_payload()
        payload["public_facts"]["proposal_id"] = "internal-pk"
        with self.assertRaisesMessage(ValueError, "proposal_id"):
            append_event(
                event_type=SystemEvent.EventType.ROLE_ASSIGNED,
                aggregate_type="RoleAssignment",
                aggregate_id="manual",
                payload_json=payload,
            )

    def test_append_event_rejects_role_id_in_public_facts(self):
        payload = self._v2_payload()
        payload["public_facts"]["role_id"] = "internal-pk"
        with self.assertRaisesMessage(ValueError, "role_id"):
            append_event(
                event_type=SystemEvent.EventType.ROLE_ASSIGNED,
                aggregate_type="RoleAssignment",
                aggregate_id="manual",
                payload_json=payload,
            )

    def test_append_event_rejects_display_name_in_public_facts(self):
        payload = self._v2_payload()
        payload["public_facts"]["display_name"] = "真实姓名"
        with self.assertRaisesMessage(ValueError, "display_name"):
            append_event(
                event_type=SystemEvent.EventType.ROLE_ASSIGNED,
                aggregate_type="RoleAssignment",
                aggregate_id="manual",
                payload_json=payload,
            )

    def test_append_event_rejects_contact_info_in_public_facts(self):
        payload = self._v2_payload()
        payload["public_facts"]["contact_info"] = "secret"
        with self.assertRaisesMessage(ValueError, "contact_info"):
            append_event(
                event_type=SystemEvent.EventType.ROLE_ASSIGNED,
                aggregate_type="RoleAssignment",
                aggregate_id="manual",
                payload_json=payload,
            )

    def test_append_event_rejects_nested_denylist_key(self):
        payload = self._v2_payload()
        payload["public_facts"]["details"] = {"member_no": "secret-nested"}
        with self.assertRaisesMessage(ValueError, "member_no"):
            append_event(
                event_type=SystemEvent.EventType.ROLE_ASSIGNED,
                aggregate_type="RoleAssignment",
                aggregate_id="manual",
                payload_json=payload,
            )

    def test_resource_adjustment_payload_with_empty_name_uses_resource_id_fallback(self):
        from core.event_ledger import validate_public_ledger_payload
        from core.event_payloads import resource_adjustment_payload

        resource = Resource.objects.create(
            resource_id="res-no-name",
            resource_type=Resource.ResourceType.TOOLS,
            unit=Resource.Unit.COUNT,
            current_stock=10,
            daily_consumption_estimate=1,
            replenishment_method=Resource.ReplenishmentMethod.MANUAL_ADJUSTMENT,
            loss_rate=0,
            warning_threshold=5,
            shortage_impact={},
            updated_at=timezone.now(),
            rule_version="v1",
        )
        p = resource_adjustment_payload(
            resource=resource,
            delta=3,
            reason="补充",
            warning=False,
            old_stock=10,
        )
        self.assertEqual(p["subject"]["label"], "res-no-name")
        self.assertEqual(p["public_facts"]["name"], "res-no-name")
        validate_public_ledger_payload(p)  # must not raise
