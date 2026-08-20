from __future__ import annotations

import os

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from live_os.demo_seed.zero_start import seed_zero_start
from worlds.context import context_from_registry
from worlds.lifecycle import get_world_or_error
from worlds.models import WorldRegistry
from worlds.state import reset_current_world, set_current_world


SIMULATION_BOOTSTRAP_ADMINISTRATOR_ENABLED = "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMINISTRATOR_ENABLED"
SIMULATION_BOOTSTRAP_ADMINISTRATOR_USERNAME = "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMINISTRATOR_USERNAME"
SIMULATION_BOOTSTRAP_ADMINISTRATOR_PASSWORD = "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMINISTRATOR_PASSWORD"
SIMULATION_BOOTSTRAP_ADMINISTRATOR_EMAIL = "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMINISTRATOR_EMAIL"
SIMULATION_BOOTSTRAP_ADMINISTRATOR_MEMBER_NO = "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMINISTRATOR_MEMBER_NO"
SIMULATION_BOOTSTRAP_ADMINISTRATOR_DISPLAY_NAME = "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMINISTRATOR_DISPLAY_NAME"


class Command(BaseCommand):
    help = "Seed an active simulation world from a safe, idempotent template."

    def add_arguments(self, parser):
        parser.add_argument("world_id")
        parser.add_argument(
            "--template",
            choices=["demo", "zero_start"],
            default="demo",
            help="World seed template. Use zero_start for a founder-only baseline.",
        )

    def handle(self, *args, **options):
        world = get_world_or_error(options["world_id"])
        if world.status != WorldRegistry.Status.ACTIVE:
            raise CommandError(f"World is not active: {world.world_id} ({world.status})")
        if world.world_type != WorldRegistry.WorldType.SIMULATION:
            raise CommandError(f"Refusing to seed non-simulation world: {world.world_id}")

        template = options["template"]
        world_context = context_from_registry(world)
        database_alias = self._effective_world_alias(world_context.database_alias)
        bootstrap_administrator = self._simulation_bootstrap_administrator_config()

        token = set_current_world(world_context)
        try:
            if template == "demo":
                call_command("seed_demo", stdout=self.stdout, stderr=self.stderr)
            elif template == "zero_start":
                if bootstrap_administrator is not None:
                    self._ensure_simulation_bootstrap_administrator(world, bootstrap_administrator)
                    seed_zero_start(
                        founder_member_no=bootstrap_administrator["member_no"],
                        founder_display_name=bootstrap_administrator["display_name"],
                    )
                    with transaction.atomic(using=database_alias):
                        self._ensure_simulation_admission_policy(bootstrap_administrator["member_no"])
                else:
                    seed_zero_start()
            else:  # pragma: no cover - argparse choices prevent this.
                raise CommandError(f"Unsupported world seed template: {template}")
            if bootstrap_administrator is not None and template != "zero_start":
                self._ensure_simulation_bootstrap_administrator(world, bootstrap_administrator)
            from core.deliberator_exam_services import ensure_simulation_exam_baseline

            ensure_simulation_exam_baseline(world_type=world.world_type)
        finally:
            reset_current_world(token)

        self.stdout.write(
            self.style.SUCCESS(
                f"seeded: world_id={world.world_id}, template={template}, database_alias={database_alias}"
            )
        )

    def _effective_world_alias(self, database_alias: str) -> str:
        if not getattr(settings, "WORLD_DATABASE_ROUTING_ENABLED", True):
            return "default"
        if database_alias not in settings.DATABASES:
            raise CommandError(f"World database alias is not configured: {database_alias}")
        return database_alias

    def _simulation_bootstrap_administrator_config(self) -> dict[str, str] | None:
        """Return validated simulation bootstrap administrator config from env.

        The account is opt-in through env variables so public and CI runs do
        not silently create a user. When explicitly enabled, missing or
        placeholder credentials are configuration errors and fail before any
        seed data is written.
        """

        if not self._env_bool(SIMULATION_BOOTSTRAP_ADMINISTRATOR_ENABLED, default=False):
            return None

        username = os.environ.get(SIMULATION_BOOTSTRAP_ADMINISTRATOR_USERNAME, "").strip()
        password = os.environ.get(SIMULATION_BOOTSTRAP_ADMINISTRATOR_PASSWORD, "").strip()
        if not username:
            raise CommandError(
                f"{SIMULATION_BOOTSTRAP_ADMINISTRATOR_USERNAME} must be set when "
                f"{SIMULATION_BOOTSTRAP_ADMINISTRATOR_ENABLED}=true."
            )
        if not password:
            raise CommandError(
                f"{SIMULATION_BOOTSTRAP_ADMINISTRATOR_PASSWORD} must be set when "
                f"{SIMULATION_BOOTSTRAP_ADMINISTRATOR_ENABLED}=true."
            )
        if password == "CHANGE_ME":
            raise CommandError(
                f"{SIMULATION_BOOTSTRAP_ADMINISTRATOR_PASSWORD} must be changed before bootstrap administrator creation."
            )

        member_no = os.environ.get(SIMULATION_BOOTSTRAP_ADMINISTRATOR_MEMBER_NO, username).strip() or username
        display_name = os.environ.get(SIMULATION_BOOTSTRAP_ADMINISTRATOR_DISPLAY_NAME, username).strip() or username
        email = os.environ.get(SIMULATION_BOOTSTRAP_ADMINISTRATOR_EMAIL, "").strip()
        return {
            "username": username,
            "password": password,
            "member_no": member_no,
            "display_name": display_name,
            "email": email,
        }

    def _ensure_simulation_bootstrap_administrator(self, world: WorldRegistry, config: dict[str, str]) -> None:
        """Ensure the configured simulation administrator exists.

        It delegates to bootstrap_world with skip_control_admin=True because
        simulation runtime login belongs to the target world database, not the
        control database. The delegated command binds the target world context
        and is idempotent for existing User, Member, and RoleAssignment
        records; failures intentionally fail seed_world so the bootstrap can
        be fixed and rerun.
        """

        call_command(
            "bootstrap_world",
            world_id=world.world_id,
            skip_control_admin=True,
            world_administrator_username=config["username"],
            world_administrator_password=config["password"],
            world_administrator_email=config["email"],
            world_administrator_member_no=config["member_no"],
            world_administrator_display_name=config["display_name"],
            stdout=self.stdout,
            stderr=self.stderr,
        )

    def _ensure_simulation_admission_policy(self, member_no: str) -> None:
        """为显式启用管理员的仿真基线幂等发布最小准入测试政策。"""

        from core.electorate_rule_services import (
            create_electorate_rule_template,
            latest_published_rule_for_proposal_type,
            publish_electorate_rule_version,
        )
        from core.models import ApprovalProposal, ElectorateRuleVersion, Member

        proposal_type = ApprovalProposal.ProposalType.MEMBER_APPLICATION
        if latest_published_rule_for_proposal_type(proposal_type) is not None:
            return
        actor = Member.objects.get(member_no=member_no)
        template = create_electorate_rule_template(
            proposal_type=proposal_type,
            rule_code="member-admission",
            name="守约者准入",
            description="仿真零起点基线使用的明确测试政策。",
            created_by=actor,
        )
        publish_electorate_rule_version(
            template=template,
            selector_config={"role_code": "administrator"},
            approve_threshold=1,
            reject_threshold=1,
            minimum_participation=1,
            voting_duration_hours=168,
            unresolved_outcome=ElectorateRuleVersion.UnresolvedOutcome.EXPIRED,
            published_by=actor,
        )

    def _env_bool(self, key: str, *, default: bool) -> bool:
        value = os.environ.get(key)
        if value is None or not value.strip():
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}
