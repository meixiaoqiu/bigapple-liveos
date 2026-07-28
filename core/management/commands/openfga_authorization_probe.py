"""Compare legacy authorization with OpenFGA for a world."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from core.authorization_services import openfga_check_for_member_permission, openfga_context_for_world_kind
from core.governance_setup import GOVERNANCE_VIEW_ADMIN_PERMISSION
from core.models import Member
from core.openfga_client import OpenFGAClient, OpenFGARequestError
from core.permission_services import legacy_member_has_permission, members_with_permission
from worlds.command_context import command_world_context


class Command(BaseCommand):
    help = "Compare legacy Django authorization with OpenFGA checks for one world."

    def add_arguments(self, parser):
        parser.add_argument("--world-id", default="")
        parser.add_argument("--world-kind", choices=("real", "sim"), default=None)
        parser.add_argument("--permission-code", default=GOVERNANCE_VIEW_ADMIN_PERMISSION)
        parser.add_argument("--member-no", default="")
        parser.add_argument("--api-url", default="")
        parser.add_argument("--store-id", default="")
        parser.add_argument("--authorization-model-id", default="")
        parser.add_argument("--limit", type=int, default=20)
        parser.add_argument("--fail-on-diff", action="store_true")

    def handle(self, *args, **options):
        permission_code = options["permission_code"]
        with command_world_context(options["world_id"], command_name="openfga_authorization_probe"):
            context = openfga_context_for_world_kind(options["world_kind"])
            store_id = options["store_id"] or context.store_id
            if not store_id:
                raise CommandError(f"{context.world_kind} OpenFGA store id is required.")

            members = list(_probe_members(permission_code, member_no=options["member_no"], limit=options["limit"]))
            client = OpenFGAClient(options["api_url"] or context.api_url)
            diffs = 0
            self.stdout.write(
                f"world_kind={context.world_kind} permission={permission_code} candidates={len(members)}"
            )
            for member in members:
                legacy_allowed = legacy_member_has_permission(member, permission_code)
                check = openfga_check_for_member_permission(member, permission_code)
                try:
                    openfga_allowed = client.check(
                        store_id=store_id,
                        authorization_model_id=options["authorization_model_id"] or context.authorization_model_id,
                        user=check.user,
                        relation=check.relation,
                        object_=check.object_,
                    )
                except OpenFGARequestError as exc:
                    raise CommandError(str(exc)) from exc

                status = "OK" if legacy_allowed == openfga_allowed else "DIFF"
                if status == "DIFF":
                    diffs += 1
                self.stdout.write(
                    " ".join(
                        [
                            f"member_id={member.pk}",
                            f"member_no={member.member_no}",
                            f"legacy={legacy_allowed}",
                            f"openfga={openfga_allowed}",
                            f"status={status}",
                        ]
                    )
                )

            self.stdout.write(self.style.SUCCESS(f"checked={len(members)} diffs={diffs}"))
            if diffs and options["fail_on_diff"]:
                raise CommandError(f"OpenFGA authorization probe found {diffs} differences.")


def _probe_members(permission_code: str, *, member_no: str, limit: int):
    checked_member_no = str(member_no or "").strip()
    if checked_member_no:
        return Member.objects.filter(member_no=checked_member_no).order_by("pk")
    return members_with_permission(permission_code).order_by("pk")[: max(limit, 1)]
