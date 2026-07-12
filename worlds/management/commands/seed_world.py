from __future__ import annotations

import os

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from live_os.demo_seed.zero_start import seed_zero_start
from worlds.context import context_from_registry
from worlds.lifecycle import get_world_or_error
from worlds.models import WorldRegistry
from worlds.state import reset_current_world, set_current_world


SIMULATION_BOOTSTRAP_ADMIN_ENABLED = "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_ENABLED"
SIMULATION_BOOTSTRAP_ADMIN_USERNAME = "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_USERNAME"
SIMULATION_BOOTSTRAP_ADMIN_PASSWORD = "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_PASSWORD"
SIMULATION_BOOTSTRAP_ADMIN_EMAIL = "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_EMAIL"
SIMULATION_BOOTSTRAP_ADMIN_MEMBER_NO = "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_MEMBER_NO"
SIMULATION_BOOTSTRAP_ADMIN_DISPLAY_NAME = "BIG_APPLE_SIMULATION_BOOTSTRAP_ADMIN_DISPLAY_NAME"


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
        bootstrap_admin = self._simulation_bootstrap_admin_config()

        token = set_current_world(world_context)
        try:
            if template == "demo":
                call_command("seed_demo", stdout=self.stdout, stderr=self.stderr)
            elif template == "zero_start":
                seed_zero_start()
            else:  # pragma: no cover - argparse choices prevent this.
                raise CommandError(f"Unsupported world seed template: {template}")
            if bootstrap_admin is not None:
                self._ensure_simulation_bootstrap_admin(world, bootstrap_admin)
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

    def _simulation_bootstrap_admin_config(self) -> dict[str, str] | None:
        """Return validated simulation bootstrap admin config from env.

        The account is opt-in through env variables so public and CI runs do
        not silently create a user. When explicitly enabled, missing or
        placeholder credentials are configuration errors and fail before any
        seed data is written.
        """

        if not self._env_bool(SIMULATION_BOOTSTRAP_ADMIN_ENABLED, default=False):
            return None

        username = os.environ.get(SIMULATION_BOOTSTRAP_ADMIN_USERNAME, "").strip()
        password = os.environ.get(SIMULATION_BOOTSTRAP_ADMIN_PASSWORD, "").strip()
        if not username:
            raise CommandError(
                f"{SIMULATION_BOOTSTRAP_ADMIN_USERNAME} must be set when "
                f"{SIMULATION_BOOTSTRAP_ADMIN_ENABLED}=true."
            )
        if not password:
            raise CommandError(
                f"{SIMULATION_BOOTSTRAP_ADMIN_PASSWORD} must be set when "
                f"{SIMULATION_BOOTSTRAP_ADMIN_ENABLED}=true."
            )
        if password == "CHANGE_ME":
            raise CommandError(
                f"{SIMULATION_BOOTSTRAP_ADMIN_PASSWORD} must be changed before bootstrap admin creation."
            )

        member_no = os.environ.get(SIMULATION_BOOTSTRAP_ADMIN_MEMBER_NO, username).strip() or username
        display_name = os.environ.get(SIMULATION_BOOTSTRAP_ADMIN_DISPLAY_NAME, username).strip() or username
        email = os.environ.get(SIMULATION_BOOTSTRAP_ADMIN_EMAIL, "").strip()
        return {
            "username": username,
            "password": password,
            "member_no": member_no,
            "display_name": display_name,
            "email": email,
        }

    def _ensure_simulation_bootstrap_admin(self, world: WorldRegistry, config: dict[str, str]) -> None:
        """Ensure the configured first simulation administrator exists.

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
            world_admin_username=config["username"],
            world_admin_password=config["password"],
            world_admin_email=config["email"],
            world_admin_member_no=config["member_no"],
            world_admin_display_name=config["display_name"],
            stdout=self.stdout,
            stderr=self.stderr,
        )

    def _env_bool(self, key: str, *, default: bool) -> bool:
        value = os.environ.get(key)
        if value is None or not value.strip():
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}
