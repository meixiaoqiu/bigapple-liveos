"""在一个明确 world 中探测新制度的 OpenFGA 具体能力。"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from core.authorization_services import (
    OPENFGA_AUTHORIZATION_MODEL_VERSION,
    AuthorizationService,
    openfga_context_for_world_kind,
)
from core.governance_setup import ADMINISTRATION_VIEW_ADMIN_PERMISSION
from core.models import Member
from worlds.command_context import command_world_context


class Command(BaseCommand):
    help = "探测一个 world 中的维护能力。"

    def add_arguments(self, parser):
        parser.add_argument("--world-id", default="")
        parser.add_argument("--world-kind", choices=("real", "sim"), default=None)
        parser.add_argument("--capability", choices=("administration",), default="administration")
        parser.add_argument("--permission-code", default=ADMINISTRATION_VIEW_ADMIN_PERMISSION)
        parser.add_argument("--member-no", default="")
        parser.add_argument("--limit", type=int, default=20)

    def handle(self, *args, **options):
        with command_world_context(options["world_id"], command_name="openfga_authorization_probe"):
            context = openfga_context_for_world_kind(options["world_kind"])
            if not context.store_id or not context.authorization_model_id:
                raise CommandError(f"{context.world_kind} OpenFGA store 和 authorization model 必须配置。")

            capability = options["capability"]
            members = _probe_members(member_no=options["member_no"], limit=options["limit"])
            authorization = AuthorizationService()
            self.stdout.write(
                " ".join(
                    [
                        f"world_kind={context.world_kind}",
                        f"model={OPENFGA_AUTHORIZATION_MODEL_VERSION}",
                        f"capability={capability}",
                        f"candidates={len(members)}",
                    ]
                )
            )
            for member in members:
                allowed = authorization.member_can_administer(
                    member=member,
                    permission_code=options["permission_code"],
                )
                target = options["permission_code"]
                self.stdout.write(
                    " ".join(
                        [
                            f"member_id={member.pk}",
                            f"member_no={member.member_no}",
                            f"target={target}",
                            f"allowed={str(bool(allowed)).lower()}",
                        ]
                    )
                )

def _probe_members(*, member_no: str, limit: int) -> list[Member]:
    checked_member_no = str(member_no or "").strip()
    if checked_member_no:
        return list(Member.objects.filter(member_no=checked_member_no).order_by("pk"))
    return list(Member.objects.order_by("pk")[: max(limit, 1)])
