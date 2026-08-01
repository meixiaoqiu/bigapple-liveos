"""向已有成员授予典守者职责。"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from core.exceptions import DomainError
from core.governance_setup import ensure_maintainer_role
from core.models import Member
from core.role_assignment_services import create_role_assignment
from worlds.command_context import command_world_context, command_world_label


class Command(BaseCommand):
    help = "向一名已有成员授予典守者职责，不修改 Django User 标志。"

    def add_arguments(self, parser):
        parser.add_argument("--username", help="与目标成员关联的 Django User 用户名。")
        parser.add_argument("--member-no", help="目标成员业务编号。")
        parser.add_argument(
            "--world-id",
            help="目标 world。运行时启用 world 数据库路由后，直接执行本命令必须显式提供。",
        )

    def handle(self, *args, **options):
        selectors = {"username": options.get("username"), "member_no": options.get("member_no")}
        provided = {key: value for key, value in selectors.items() if value not in (None, "")}
        if len(provided) != 1:
            raise CommandError("必须且只能提供 --username 或 --member-no 其中之一。")

        with command_world_context(options.get("world_id"), command_name="grant_maintainer") as world:
            member = self._resolve_member(provided)
            role = ensure_maintainer_role()["role"]
            try:
                assignment = create_role_assignment(member=member, role=role, source_type="direct")
            except DomainError as exc:
                raise CommandError(
                    f"授予典守者职责失败：{exc}\n"
                    "目标成员必须先通过守约者准入；本命令不会自动授予守约者资格。"
                ) from exc

            self.stdout.write(
                self.style.SUCCESS(
                    "典守者任命已创建："
                    f"world_id={command_world_label(world)}，member_no={member.member_no}，"
                    f"role_id={role.pk}，role_assignment_id={assignment.pk}。"
                    "Django User.is_staff 和 User.is_superuser 未改变。"
                )
            )

    def _resolve_member(self, provided: dict[str, object]) -> Member:
        if "username" in provided:
            username = str(provided["username"]).strip()
            user_model = get_user_model()
            try:
                user = user_model.objects.get(username=username)
            except user_model.DoesNotExist as exc:
                raise CommandError(f"找不到登录账号：{username}") from exc
            member = Member.objects.filter(user=user).first() or Member.objects.filter(member_no=username).first()
            if member is None:
                raise CommandError(f"找不到与登录账号关联的成员：{username}")
            return member

        member_no = str(provided["member_no"]).strip()
        try:
            return Member.objects.get(member_no=member_no)
        except Member.DoesNotExist as exc:
            raise CommandError(f"找不到成员：{member_no}") from exc
