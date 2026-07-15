from __future__ import annotations

from contextlib import suppress

from django.contrib.auth import get_user_model
from django.db import connections
from django.db.utils import OperationalError
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from core.event_ledger import PUBLIC_LEDGER_SCHEMA, append_event
from core.models import Member, Organization, Role, RoleAssignment, SystemEvent
from worlds.context import WorldContext
from worlds.models import WorldRegistry
from worlds.state import reset_current_world, set_current_world


def _v2_world_payload(world_id: str) -> dict:
    return {
        "schema": PUBLIC_LEDGER_SCHEMA,
        "subject": {"type": "world", "ref": world_id, "label": world_id},
        "action": "initialized",
        "stage": "initialized",
        "summary": f"World {world_id} initialized.",
        "public_facts": {"world_id": world_id},
        "private_commitments": [],
    }


@override_settings(
    WORLD_DATABASE_ROUTING_ENABLED=True,
    DEFAULT_WORLD_DATABASE_ALIAS="realworld",
    WORLD_DATABASE_ALIASES=("realworld", "simulation0001"),
)
class WorldDatabaseIsolationTests(TransactionTestCase):
    databases = {"realworld", "simulation0001"}

    def setUp(self) -> None:
        for alias in self.databases:
            self.create_member_table(alias)

    def tearDown(self) -> None:
        for alias in self.databases:
            self.drop_member_table(alias)

    def create_member_table(self, alias: str) -> None:
        self.drop_member_table(alias)
        with connections[alias].schema_editor() as schema_editor:
            schema_editor.create_model(get_user_model())
            schema_editor.create_model(Member)
            schema_editor.create_model(Organization)
            schema_editor.create_model(Role)
            schema_editor.create_model(RoleAssignment)
            schema_editor.create_model(SystemEvent)

    def drop_member_table(self, alias: str) -> None:
        connection = connections[alias]
        table_names = connection.introspection.table_names()
        with suppress(OperationalError):
            if SystemEvent._meta.db_table in table_names:
                with connection.schema_editor() as schema_editor:
                    schema_editor.delete_model(SystemEvent)
        table_names = connection.introspection.table_names()
        with suppress(OperationalError):
            if RoleAssignment._meta.db_table in table_names:
                with connection.schema_editor() as schema_editor:
                    schema_editor.delete_model(RoleAssignment)
        table_names = connection.introspection.table_names()
        with suppress(OperationalError):
            if Role._meta.db_table in table_names:
                with connection.schema_editor() as schema_editor:
                    schema_editor.delete_model(Role)
        table_names = connection.introspection.table_names()
        with suppress(OperationalError):
            if Organization._meta.db_table in table_names:
                with connection.schema_editor() as schema_editor:
                    schema_editor.delete_model(Organization)
        table_names = connection.introspection.table_names()
        with suppress(OperationalError):
            if Member._meta.db_table in table_names:
                with connection.schema_editor() as schema_editor:
                    schema_editor.delete_model(Member)
        with suppress(OperationalError):
            if get_user_model()._meta.db_table in connection.introspection.table_names():
                with connection.schema_editor() as schema_editor:
                    schema_editor.delete_model(get_user_model())

    def world_context(self, world_id: str, alias: str) -> WorldContext:
        return WorldContext(
            world_id=world_id,
            world_type=(
                WorldRegistry.WorldType.REAL
                if world_id == "realworld"
                else WorldRegistry.WorldType.SIMULATION
            ),
            database_alias=alias,
            database_name=f"test_{alias}",
        )

    def create_member_in_world(self, world: WorldContext, member_no: str) -> None:
        token = set_current_world(world)
        try:
            Member.objects.create(
                member_no=member_no,
                display_name=member_no,
                status=Member.Status.ACTIVE,
                batch_id="isolation-test",
                joined_simulation_day=1,
                credit_floor=-100,
                profile={},
                created_at=timezone.now(),
            )
        finally:
            reset_current_world(token)

    def member_numbers_for_world(self, world: WorldContext | None) -> set[str]:
        token = set_current_world(world)
        try:
            return set(Member.objects.values_list("member_no", flat=True))
        finally:
            reset_current_world(token)

    def append_event_in_world(self, world: WorldContext, aggregate_id: str) -> None:
        token = set_current_world(world)
        try:
            append_event(
                event_type=SystemEvent.EventType.SYSTEM_INITIALIZED,
                aggregate_type="World",
                aggregate_id=aggregate_id,
                payload_json=_v2_world_payload(world.world_id),
            )
        finally:
            reset_current_world(token)

    def event_payload_world_ids(self, world: WorldContext) -> set[str]:
        token = set_current_world(world)
        try:
            return set(SystemEvent.objects.values_list("payload_json__public_facts__world_id", flat=True))
        finally:
            reset_current_world(token)

    def test_core_model_reads_and_writes_stay_inside_current_world_database(self) -> None:
        realworld = self.world_context("realworld", "realworld")
        simulation = self.world_context("simulation0001", "simulation0001")

        self.create_member_in_world(realworld, "real-member-0001")
        self.create_member_in_world(simulation, "sim-member-0001")

        self.assertEqual(self.member_numbers_for_world(realworld), {"real-member-0001"})
        self.assertEqual(self.member_numbers_for_world(simulation), {"sim-member-0001"})

    def test_core_model_without_request_context_defaults_to_realworld_database(self) -> None:
        realworld = self.world_context("realworld", "realworld")
        simulation = self.world_context("simulation0001", "simulation0001")

        self.create_member_in_world(realworld, "real-member-0001")
        self.create_member_in_world(simulation, "sim-member-0001")

        self.assertEqual(self.member_numbers_for_world(None), {"real-member-0001"})

    def test_append_event_uses_the_current_world_database_transaction(self) -> None:
        realworld = self.world_context("realworld", "realworld")
        simulation = self.world_context("simulation0001", "simulation0001")

        self.append_event_in_world(realworld, "realworld")
        self.append_event_in_world(simulation, "simulation0001")

        self.assertEqual(self.event_payload_world_ids(realworld), {"realworld"})
        self.assertEqual(self.event_payload_world_ids(simulation), {"simulation0001"})
