"""Repair: scan ROLE_FORMAL_MEMBER members and backfill formal member number credentials."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from core.credential_services import ensure_builtin_credential_templates, issue_formal_member_number
from core.member_roles import ROLE_FORMAL_MEMBER, member_has_role
from core.models import Member
from worlds.command_context import command_world_context, command_world_label


class Command(BaseCommand):
    help = "Backfill formal_member_number credentials for active ROLE_FORMAL_MEMBER members."

    def add_arguments(self, parser):
        parser.add_argument("--world-id", help="Target world.")
        parser.add_argument("--dry-run", action="store_true", default=False)

    def handle(self, *args, **options):
        world_id = options.get("world_id")
        if not world_id:
            raise CommandError("--world-id is required.")
        dry_run = bool(options.get("dry_run"))

        # Must enter world context *before* any ORM reads or writes.
        with command_world_context(world_id, command_name="repair_formal_member_credentials") as world:
            if not dry_run:
                ensure_builtin_credential_templates()

            members = Member.objects.all()
            issued = 0
            for member in members:
                if not member_has_role(member, ROLE_FORMAL_MEMBER):
                    continue
                existing = member.credential_grants.filter(
                    template__code="formal_member_number"
                ).exists()
                if existing:
                    continue
                if not dry_run:
                    issue_formal_member_number(member)
                issued += 1

            action = "Would issue" if dry_run else "Issued"
            self.stdout.write(
                self.style.SUCCESS(
                    f"{action} {issued} formal member number credential(s). "
                    f"world_id={command_world_label(world)}"
                )
            )