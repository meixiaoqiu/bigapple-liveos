from __future__ import annotations

import os
from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.finance_setup import ensure_finance_roles
from core.governance_setup import default_role_assignment_end_at, ensure_governance_admin_role
from core.member_roles import ensure_member_role
from core.models import Member, RoleAssignment
from core.role_assignment_services import bootstrap_first_governance_member
from worlds.context import DEFAULT_REALWORLD_ID, WorldContext, context_from_registry
from worlds.models import WorldRegistry
from worlds.state import reset_current_world, set_current_world


DEFAULT_WORLD_ADMIN_MEMBER_NO = "member-admin-0001"
DEFAULT_CONTROL_USERNAME = "wzy"


@dataclass(frozen=True)
class BootstrapResult:
    created: bool
    updated: bool
    label: str


class Command(BaseCommand):
    help = "Bootstrap control admin and one world governance administrator."

    def add_arguments(self, parser):
        parser.add_argument("--world-id", default=DEFAULT_REALWORLD_ID)
        parser.add_argument("--skip-control-admin", action="store_true")
        parser.add_argument("--skip-world-admin", action="store_true")
        parser.add_argument("--control-username", default=os.environ.get("BIG_APPLE_CONTROL_ADMIN_USERNAME", DEFAULT_CONTROL_USERNAME))
        parser.add_argument("--control-password", default=os.environ.get("BIG_APPLE_CONTROL_ADMIN_PASSWORD", ""))
        parser.add_argument("--control-email", default=os.environ.get("BIG_APPLE_CONTROL_ADMIN_EMAIL", ""))
        parser.add_argument("--world-admin-username", default=os.environ.get("BIG_APPLE_WORLD_ADMIN_USERNAME", ""))
        parser.add_argument("--world-admin-password", default=os.environ.get("BIG_APPLE_WORLD_ADMIN_PASSWORD", ""))
        parser.add_argument("--world-admin-email", default=os.environ.get("BIG_APPLE_WORLD_ADMIN_EMAIL", ""))
        parser.add_argument("--world-admin-member-no", default=os.environ.get("BIG_APPLE_WORLD_ADMIN_MEMBER_NO", DEFAULT_WORLD_ADMIN_MEMBER_NO))
        parser.add_argument("--world-admin-display-name", default=os.environ.get("BIG_APPLE_WORLD_ADMIN_DISPLAY_NAME", "World governance admin"))

    def handle(self, *args, **options):
        world = self._get_world(str(options["world_id"]).strip())
        world_context = context_from_registry(world)

        if options["skip_control_admin"] and options["skip_world_admin"]:
            raise CommandError("Nothing to bootstrap: both --skip-control-admin and --skip-world-admin were provided.")

        if not options["skip_control_admin"]:
            control_result = self._ensure_control_admin(
                username=str(options["control_username"]).strip(),
                password=str(options["control_password"] or ""),
                email=str(options["control_email"] or "").strip(),
            )
            self.stdout.write(self.style.SUCCESS(self._format_result(control_result)))

        if not options["skip_world_admin"]:
            username = str(options["world_admin_username"] or options["world_admin_member_no"]).strip()
            world_result = self._ensure_world_governance_admin(
                world_context,
                username=username,
                password=str(options["world_admin_password"] or ""),
                email=str(options["world_admin_email"] or "").strip(),
                member_no=str(options["world_admin_member_no"]).strip(),
                display_name=str(options["world_admin_display_name"]).strip(),
            )
            self.stdout.write(self.style.SUCCESS(self._format_result(world_result)))

        self.stdout.write(
            self.style.SUCCESS(
                f"Bootstrap complete: world_id={world.world_id}, database_alias={world.database_alias}."
            )
        )

    def _get_world(self, world_id: str) -> WorldRegistry:
        if not world_id:
            raise CommandError("--world-id cannot be empty.")
        try:
            return WorldRegistry.objects.using("default").get(world_id=world_id, status=WorldRegistry.Status.ACTIVE)
        except WorldRegistry.DoesNotExist as exc:
            raise CommandError(f"Active world not found in control registry: {world_id}") from exc

    def _effective_world_alias(self, world: WorldContext) -> str:
        if not getattr(settings, "WORLD_DATABASE_ROUTING_ENABLED", True):
            return "default"
        if world.database_alias not in settings.DATABASES:
            raise CommandError(f"World database alias is not configured: {world.database_alias}")
        return world.database_alias

    def _ensure_control_admin(self, *, username: str, password: str, email: str) -> BootstrapResult:
        if not username:
            raise CommandError("--control-username cannot be empty.")

        user_model = get_user_model()
        manager = user_model._default_manager.db_manager("default")
        user = manager.filter(username=username).first()
        created = user is None
        if created:
            if not password:
                raise CommandError("A new control admin requires --control-password or BIG_APPLE_CONTROL_ADMIN_PASSWORD.")
            user = user_model(username=username, email=email, is_staff=True, is_superuser=True, is_active=True)
            user.set_password(password)
            user.save(using="default")
            return BootstrapResult(created=True, updated=False, label=f"control_admin username={username}")

        changed = False
        if not user.is_staff or not user.is_superuser or not user.is_active:
            user.is_staff = True
            user.is_superuser = True
            user.is_active = True
            changed = True
        if email and user.email != email:
            user.email = email
            changed = True
        if password:
            user.set_password(password)
            changed = True
        if changed:
            user.save(using="default")
        return BootstrapResult(created=False, updated=changed, label=f"control_admin username={username}")

    def _ensure_world_governance_admin(
        self,
        world: WorldContext,
        *,
        username: str,
        password: str,
        email: str,
        member_no: str,
        display_name: str,
    ) -> BootstrapResult:
        if not username:
            raise CommandError("--world-admin-username cannot be empty.")
        if not member_no:
            raise CommandError("--world-admin-member-no cannot be empty.")

        database_alias = self._effective_world_alias(world)
        token = set_current_world(world)
        try:
            from core.credential_services import ensure_builtin_credential_templates
            ensure_builtin_credential_templates()
            ensure_finance_roles()
            with transaction.atomic(using=database_alias):
                user = self._ensure_world_user(username=username, password=password, email=email, database_alias=database_alias)
                member = self._ensure_world_member(
                    member_no=member_no,
                    user=user,
                    display_name=display_name,
                    database_alias=database_alias,
                )
                admin_role = ensure_governance_admin_role()["role"]
                admin_assignment_before = RoleAssignment.objects.filter(
                    member=member, role=admin_role, status=RoleAssignment.Status.ACTIVE
                ).first()
                result = bootstrap_first_governance_member(member)
                assignment = result["admin"]
                created_assignment = admin_assignment_before is None
                assignment_updated = self._ensure_assignment_window(assignment)
        finally:
            reset_current_world(token)

        return BootstrapResult(
            created=created_assignment,
            updated=assignment_updated if not created_assignment else False,
            label=(
                f"world_admin world_id={world.world_id}, username={username}, "
                f"member_no={member.member_no}, role_assignment_id={assignment.pk}"
            ),
        )

    def _ensure_world_user(self, *, username: str, password: str, email: str, database_alias: str):
        user_model = get_user_model()
        manager = user_model._default_manager.db_manager(database_alias)
        user = manager.filter(username=username).first()
        created = user is None
        if created:
            if not password:
                raise CommandError("A new world admin requires --world-admin-password or BIG_APPLE_WORLD_ADMIN_PASSWORD.")
            user = user_model(username=username, email=email, is_active=True, is_staff=False, is_superuser=False)
            user.set_password(password)
            user.save(using=database_alias)
            return user

        changed = False
        if not user.is_active or user.is_staff or user.is_superuser:
            user.is_active = True
            user.is_staff = False
            user.is_superuser = False
            changed = True
        if email and user.email != email:
            user.email = email
            changed = True
        if password:
            user.set_password(password)
            changed = True
        if changed:
            user.save(using=database_alias)
        return user

    def _ensure_world_member(self, *, member_no: str, user, display_name: str, database_alias: str) -> Member:
        member = Member.objects.using(database_alias).filter(member_no=member_no).first()
        if member is None:
            return Member.objects.using(database_alias).create(
                member_no=member_no,
                user=user,
                display_name=display_name or member_no,
                status=Member.Status.ACTIVE,
                batch_id="bootstrap",
                joined_simulation_day=1,
                credit_floor=-100,
                profile={},
                created_at=timezone.now(),
            )

        if member.user_id not in (None, user.pk):
            raise CommandError(f"Member {member_no} is already linked to another user.")

        changed_fields = []
        if member.user_id is None:
            member.user = user
            changed_fields.append("user")
        if display_name and member.display_name != display_name:
            member.display_name = display_name
            changed_fields.append("display_name")
        if member.status != Member.Status.ACTIVE:
            member.status = Member.Status.ACTIVE
            changed_fields.append("status")
        if changed_fields:
            member.save(using=database_alias, update_fields=changed_fields)
        return member

    def _ensure_assignment_window(self, assignment: RoleAssignment) -> bool:
        now = timezone.now()
        changed = False
        if assignment.start_at > now:
            assignment.start_at = now
            changed = True
        if assignment.end_at <= now:
            assignment.end_at = default_role_assignment_end_at(now)
            changed = True
        if changed:
            assignment.save(update_fields=["start_at", "end_at", "updated_at"])
        return changed

    def _format_result(self, result: BootstrapResult) -> str:
        if result.created:
            state = "created"
        elif result.updated:
            state = "updated"
        else:
            state = "already_exists"
        return f"{state}: {result.label}"
