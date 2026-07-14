"""Repair old MemberApplication records that lack an admission proposal.

After migrating from the standalone-review state machine, some applications
may have been created without an auto-linked member_admission Proposal (e.g.
records created via simulation before the auto-proposal flow existed, or
applications stuck in the old candidate / standby states).

This command finds such applications in a single world database and creates
the missing proposals so they can continue through the governance voting
pipeline.

Usage (one world at a time):

    python manage.py repair_member_admission_proposals --world-id realworld --dry-run
    python manage.py repair_member_admission_proposals --world-id realworld
    python manage.py repair_member_admission_proposals --world-id simulation0001 --dry-run
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from core.application_services import create_member_application_admission_proposal
from core.models import MemberApplication
from worlds.command_context import command_world_context


class Command(BaseCommand):
    help = "Create missing member_admission proposals for applications in one world database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--world-id",
            required=True,
            help="World to repair (e.g. realworld or simulation0001).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be done without making changes.",
        )

    def handle(self, **options):
        world_id = str(options["world_id"]).strip()
        dry_run = options["dry_run"]

        # Activate the world context so all ORM read/write targets the
        # correct world database, not the control DB default router.
        with command_world_context(world_id, command_name="repair_member_admission_proposals") as world_ctx:
            if world_ctx is None:
                raise CommandError(f"Failed to activate world context for: {world_id}")

            # Applications that have a linked_member but no admission_proposal.
            orphan_apps = MemberApplication.objects.filter(
                linked_member__isnull=False,
                admission_proposal__isnull=True,
            ).order_by("submitted_at", "application_id")

            count = orphan_apps.count()
            if count == 0:
                self.stdout.write(self.style.SUCCESS("所有报名均已关联准入提案，无需修复。"))
                return

            if dry_run:
                self.stdout.write(
                    f"[world={world_id}] 将修复 {count} 条报名（dry-run，未实际写入）："
                )
                for app in orphan_apps:
                    self.stdout.write(f"  {app.application_id}  {app.applicant_name}")
                return

            succeeded = 0
            failed: list[str] = []
            for app in orphan_apps:
                try:
                    create_member_application_admission_proposal(
                        application=app,
                        reason="修复命令自动补建准入提案。",
                    )
                except Exception as exc:
                    failed.append(f"{app.application_id}: {exc}")
                else:
                    succeeded += 1

            if succeeded:
                self.stdout.write(
                    self.style.SUCCESS(f"[world={world_id}] 已补建 {succeeded} 条准入提案。")
                )
            if failed:
                self.stdout.write(self.style.WARNING("以下报名补建失败："))
                for msg in failed:
                    self.stdout.write(self.style.ERROR(f"  {msg}"))
