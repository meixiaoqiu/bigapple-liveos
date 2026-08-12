"""Rebuild OpenFGA tuples from Django authority data."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from core.authorization_services import (
    OPENFGA_AUTHORIZATION_MODEL_VERSION,
    openfga_global_resource_permission_object,
    openfga_context_for_world_kind,
    openfga_member_user,
    openfga_permission_object,
    openfga_professional_domain_object,
    openfga_proposal_object,
    openfga_resource_permission_object,
    openfga_role_object,
)
from core.proposals.voters import eligible_voters_for_rule_snapshot
from core.member_roles import ROLE_DELIBERATOR, ROLE_COVENANTER, ROLE_ADMINISTRATOR, member_role_filter
from core.models import (
    Member,
    MemberProfessionalQualification,
    ProfessionalDomain,
    Proposal,
    Role,
    RoleAssignment,
    RolePermission,
)
from core.finance_setup import (
    FINANCE_ORGANIZATION_NAME,
    FINANCE_REVIEW_ROLE_NAME,
    FINANCE_PAY_ROLE_NAME,
    FINANCE_PUBLIC_ATTACHMENT_PUBLISH_ROLE_NAME,
)
from core.role_catalog import ROLE_CATALOG_ORGANIZATION_KEY
from core.openfga_client import OpenFGAClient, OpenFGARequestError
from core.permission_services import MEMBER_PERMISSION_STATUSES, permission_requires_covenanter
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
                    f"OpenFGA model={OPENFGA_AUTHORIZATION_MODEL_VERSION}; projected "
                    f"{len(tuples)} OpenFGA tuples; "
                    f"deleted {len(existing_tuple_keys)} existing tuples; "
                    f"wrote {len(tuples)} rebuilt tuples."
                )
            )


def _project_authorization_tuples(*, platform_object: str):
    checked_at = timezone.now()

    for role_name, relation in (
        (ROLE_COVENANTER, "covenanter"),
        (ROLE_DELIBERATOR, "deliberator"),
        (ROLE_ADMINISTRATOR, "administrator"),
    ):
        members = Member.objects.filter(member_role_filter(role_name, checked_at=checked_at)).distinct()
        for member in members:
            yield {
                "user": openfga_member_user(member),
                "relation": relation,
                "object": platform_object,
            }

    frozen_members = Member.objects.filter(
        Q(status__in={Member.Status.SUSPENDED, Member.Status.EXITED})
        | Q(user__isnull=False, user__is_active=False)
    ).distinct()
    for member in frozen_members:
        yield {
            "user": openfga_member_user(member),
            "relation": "frozen_member",
            "object": platform_object,
        }

    administrator_assignments = RoleAssignment.objects.select_related("member", "role").filter(
        member__in=Member.objects.filter(member_role_filter(ROLE_ADMINISTRATOR, checked_at=checked_at)),
        status=RoleAssignment.Status.ACTIVE,
        role__status=Role.Status.ACTIVE,
        role__organization__role_catalog_key=ROLE_CATALOG_ORGANIZATION_KEY,
        role__name=ROLE_ADMINISTRATOR,
        start_at__lte=checked_at,
        end_at__gt=checked_at,
    )
    for assignment in administrator_assignments:
        yield {
            "user": openfga_member_user(assignment.member),
            "relation": "assignee",
            "object": openfga_role_object(assignment.role_id),
        }

    finance_role_names = {
        FINANCE_REVIEW_ROLE_NAME,
        FINANCE_PAY_ROLE_NAME,
        FINANCE_PUBLIC_ATTACHMENT_PUBLISH_ROLE_NAME,
    }
    finance_assignments = RoleAssignment.objects.select_related("member", "role").filter(
        member__in=Member.objects.filter(member_role_filter(ROLE_COVENANTER, checked_at=checked_at)),
        status=RoleAssignment.Status.ACTIVE,
        role__status=Role.Status.ACTIVE,
        role__organization__name=FINANCE_ORGANIZATION_NAME,
        role__name__in=finance_role_names,
        start_at__lte=checked_at,
        end_at__gt=checked_at,
    )
    for assignment in finance_assignments:
        yield {
            "user": openfga_member_user(assignment.member),
            "relation": "assignee",
            "object": openfga_role_object(assignment.role_id),
        }

    role_permissions = RolePermission.objects.select_related("permission").filter(
        role__organization__role_catalog_key=ROLE_CATALOG_ORGANIZATION_KEY,
        role__name=ROLE_ADMINISTRATOR,
        role__status=Role.Status.ACTIVE,
    )
    for role_permission in role_permissions:
        for permission_object in _permission_objects_for_role_permission(role_permission):
            yield {
                "user": openfga_role_object(role_permission.role_id),
                "relation": "role",
                "object": permission_object,
            }
            if permission_requires_covenanter(role_permission.permission.code):
                yield {
                    "user": platform_object,
                    "relation": "platform",
                    "object": permission_object,
                }

    finance_role_permissions = RolePermission.objects.select_related("permission").filter(
        role__organization__name=FINANCE_ORGANIZATION_NAME,
        role__name__in=finance_role_names,
        role__status=Role.Status.ACTIVE,
        permission__code__startswith="finance.",
    )
    for role_permission in finance_role_permissions:
        for permission_object in _permission_objects_for_role_permission(role_permission):
            yield {
                "user": openfga_role_object(role_permission.role_id),
                "relation": "role",
                "object": permission_object,
            }
            if permission_requires_covenanter(role_permission.permission.code):
                yield {
                    "user": platform_object,
                    "relation": "platform",
                    "object": permission_object,
                }

    qualifications = MemberProfessionalQualification.objects.select_related("member", "domain").filter(
        member__status__in=MEMBER_PERMISSION_STATUSES,
        status=MemberProfessionalQualification.Status.ACTIVE,
        domain__status=ProfessionalDomain.Status.ACTIVE,
        valid_from__lte=checked_at,
    ).filter(Q(valid_until__isnull=True) | Q(valid_until__gt=checked_at)).filter(
        Q(member__user__isnull=True) | Q(member__user__is_active=True)
    )
    for qualification in qualifications:
        yield {
            "user": openfga_member_user(qualification.member),
            "relation": "qualified_member",
            "object": openfga_professional_domain_object(qualification.domain),
        }

    proposals = Proposal.objects.select_related("electorate_rule_version").filter(
        status=Proposal.Status.VOTING,
        deadline_at__gt=checked_at,
    )
    for proposal in proposals:
        try:
            proposal_object = openfga_proposal_object(proposal)
        except ValueError:
            continue
        yield {
            "user": platform_object,
            "relation": "platform",
            "object": proposal_object,
        }
        try:
            eligible_members = eligible_voters_for_rule_snapshot(
                rule_snapshot=proposal.electorate_rule_snapshot_json,
                at_time=checked_at,
            )
        except (ValidationError, ValueError, TypeError):
            continue
        for member in eligible_members:
            yield {
                "user": openfga_member_user(member),
                "relation": "eligible_member",
                "object": proposal_object,
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
