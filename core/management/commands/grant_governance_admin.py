"""Grant the baseline governance-admin role to one existing Member."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from core.exceptions import DomainError
from core.governance_setup import ensure_governance_admin_role
from core.models import Member
from core.role_assignment_services import create_role_assignment
from worlds.command_context import command_world_context, command_world_label


class Command(BaseCommand):
    help = "Grant the initialized governance-admin role to one existing Member without changing Django User flags."

    def add_arguments(self, parser):
        parser.add_argument("--username", help="Django User username linked to the target Member.")
        parser.add_argument("--member-no", help="Target Member business number.")
        parser.add_argument(
            "--world-id",
            help="目标 world。运行时启用 world 数据库路由后，直接执行本命令必须显式提供。",
        )

    def handle(self, *args, **options):
        selectors = {
            "username": options.get("username"),
            "member_no": options.get("member_no"),
        }
        provided = {key: value for key, value in selectors.items() if value not in (None, "")}
        if len(provided) != 1:
            raise CommandError("Provide exactly one of --username or --member-no.")

        with command_world_context(options.get("world_id"), command_name="grant_governance_admin") as world:
            member = self._resolve_member(provided)
            result = ensure_governance_admin_role()
            role = result["role"]
            try:
                assignment = create_role_assignment(
                    member=member,
                    role=role,
                    source_type="direct",
                )
            except DomainError as exc:
                raise CommandError(
                    f"授予治理管理员角色失败：{exc}\n"
                    "授予治理管理员角色前，目标成员必须先成为正式成员（拥有 ROLE_FORMAL_MEMBER）。"
                    "本命令不会自动授予正式成员身份。请先通过正式成员准入流程或 bootstrap 完成正式成员认证。"
                ) from exc

            self.stdout.write(
                self.style.SUCCESS(
                    f"Governance admin role assignment created: world_id={command_world_label(world)}, "
                    f"member_no={member.member_no}, role_id={role.pk}, role_assignment_id={assignment.pk}. "
                    "Django User.is_staff and User.is_superuser were not changed."
                )
            )

    def _resolve_member(self, provided: dict[str, object]) -> Member:
        if "username" in provided:
            username = str(provided["username"]).strip()
            user_model = get_user_model()
            try:
                user = user_model.objects.get(username=username)
            except user_model.DoesNotExist as exc:
                raise CommandError(f"User not found: {username}") from exc
            member = Member.objects.filter(user=user).first()
            if member is None:
                member = Member.objects.filter(member_no=username).first()
            if member is None:
                raise CommandError(f"Member linked to user not found: {username}")
            return member

        member_no = str(provided["member_no"]).strip()
        try:
            return Member.objects.get(member_no=member_no)
        except Member.DoesNotExist as exc:
            raise CommandError(f"Member not found: {member_no}") from exc
