"""在一个明确 world 中探测新制度的 OpenFGA 具体能力。"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from core.authorization_services import (
    OPENFGA_AUTHORIZATION_MODEL_VERSION,
    AuthorizationService,
    openfga_context_for_world_kind,
)
from core.governance_setup import MAINTENANCE_VIEW_ADMIN_PERMISSION
from core.models import Member, Proposal
from worlds.command_context import command_world_context


class Command(BaseCommand):
    help = "探测一个 world 中的维护能力或指定提案投票能力。"

    def add_arguments(self, parser):
        parser.add_argument("--world-id", default="")
        parser.add_argument("--world-kind", choices=("real", "sim"), default=None)
        parser.add_argument("--capability", choices=("maintenance", "proposal_vote"), default="maintenance")
        parser.add_argument("--permission-code", default=MAINTENANCE_VIEW_ADMIN_PERMISSION)
        parser.add_argument("--proposal-id", type=int, default=None)
        parser.add_argument("--member-no", default="")
        parser.add_argument("--limit", type=int, default=20)

    def handle(self, *args, **options):
        with command_world_context(options["world_id"], command_name="openfga_authorization_probe"):
            context = openfga_context_for_world_kind(options["world_kind"])
            if not context.store_id or not context.authorization_model_id:
                raise CommandError(f"{context.world_kind} OpenFGA store 和 authorization model 必须配置。")

            capability = options["capability"]
            proposal = self._proposal_for_capability(capability=capability, proposal_id=options["proposal_id"])
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
                if capability == "maintenance":
                    allowed = authorization.member_can_maintain(
                        member=member,
                        permission_code=options["permission_code"],
                    )
                    target = options["permission_code"]
                else:
                    allowed = authorization.member_can_vote_on_proposal(member=member, proposal=proposal)
                    target = f"proposal:{proposal.pk}"
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

    @staticmethod
    def _proposal_for_capability(*, capability: str, proposal_id: int | None) -> Proposal | None:
        if capability != "proposal_vote":
            return None
        if proposal_id is None:
            raise CommandError("探测提案投票能力时必须提供 --proposal-id。")
        try:
            return Proposal.objects.get(pk=proposal_id)
        except Proposal.DoesNotExist as exc:
            raise CommandError(f"提案不存在：{proposal_id}") from exc


def _probe_members(*, member_no: str, limit: int) -> list[Member]:
    checked_member_no = str(member_no or "").strip()
    if checked_member_no:
        return list(Member.objects.filter(member_no=checked_member_no).order_by("pk"))
    return list(Member.objects.order_by("pk")[: max(limit, 1)])
