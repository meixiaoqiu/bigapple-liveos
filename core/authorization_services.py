"""Authorization service boundary for Django and OpenFGA checks."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings

from .models import Member, Resource
from .openfga_client import OpenFGAClient, OpenFGARequestError
from .permission_services import legacy_member_has_permission, permission_requires_formal_member
from worlds.models import WorldRegistry
from worlds.state import get_current_world


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OpenFGACheck:
    user: str
    relation: str
    object_: str


@dataclass(frozen=True)
class OpenFGAContext:
    world_kind: str
    api_url: str
    store_name: str
    store_id: str
    authorization_model_id: str
    platform_object: str


def openfga_member_user(member: Member) -> str:
    return f"member:{member.pk}"


def openfga_role_object(role_id: int) -> str:
    return f"role:{role_id}"


def permission_object_type(permission_code: str) -> str:
    if permission_requires_formal_member(permission_code):
        return "guarded_permission"
    return "permission"


def openfga_permission_object(permission_code: str) -> str:
    return f"{permission_object_type(permission_code)}:{permission_code}"


def openfga_check_for_member_permission(member: Member, permission_code: str) -> OpenFGACheck:
    return OpenFGACheck(
        user=openfga_member_user(member),
        relation="holder",
        object_=openfga_permission_object(permission_code),
    )


def openfga_world_kind_for_runtime() -> str:
    world = get_current_world()
    if world is not None:
        return "real" if world.world_type == WorldRegistry.WorldType.REAL else "sim"
    site_role = str(getattr(settings, "SITE_ROLE", "") or "").strip().lower()
    if site_role == "real":
        return "real"
    if site_role == "simulation":
        return "sim"
    world_instance_type = str(getattr(settings, "WORLD_INSTANCE_TYPE", "") or "").strip().lower()
    if world_instance_type == "real":
        return "real"
    return "sim"


def openfga_context_for_world_kind(world_kind: str | None = None) -> OpenFGAContext:
    kind = (world_kind or openfga_world_kind_for_runtime()).strip().lower()
    if kind in {"realworld", "real"}:
        return OpenFGAContext(
            world_kind="real",
            api_url=getattr(settings, "OPENFGA_REAL_API_URL", "http://127.0.0.1:20103"),
            store_name=getattr(settings, "OPENFGA_REAL_STORE_NAME", "big-apple-realworld"),
            store_id=getattr(settings, "OPENFGA_REAL_STORE_ID", ""),
            authorization_model_id=getattr(settings, "OPENFGA_REAL_AUTHORIZATION_MODEL_ID", ""),
            platform_object=getattr(settings, "OPENFGA_REAL_PLATFORM_OBJECT", "platform:realworld"),
        )
    if kind in {"simulation", "simulation0001", "sim"}:
        return OpenFGAContext(
            world_kind="sim",
            api_url=getattr(settings, "OPENFGA_SIM_API_URL", "http://127.0.0.1:20106"),
            store_name=getattr(settings, "OPENFGA_SIM_STORE_NAME", "big-apple-simulation0001"),
            store_id=getattr(settings, "OPENFGA_SIM_STORE_ID", ""),
            authorization_model_id=getattr(settings, "OPENFGA_SIM_AUTHORIZATION_MODEL_ID", ""),
            platform_object=getattr(settings, "OPENFGA_SIM_PLATFORM_OBJECT", "platform:simulation0001"),
        )
    raise ValueError(f"Unsupported OpenFGA world kind: {world_kind}")


class AuthorizationService:
    """Single runtime permission boundary for all business authorization checks."""

    def __init__(self, client: OpenFGAClient | None = None):
        self.client = client

    def member_has_permission(
        self,
        member: Member,
        permission_code: str,
        resource: Resource | None = None,
        at_time=None,
    ) -> bool:
        backend = getattr(settings, "BIG_APPLE_AUTHORIZATION_BACKEND", "legacy")
        legacy_allowed = legacy_member_has_permission(
            member,
            permission_code,
            resource=resource,
            at_time=at_time,
        )
        if backend == "legacy":
            return legacy_allowed

        openfga_allowed = self._openfga_member_has_permission(member, permission_code, resource=resource)
        if backend == "dual_shadow":
            if openfga_allowed is not None and openfga_allowed != legacy_allowed:
                logger.warning(
                    "OpenFGA authorization differs from legacy authorization",
                    extra={
                        "member_id": member.pk,
                        "permission_code": permission_code,
                        "legacy_allowed": legacy_allowed,
                        "openfga_allowed": openfga_allowed,
                    },
                )
            return legacy_allowed

        if backend == "openfga":
            return bool(openfga_allowed)

        logger.error("Unknown authorization backend %s; denying permission", backend)
        return False

    def _openfga_member_has_permission(
        self,
        member: Member,
        permission_code: str,
        resource: Resource | None = None,
    ) -> bool | None:
        if resource is not None:
            logger.warning(
                "OpenFGA resource-scoped checks are not enabled yet; falling back to legacy shadow result",
                extra={"member_id": member.pk, "permission_code": permission_code, "resource_id": resource.pk},
            )
            return None
        context = openfga_context_for_world_kind()
        if not context.store_id:
            logger.warning("%s OpenFGA store id is not configured; OpenFGA check skipped", context.world_kind)
            return None
        check = openfga_check_for_member_permission(member, permission_code)
        client = self.client or OpenFGAClient(context.api_url)
        try:
            return client.check(
                store_id=context.store_id,
                authorization_model_id=context.authorization_model_id,
                user=check.user,
                relation=check.relation,
                object_=check.object_,
            )
        except OpenFGARequestError:
            logger.exception("OpenFGA check failed")
            return None
