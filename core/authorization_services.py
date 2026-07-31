"""Authorization service boundary for Django and OpenFGA checks."""

from __future__ import annotations

import logging
from base64 import urlsafe_b64encode
from dataclasses import dataclass

from django.conf import settings

from .models import Member, ProfessionalDomain, Proposal, Resource
from .openfga_client import OpenFGAClient, OpenFGARequestError
from .permission_services import legacy_member_has_permission, permission_requires_formal_member
from worlds.models import WorldRegistry
from worlds.state import get_current_world


logger = logging.getLogger(__name__)


OPENFGA_AUTHORIZATION_MODEL_VERSION = "2026-07-30-role-baseline-v1"


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


@dataclass(frozen=True)
class WorkspaceAccessDecision:
    allowed: bool
    reason: str = ""


def openfga_member_user(member: Member) -> str:
    return f"member:{member.pk}"


def openfga_role_object(role_id: int) -> str:
    return f"role:{role_id}"


def openfga_professional_domain_object(domain: ProfessionalDomain | int) -> str:
    """返回专业资格关系使用的稳定 OpenFGA 对象。"""

    domain_id = domain.pk if isinstance(domain, ProfessionalDomain) else domain
    return f"professional_domain:{domain_id}"


def openfga_proposal_object(proposal: Proposal) -> str:
    """按选民政策映射为 OpenFGA 提案对象；未知政策必须拒绝。"""

    if proposal.electorate_policy == Proposal.ElectoratePolicy.GENERAL_DELIBERATION:
        return f"general_proposal:{proposal.pk}"
    if proposal.electorate_policy == Proposal.ElectoratePolicy.PROFESSIONAL_DELIBERATION:
        return f"professional_proposal:{proposal.pk}"
    raise ValueError(f"Unknown electorate policy: {proposal.electorate_policy}")


def permission_object_type(permission_code: str) -> str:
    if permission_requires_formal_member(permission_code):
        return "guarded_permission"
    return "permission"


def resource_permission_object_type(permission_code: str) -> str:
    if permission_requires_formal_member(permission_code):
        return "guarded_resource_permission"
    return "resource_permission"


def openfga_object_id_part(value: object) -> str:
    return urlsafe_b64encode(str(value).encode("utf-8")).decode("ascii").rstrip("=")


def openfga_permission_object(permission_code: str) -> str:
    return f"{permission_object_type(permission_code)}:{permission_code}"


def openfga_global_resource_permission_object(permission_code: str) -> str:
    permission_id = openfga_object_id_part(permission_code)
    return f"{resource_permission_object_type(permission_code)}:{permission_id}.global"


