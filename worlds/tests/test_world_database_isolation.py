from __future__ import annotations

from contextlib import suppress

from django.contrib.auth import get_user_model
from django.db import connections
from django.db.utils import OperationalError
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from core.event_ledger import PUBLIC_LEDGER_SCHEMA, append_event
from core.credit_services import ensure_system_accounts, issue_credits_to_pool
from core.models import (
    ApprovalProposal,
    CreditAccount,
    CreditTransaction,
    ElectorateRuleTemplate,
    ElectorateRuleVersion,
    LedgerEntry,
    Member,
    Organization,
    ProposalBallot,
    ProposalElectorSnapshot,
    ProposalExecutionRecord,
    ProposalResolution,
    Role,
    RoleAssignment,
    SystemEvent,
    Task,
)
from core.service_utils import actor_ref
from core.tasks.authoring import create_task_draft
from core.tasks.funding import fund_and_publish_task
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
    databases = {"default", "realworld", "simulation0001"}
    world_databases = {"realworld", "simulation0001"}

    def setUp(self) -> None:
        for alias in self.world_databases:
            self.create_member_table(alias)

    def tearDown(self) -> None:
        for alias in self.world_databases:
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
            schema_editor.create_model(Task)
            schema_editor.create_model(LedgerEntry)
            schema_editor.create_model(CreditAccount)
            schema_editor.create_model(CreditTransaction)
            schema_editor.create_model(ElectorateRuleTemplate)
            schema_editor.create_model(ElectorateRuleVersion)
            schema_editor.create_model(ApprovalProposal)
            schema_editor.create_model(ProposalElectorSnapshot)
            schema_editor.create_model(ProposalBallot)
            schema_editor.create_model(ProposalResolution)
            schema_editor.create_model(ProposalExecutionRecord)

    def drop_member_table(self, alias: str) -> None:
        connection = connections[alias]
        for model in (CreditTransaction, CreditAccount, LedgerEntry, Task):
            table_names = connection.introspection.table_names()
            with suppress(OperationalError):
                if model._meta.db_table in table_names:
                    with connection.schema_editor() as schema_editor:
                        schema_editor.delete_model(model)
        for model in (
            ProposalExecutionRecord,
            ProposalResolution,
            ProposalBallot,
            ProposalElectorSnapshot,
            ApprovalProposal,
            ElectorateRuleVersion,
            ElectorateRuleTemplate,
        ):
            table_names = connection.introspection.table_names()
            with suppress(OperationalError):
                if model._meta.db_table in table_names:
                    with connection.schema_editor() as schema_editor:
                        schema_editor.delete_model(model)
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

    def fund_and_publish_in_world(self, world: WorldContext, suffix: str) -> str:
        token = set_current_world(world)
        try:
            # This focused isolation fixture creates only the authority tables
            # touched by the workflow; unrelated nullable FK target tables are
            # intentionally absent.
            with connections[world.database_alias].constraint_checks_disabled():
                member = Member.objects.create(
                    member_no=f"funding-member-{suffix}",
                    display_name=f"预算发布成员 {suffix}",
                    status=Member.Status.ACTIVE,
                    batch_id="funding-isolation",
                    joined_simulation_day=1,
                    credit_floor=-100,
                    profile={},
                    created_at=timezone.now(),
                )
                ensure_system_accounts()
                issue_credits_to_pool(
                    amount=50,
                    reason="world 隔离测试发行",
                    initiated_by=member,
                    reviewed_by=member,
                )
                task = create_task_draft(
                    title=f"world 隔离发布任务 {suffix}",
                    task_type=Task.TaskType.PUBLIC_CLEANING,
                    standard_minutes=60,
                    base_points=30,
                    role_coefficient=1,
                    failure_consequence="",
                    can_be_delayed=True,
                    requires_review=True,
                    rule_version="ruleset-v0.1.0",
                    created_by=actor_ref(member),
                )
                result = fund_and_publish_task(
                    task=task,
                    publisher=actor_ref(member),
                    initiated_by=member,
                )
                self.assertTrue(result.published)
                return task.pk
        finally:
            reset_current_world(token)

    def funded_publication_facts(self, world: WorldContext) -> tuple[set[str], set[str], set[str]]:
        token = set_current_world(world)
        try:
            return (
                set(Task.objects.values_list("task_id", flat=True)),
                set(
                    CreditTransaction.objects.filter(
                        transaction_type=CreditTransaction.Type.LOCK,
                    ).values_list("related_task_id", flat=True)
                ),
                set(
                    SystemEvent.objects.filter(
                        event_type=SystemEvent.EventType.TASK_PUBLISHED,
                    ).values_list("aggregate_id", flat=True)
                ),
            )
        finally:
            reset_current_world(token)

    def test_funded_publication_writes_only_to_bound_world_database(self) -> None:
        realworld = self.world_context("realworld", "realworld")
        simulation = self.world_context("simulation0001", "simulation0001")

        real_task_id = self.fund_and_publish_in_world(realworld, "real")
        self.assertEqual(
            self.funded_publication_facts(realworld),
            ({real_task_id}, {real_task_id}, {real_task_id}),
        )
        self.assertEqual(self.funded_publication_facts(simulation), (set(), set(), set()))

        simulation_task_id = self.fund_and_publish_in_world(simulation, "simulation")
        self.assertEqual(
            self.funded_publication_facts(simulation),
            ({simulation_task_id}, {simulation_task_id}, {simulation_task_id}),
        )
        self.assertEqual(
            self.funded_publication_facts(realworld),
            ({real_task_id}, {real_task_id}, {real_task_id}),
        )
        self.assertFalse(
            Task.objects.using("default").filter(
                task_id__in=[real_task_id, simulation_task_id],
            ).exists()
        )
        self.assertFalse(
            CreditTransaction.objects.using("default").filter(
                related_task_id__in=[real_task_id, simulation_task_id],
            ).exists()
        )
        self.assertFalse(
            SystemEvent.objects.using("default").filter(
                aggregate_id__in=[real_task_id, simulation_task_id],
            ).exists()
        )

    def create_unified_proposal_facts(self, world: WorldContext, suffix: str) -> None:
        token = set_current_world(world)
        try:
            member = Member.objects.create(
                member_no=f"proposal-member-{suffix}",
                display_name=f"提案成员 {suffix}",
                status=Member.Status.ACTIVE,
                batch_id="proposal-isolation",
                joined_simulation_day=1,
                credit_floor=-100,
                profile={},
                created_at=timezone.now(),
            )
            organization = Organization.objects.create(name=f"角色目录 {suffix}")
            role = Role.objects.create(organization=organization, name=f"守约者 {suffix}")
            RoleAssignment.objects.create(
                member=member,
                role=role,
                start_at=timezone.now(),
                end_at=timezone.now() + timezone.timedelta(days=365),
            )
            template = ElectorateRuleTemplate.objects.create(
                rule_code=f"member-admission-{suffix}",
                proposal_type=ApprovalProposal.ProposalType.MEMBER_APPLICATION,
                name="守约者准入",
                created_by=member,
            )
            version = ElectorateRuleVersion.objects.create(
                rule_version_id=f"rule-version-{suffix}",
                template=template,
                version=1,
                selector_config={"role_code": "covenanter"},
                approve_threshold=1,
                reject_threshold=1,
                minimum_participation=1,
                voting_duration_hours=24,
                unresolved_outcome=ElectorateRuleVersion.UnresolvedOutcome.EXPIRED,
                published_by=member,
            )
            proposal = ApprovalProposal.objects.create(
                proposal_id=f"proposal-{suffix}",
                proposal_type=ApprovalProposal.ProposalType.MEMBER_APPLICATION,
                title="守约者准入提案",
                status=ApprovalProposal.Status.EXECUTED,
                strategy_type=ApprovalProposal.StrategyType.ELECTORATE,
                dedupe_key=f"member-admission:{suffix}",
                submitted_by=member,
                electorate_rule_version=version,
            )
            ProposalElectorSnapshot.objects.create(
                proposal=proposal, member=member, rule_version=version,
            )
            ProposalBallot.objects.create(
                ballot_id=f"ballot-{suffix}", proposal=proposal, voter=member, revision=1, choice="approve",
            )
            ProposalResolution.objects.create(
                proposal=proposal,
                outcome=ProposalResolution.Outcome.APPROVED,
                reason_code="approve_threshold_reached",
                evidence={"approve_count": 1},
                decided_by=member,
            )
            ProposalExecutionRecord.objects.create(
                execution_id=f"execution-{suffix}",
                proposal=proposal,
                idempotency_key=f"proposal:{suffix}",
                executed_by=member,
                status=ProposalExecutionRecord.Status.SUCCEEDED,
            )
        finally:
            reset_current_world(token)

    def unified_proposal_counts(self, world: WorldContext) -> tuple[int, ...]:
        token = set_current_world(world)
        try:
            return (
                ElectorateRuleVersion.objects.count(),
                ApprovalProposal.objects.count(),
                ProposalElectorSnapshot.objects.count(),
                ProposalBallot.objects.count(),
                ProposalResolution.objects.count(),
                ProposalExecutionRecord.objects.count(),
                RoleAssignment.objects.count(),
            )
        finally:
            reset_current_world(token)

    def test_unified_proposal_facts_stay_inside_current_world_database(self) -> None:
        realworld = self.world_context("realworld", "realworld")
        simulation = self.world_context("simulation0001", "simulation0001")

        self.create_unified_proposal_facts(simulation, "sim")
        self.assertEqual(self.unified_proposal_counts(simulation), (1, 1, 1, 1, 1, 1, 1))
        self.assertEqual(self.unified_proposal_counts(realworld), (0, 0, 0, 0, 0, 0, 0))

        self.create_unified_proposal_facts(realworld, "real")
        self.assertEqual(self.unified_proposal_counts(realworld), (1, 1, 1, 1, 1, 1, 1))
        self.assertEqual(self.unified_proposal_counts(simulation), (1, 1, 1, 1, 1, 1, 1))
