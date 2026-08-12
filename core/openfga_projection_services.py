"""Incremental OpenFGA projection for newly created authority facts."""

from __future__ import annotations

import logging

from django.core.exceptions import ValidationError
from django.utils import timezone

from .authorization_services import (
    authorization_backend,
    openfga_context_for_world_kind,
    openfga_member_user,
    openfga_proposal_object,
    openfga_role_object,
)
from .member_roles import (
    ROLE_COVENANTER,
    ROLE_DELIBERATOR,
    ROLE_ADMINISTRATOR,
    member_allows_role_facts,
    member_has_role,
)
from .models import Proposal, Role, RoleAssignment
from .role_catalog import catalog_role_definition_for_role
from .openfga_client import OpenFGAClient, OpenFGARequestError
from .proposals.voters import eligible_voters_for_rule_snapshot


logger = logging.getLogger(__name__)


def _write_tuples(tuples: list[dict[str, str]]) -> bool:
    if authorization_backend() != "openfga":
        return True
    context = openfga_context_for_world_kind()
    if not context.store_id or not context.authorization_model_id:
        logger.warning("OpenFGA incremental projection is unavailable")
        return False
    try:
        OpenFGAClient(context.api_url).write_tuples(
            store_id=context.store_id,
            authorization_model_id=context.authorization_model_id,
            writes=tuples,
        )
    except OpenFGARequestError as exc:
        logger.warning("OpenFGA incremental projection failed: %s", exc)
        return False
    return True


def _delete_tuples(tuples: list[dict[str, str]]) -> bool:
    if authorization_backend() != "openfga" or not tuples:
        return True
    context = openfga_context_for_world_kind()
    if not context.store_id or not context.authorization_model_id:
        logger.warning("OpenFGA incremental projection deletion is unavailable")
        return False
    try:
        OpenFGAClient(context.api_url).delete_tuples(
            store_id=context.store_id,
            authorization_model_id=context.authorization_model_id,
            deletes=tuples,
        )
    except OpenFGARequestError as exc:
        logger.warning("OpenFGA incremental projection deletion failed: %s", exc)
        return False
    return True


def project_voting_proposal(proposal: Proposal) -> bool:
    """Project one newly created voting proposal and its current eligible members."""
    if proposal.status != Proposal.Status.VOTING:
        return True
    context = openfga_context_for_world_kind()
    proposal_object = openfga_proposal_object(proposal)
    tuples = [{"user": context.platform_object, "relation": "platform", "object": proposal_object}]
    try:
        eligible = eligible_voters_for_rule_snapshot(rule_snapshot=proposal.electorate_rule_snapshot_json)
    except (ValidationError, ValueError, TypeError):
        return False
    tuples.extend(
        {"user": openfga_member_user(member), "relation": "eligible_member", "object": proposal_object}
        for member in eligible
    )
    return _write_tuples(tuples)


def _role_assignment_tuples(assignment: RoleAssignment) -> list[dict[str, str]]:
    context = openfga_context_for_world_kind()
    definition = catalog_role_definition_for_role(assignment.role)
    tuples: list[dict[str, str]] = []
    if definition is not None:
        relation = {
            ROLE_COVENANTER: "covenanter",
            ROLE_DELIBERATOR: "deliberator",
            ROLE_ADMINISTRATOR: "administrator",
        }.get(definition.display_name)
        if relation:
            tuples.append({
                "user": openfga_member_user(assignment.member),
                "relation": relation,
                "object": context.platform_object,
            })
        if definition.display_name == ROLE_ADMINISTRATOR:
            tuples.append({
                "user": openfga_member_user(assignment.member),
                "relation": "assignee",
                "object": openfga_role_object(assignment.role_id),
            })
    elif any(
        str(code).startswith(("finance.", "governance."))
        for code in assignment.role.role_permissions.values_list("permission__code", flat=True)
    ):
        tuples.append({
            "user": openfga_member_user(assignment.member),
            "relation": "assignee",
            "object": openfga_role_object(assignment.role_id),
        })
    return tuples


def _role_assignment_is_current(assignment: RoleAssignment, *, checked_at=None) -> bool:
    moment = checked_at or timezone.now()
    if (
        assignment.status != RoleAssignment.Status.ACTIVE
        or assignment.role.status != Role.Status.ACTIVE
        or assignment.start_at > moment
        or assignment.end_at <= moment
        or not member_allows_role_facts(assignment.member)
    ):
        return False
    definition = catalog_role_definition_for_role(assignment.role)
    requires_covenanter = bool(definition and definition.requires_covenanter)
    if definition is None:
        requires_covenanter = any(
            str(code).startswith(("finance.", "governance."))
            for code in assignment.role.role_permissions.values_list("permission__code", flat=True)
        )
    return not requires_covenanter or member_has_role(
        assignment.member,
        ROLE_COVENANTER,
        checked_at=moment,
    )


def project_role_assignment(assignment: RoleAssignment) -> bool:
    """Project one role assignment only while its Django authority fact is current."""
    assignment = RoleAssignment.objects.select_related("member__user", "role").get(pk=assignment.pk)
    if not _role_assignment_is_current(assignment):
        return remove_role_assignment_projection(assignment)
    return _write_tuples(_role_assignment_tuples(assignment))


def remove_role_assignment_projection(assignment: RoleAssignment) -> bool:
    """Delete the OpenFGA tuples derived from one ended or invalid role assignment."""
    assignment = RoleAssignment.objects.select_related("member", "role").get(pk=assignment.pk)
    return _delete_tuples(_role_assignment_tuples(assignment))


def remove_non_current_role_assignment_projections(member) -> bool:
    """Lazily remove stale lifecycle tuples when authority is checked after expiry."""
    assignments = list(
        RoleAssignment.objects.filter(member=member)
        .select_related("member__user", "role")
        .prefetch_related("role__role_permissions__permission")
    )
    current_keys: set[tuple[str, str, str]] = set()
    stale_keys: set[tuple[str, str, str]] = set()
    for assignment in assignments:
        destination = current_keys if _role_assignment_is_current(assignment) else stale_keys
        destination.update(
            (item["user"], item["relation"], item["object"])
            for item in _role_assignment_tuples(assignment)
        )
    deletes = [
        {"user": user, "relation": relation, "object": object_}
        for user, relation, object_ in sorted(stale_keys - current_keys)
    ]
    return _delete_tuples(deletes)