def openfga_resource_permission_object(permission_code: str, resource_id: object) -> str:
    permission_id = openfga_object_id_part(permission_code)
    resource_part = openfga_object_id_part(resource_id)
    return f"{resource_permission_object_type(permission_code)}:{permission_id}.{resource_part}"


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
        backend = authorization_backend()
        if backend == "legacy":
            return legacy_member_has_permission(
                member,
                permission_code,
                resource=resource,
                at_time=at_time,
            )

        openfga_allowed = self._openfga_member_has_permission(member, permission_code, resource=resource)
        if backend == "openfga":
            return bool(openfga_allowed)

        logger.error("Unknown authorization backend %s; denying permission", backend)
        return False

    def member_has_full_workspace_access(self, member: Member) -> bool:
        return self.full_workspace_access_decision(member).allowed

    def member_can_maintain(
        self,
        *,
        member: Member,
        permission_code: str,
        resource: Resource | None = None,
        at_time=None,
    ) -> bool:
        """检查一项明确维护能力；不允许以角色名称或后台标志旁路。"""

        if not str(permission_code).startswith("governance."):
            return False
        return self.member_has_permission(
            member,
            permission_code,
            resource=resource,
            at_time=at_time,
        )

    def full_workspace_access_decision(self, member: Member) -> WorkspaceAccessDecision:
        backend = authorization_backend()
        if backend == "legacy":
            from .member_roles import ROLE_FORMAL_MEMBER, member_has_role

            allowed = member.status in {Member.Status.ACTIVE, Member.Status.ADMITTED} and member_has_role(
                member,
                ROLE_FORMAL_MEMBER,
            )
            return WorkspaceAccessDecision(allowed=allowed, reason="" if allowed else "not_authorized")
        if backend != "openfga":
            logger.error("Unknown authorization backend %s; denying workspace access", backend)
            return WorkspaceAccessDecision(allowed=False, reason="authorization_unavailable")
        context = openfga_context_for_world_kind()
        if not context.store_id:
            logger.warning("%s OpenFGA store id is not configured; workspace access denied", context.world_kind)
            return WorkspaceAccessDecision(allowed=False, reason="authorization_unavailable")
        client = self.client or OpenFGAClient(context.api_url)
        try:
            allowed = client.check(
                store_id=context.store_id,
                authorization_model_id=context.authorization_model_id,
                user=openfga_member_user(member),
                relation="formal_member",
                object_=context.platform_object,
            )
            return WorkspaceAccessDecision(allowed=allowed, reason="" if allowed else "not_authorized")
        except OpenFGARequestError as exc:
            logger.warning("OpenFGA workspace access check failed: %s", exc)
            return WorkspaceAccessDecision(allowed=False, reason="authorization_unavailable")

    def member_can_vote_on_proposal(self, *, member: Member, proposal, at_time=None) -> bool:
        """检查成员当前是否可对指定提案投票，不能只依赖创建时快照。"""

        backend = authorization_backend()
        if backend == "legacy":
            from .proposals.voters import member_is_currently_eligible_to_vote

            return member_is_currently_eligible_to_vote(
                member=member,
                electorate_policy=proposal.electorate_policy,
                professional_domain=proposal.professional_domain,
                at_time=at_time,
            )
        if backend == "openfga":
            context = openfga_context_for_world_kind()
            if not context.store_id or not context.authorization_model_id:
                logger.warning("%s OpenFGA proposal-voting model is unavailable; voting denied", context.world_kind)
                return False
            try:
                object_ = openfga_proposal_object(proposal)
            except ValueError:
                logger.warning("Unknown proposal electorate policy; voting denied")
                return False
            client = self.client or OpenFGAClient(context.api_url)
            try:
                return client.check(
                    store_id=context.store_id,
                    authorization_model_id=context.authorization_model_id,
                    user=openfga_member_user(member),
                    relation="can_vote",
                    object_=object_,
                )
            except OpenFGARequestError as exc:
                logger.warning("OpenFGA proposal-voting check failed: %s", exc)
                return False
        logger.error("Unknown authorization backend %s; proposal voting denied", backend)
        return False

    def _openfga_member_has_permission(
        self,
        member: Member,
        permission_code: str,
        resource: Resource | None = None,
    ) -> bool | None:
        context = openfga_context_for_world_kind()
        if not context.store_id:
            logger.warning("%s OpenFGA store id is not configured; OpenFGA check skipped", context.world_kind)
            return None
        checks = [openfga_check_for_member_permission(member, permission_code)]
        if resource is not None:
            checks = [
                OpenFGACheck(
                    user=openfga_member_user(member),
                    relation="holder",
                    object_=openfga_global_resource_permission_object(permission_code),
                ),
                OpenFGACheck(
                    user=openfga_member_user(member),
                    relation="holder",
                    object_=openfga_resource_permission_object(permission_code, resource.pk),
                ),
            ]
        client = self.client or OpenFGAClient(context.api_url)
        unavailable = False
        for check in checks:
            allowed = self._check_openfga_permission(client, context=context, check=check)
            if allowed is True:
                return True
            if allowed is None:
                unavailable = True
        if unavailable:
            return None
        return False

    def _check_openfga_permission(
        self,
        client: OpenFGAClient,
        *,
        context: OpenFGAContext,
        check: OpenFGACheck,
    ) -> bool | None:
        try:
            return client.check(
                store_id=context.store_id,
                authorization_model_id=context.authorization_model_id,
                user=check.user,
                relation=check.relation,
                object_=check.object_,
            )
        except OpenFGARequestError as exc:
            logger.warning("OpenFGA check failed: %s", exc)
            return None

def authorization_backend() -> str:
    return getattr(settings, "BIG_APPLE_AUTHORIZATION_BACKEND", "openfga")
