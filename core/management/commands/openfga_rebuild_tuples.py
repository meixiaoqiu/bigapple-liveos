"""Rebuild OpenFGA tuples from Django authority data."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.authorization_services import (
    openfga_global_resource_permission_object,
    openfga_context_for_world_kind,
    openfga_member_user,
    openfga_permission_object,
    openfga_resource_permission_object,
    openfga_role_object,
)
from core.member_roles import ROLE_FORMAL_MEMBER, member_role_filter
from core.models import Member, Role, RoleAssignment, RolePermission
from core.openfga_client import OpenFGAClient, OpenFGARequestError
from core.permission_services import MEMBER_PERMISSION_STATUSES, permission_requires_formal_member
from worlds.command_context import command_world_context


class Command(BaseCommand):
    help = "Delete OpenFGA tuples and rebuild them from the current Django authority projection."

    def add_arguments(self, parser):
        parser.add_argument("--world-kind", choices=("real", "sim"), default=None)
        parser.add_argument("--world-id", default="")
        parser.add_argument("--store-id", default="")
        parser.add_argument("--api-url", default="")
        parser.add_argument("--authorization-model-id", default="")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        with command_world_context(options["world_id"], command_name="openfga_rebuild_tuples"):
            context = openfga_context_for_world_kind(options["world_kind"])
            store_id = options["store_id"] or context.store_id

            tuples = list(_unique_tuples(_project_authorization_tuples(platform_object=context.platform_object)))
            if options["dry_run"]:
                self.stdout.write(
                    f"Would delete all existing OpenFGA tuples and rebuild {len(tuples)} projected tuples."
                )
                return
            if not store_id:
                raise CommandError(f"{context.world_kind} OpenFGA store id is required.")

            client = OpenFGAClient(options["api_url"] or context.api_url)
            try:
                existing_tuple_keys = list(_unique_tuples(_read_tuple_keys(client, store_id=store_id)))
                authorization_model_id = options["authorization_model_id"] or context.authorization_model_id
                for start in range(0, len(existing_tuple_keys), 100):
                    client.delete_tuples(
                        store_id=store_id,
                        authorization_model_id=authorization_model_id,
                        deletes=existing_tuple_keys[start : start + 100],
                    )
                for start in range(0, len(tuples), 100):
                    client.write_tuples(
                        store_id=store_id,
                        authorization_model_id=authorization_model_id,
                        writes=tuples[start : start + 100],
                    )
            except OpenFGARequestError as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(
                self.style.SUCCESS(
                    "Projected "
                    f"{len(tuples)} OpenFGA tuples; "
                    f"deleted {len(existing_tuple_keys)} existing tuples; "
                    f"wrote {len(tuples)} rebuilt tuples."
                )
            )


def _project_authorization_tuples(*, platform_object: str):
    checked_at = timezone.now()

    formal_members = Member.objects.filter(
        status__in=MEMBER_PERMISSION_STATUSES,
    ).filter(member_role_filter(ROLE_FORMAL_MEMBER))
    for member in formal_members.distinct():
        yield {
            "user": openfga_member_user(member),
            "relation": "formal_member",
            "object": platform_object,
        }

    frozen_members = Member.objects.filter(status__in={Member.Status.SUSPENDED, Member.Status.EXITED})
    for member in frozen_members:
        yield {
            "user": openfga_member_user(member),
            "relation": "frozen_member",
            "object": platform_object,
        }

    active_assignments = RoleAssignment.objects.select_related("member", "role").filter(
        member__status__in=MEMBER_PERMISSION_STATUSES,
        status=RoleAssignment.Status.ACTIVE,
        role__status=Role.Status.ACTIVE,
        start_at__lte=checked_at,
        end_at__gte=checked_at,
    )
    for assignment in active_assignments:
        yield {
            "user": openfga_member_user(assignment.member),
            "relation": "assignee",
            "object": openfga_role_object(assignment.role_id),
        }

    active_role_ids = Role.objects.filter(status=Role.Status.ACTIVE).values("pk")
    role_permissions = RolePermission.objects.select_related("permission").filter(role_id__in=active_role_ids)
    for role_permission in role_permissions:
        for permission_object in _permission_objects_for_role_permission(role_permission):
            yield {
                "user": openfga_role_object(role_permission.role_id),
                "relation": "role",
                "object": permission_object,
            }
            if permission_requires_formal_member(role_permission.permission.code):
                yield {
                    "user": platform_object,
                    "relation": "platform",
                    "object": permission_object,
                }


def _permission_objects_for_role_permission(role_permission: RolePermission):
    permission_code = role_permission.permission.code
    yield openfga_permission_object(permission_code)

    if str(role_permission.scope or "").strip() in {"", "global", "all"}:
        yield openfga_global_resource_permission_object(permission_code)
        return

    for resource_id in _resource_ids_for_role_permission(role_permission):
        yield openfga_resource_permission_object(permission_code, resource_id)


def _resource_ids_for_role_permission(role_permission: RolePermission) -> list[str]:
    constraints = role_permission.constraints_json or {}
    resource_ids: list[str] = []
    constrained_id = constraints.get("resource_id")
    if constrained_id:
        resource_ids.append(str(constrained_id))
    constrained_ids = constraints.get("resource_ids") or []
    resource_ids.extend(str(item) for item in constrained_ids if item)
    return resource_ids


def _unique_tuples(tuples):
    seen: set[tuple[str, str, str]] = set()
    for tuple_key in tuples:
        key = _tuple_identity(tuple_key)
        if key in seen:
            continue
        seen.add(key)
        yield tuple_key


def _tuple_identity(tuple_key: dict[str, str]) -> tuple[str, str, str]:
    return (tuple_key["user"], tuple_key["relation"], tuple_key["object"])


def _read_tuple_keys(client: OpenFGAClient, *, store_id: str):
    for item in client.read_tuples(store_id=store_id):
        yield {
            "user": item["key"]["user"],
            "relation": item["key"]["relation"],
            "object": item["key"]["object"],
        }
