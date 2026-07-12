"""Apply accepted simulation plan changes to a new plan revision."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import re
from collections.abc import Iterable
from typing import Any

from django.db import router, transaction
from django.utils import timezone

from core.exceptions import DomainError
from core.models import (
    PlanCapacityImpact,
    PlanChangeOperation,
    PlanChangeSet,
    PlanDependency,
    PlanNode,
    PlanRequirement,
    PlanRevision,
)


SEMVER_RE = re.compile(r"^v(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")
SUPPORTED_OPERATION_TYPES = {
    PlanChangeOperation.OperationType.ADD_NODE,
    PlanChangeOperation.OperationType.ADD_PREPARATION,
    PlanChangeOperation.OperationType.ADD_DEPENDENCY,
    PlanChangeOperation.OperationType.ADD_REQUIREMENT,
    PlanChangeOperation.OperationType.ADD_CAPACITY_IMPACT,
    PlanChangeOperation.OperationType.UPDATE_NODE_FIELD,
    PlanChangeOperation.OperationType.REDUCE_ADMISSION,
    PlanChangeOperation.OperationType.NOTE,
}
UPDATABLE_NODE_FIELDS = {
    "parent",
    "parent_id",
    "sequence",
    "code",
    "title",
    "node_type",
    "status",
    "is_required",
    "is_expandable",
    "allow_simulation_adjustment",
    "description",
    "planned_start_day",
    "planned_duration_days",
    "planned_end_day",
    "estimated_cost_low",
    "estimated_cost_expected",
    "estimated_cost_high",
    "required_people_min",
    "required_people_max",
    "required_person_days",
    "required_skills",
    "required_resources",
    "completion_criteria",
    "risk_notes",
    "metadata",
}
DECIMAL_NODE_FIELDS = {
    "estimated_cost_low",
    "estimated_cost_expected",
    "estimated_cost_high",
    "required_person_days",
}
INT_NODE_FIELDS = {
    "sequence",
    "planned_start_day",
    "planned_duration_days",
    "planned_end_day",
    "required_people_min",
    "required_people_max",
}
BOOL_NODE_FIELDS = {"is_required", "is_expandable", "allow_simulation_adjustment"}
JSON_NODE_FIELDS = {"required_skills", "required_resources", "completion_criteria", "metadata"}


def validate_plan_change_set_operations(
    change_set: PlanChangeSet,
    *,
    using: str | None = None,
    operations: Iterable[PlanChangeOperation] | None = None,
) -> list[str]:
    """Return structural validation errors for a plan change set.

    This is intentionally a preflight check. It validates the stable payload
    contract before the application code starts copying a PlanRevision, so a
    malformed historical change set cannot be mistaken for an applicable
    baseline update.
    """

    db_alias = using or change_set._state.db or router.db_for_read(PlanChangeOperation)
    if operations is None:
        operations = (
            PlanChangeOperation.objects.using(db_alias)
            .filter(change_set=change_set)
            .order_by("sequence", "operation_id")
        )
    errors: list[str] = []
    for operation in operations:
        if operation.operation_type not in SUPPORTED_OPERATION_TYPES:
            if operation.is_required:
                errors.append(f"计划变更操作 {operation.operation_id} 使用了不支持的类型：{operation.operation_type}")
            continue
        if operation.operation_type == PlanChangeOperation.OperationType.NOTE:
            continue
        payload = operation.new_value or {}
        if not isinstance(payload, dict):
            errors.append(f"计划变更操作 {operation.operation_id} 的 new_value 必须是对象。")
            continue
        errors.extend(validate_operation_payload(operation, payload))
    return errors


def validate_operation_payload(operation: PlanChangeOperation, payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    operation_type = operation.operation_type
    if operation_type in {
        PlanChangeOperation.OperationType.ADD_NODE,
        PlanChangeOperation.OperationType.ADD_PREPARATION,
    }:
        require_payload_keys(operation, payload, errors, "code", "title")
    elif operation_type == PlanChangeOperation.OperationType.ADD_DEPENDENCY:
        require_any_payload_key(operation, payload, errors, "node_id", "target_node_id", "node_code", "target_node_code", "code")
        require_any_payload_key(operation, payload, errors, "depends_on_id", "depends_on_code")
    elif operation_type == PlanChangeOperation.OperationType.ADD_REQUIREMENT:
        require_any_payload_key(operation, payload, errors, "node_id", "target_node_id", "node_code", "target_node_code")
        require_payload_keys(operation, payload, errors, "name")
    elif operation_type == PlanChangeOperation.OperationType.ADD_CAPACITY_IMPACT:
        require_any_payload_key(operation, payload, errors, "node_id", "target_node_id", "node_code", "target_node_code")
    elif operation_type == PlanChangeOperation.OperationType.UPDATE_NODE_FIELD:
        if not operation.target_field:
            errors.append(f"计划变更操作 {operation.operation_id} 缺少目标字段：target_field")
        if not operation.target_id:
            require_any_payload_key(operation, payload, errors, "node_id", "target_node_id", "node_code", "target_node_code", "code")
    return errors


def require_payload_keys(
    operation: PlanChangeOperation,
    payload: dict[str, Any],
    errors: list[str],
    *keys: str,
) -> None:
    for key in keys:
        if str(payload.get(key) or "").strip() == "":
            errors.append(f"计划变更操作 {operation.operation_id} 缺少必填字段：{key}")


def require_any_payload_key(
    operation: PlanChangeOperation,
    payload: dict[str, Any],
    errors: list[str],
    *keys: str,
) -> None:
    if all(str(payload.get(key) or "").strip() == "" for key in keys):
        errors.append(f"计划变更操作 {operation.operation_id} 缺少节点引用字段：{'/'.join(keys)}")


class PlanApplicationContext:
    """Mutable mapping state while one change set is applied."""

    def __init__(self, *, using: str, revision: PlanRevision, revision_slug: str, applied_at) -> None:
        self.using = using
        self.revision = revision
        self.revision_slug = revision_slug
        self.applied_at = applied_at
        self.nodes_by_source_id: dict[str, PlanNode] = {}
        self.nodes_by_new_id: dict[str, PlanNode] = {}
        self.nodes_by_code: dict[str, PlanNode] = {}
        self.operation_results: list[dict[str, object]] = []
        self.notes: list[dict[str, str]] = []

    def remember_node(self, node: PlanNode, *, source_node_id: str = "") -> None:
        if source_node_id:
            self.nodes_by_source_id[source_node_id] = node
        self.nodes_by_new_id[node.node_id] = node
        self.nodes_by_code[node.code] = node


def apply_plan_change_set(change_set: PlanChangeSet, *, actor=None, publish: bool = False) -> PlanRevision:
    """Copy the source PlanRevision and apply one reviewed PlanChangeSet.

    The source revision is never modified. Re-applying an already applied
    change set returns the existing generated revision instead of creating a
    second version. When ``publish`` is true, the generated revision becomes
    the published baseline for the same plan and prior published revisions are
    retired.
    """

    using = change_set._state.db or router.db_for_write(PlanChangeSet)
    with transaction.atomic(using=using):
        locked = (
            PlanChangeSet.objects.using(using)
            .select_for_update()
            .select_related("plan_revision", "plan_revision__plan", "run", "proposal", "applied_revision")
            .get(change_set_id=change_set.change_set_id)
        )
        if locked.status == PlanChangeSet.Status.APPLIED:
            if locked.applied_revision_id:
                existing_revision = PlanRevision.objects.using(using).select_related("plan").get(
                    revision_id=locked.applied_revision_id
                )
                if publish:
                    publish_plan_revision(existing_revision, published_at=timezone.now(), using=using)
                return existing_revision
            raise DomainError(f"计划变更集 {locked.change_set_id} 已标记为 applied，但缺少 applied_revision。")
        if locked.status == PlanChangeSet.Status.REJECTED:
            raise DomainError(f"计划变更集 {locked.change_set_id} 已拒绝，不能应用。")

        validation_errors = validate_plan_change_set_operations(locked, using=using)
        if validation_errors:
            raise DomainError("；".join(validation_errors))

        applied_at = timezone.now()
        actor_payload = actor_ref(actor)
        source_revision = locked.plan_revision
        revision_code = next_revision_code(source_revision, using=using)
        revision_id = unique_model_id(
            PlanRevision,
            "revision_id",
            f"{source_revision.plan_id}-rev-{slugify(revision_code, separator='_')}",
            using=using,
        )
        new_revision = PlanRevision.objects.using(using).create(
            revision_id=revision_id,
            plan=source_revision.plan,
            revision_code=revision_code,
            status=PlanRevision.Status.DRAFT,
            title=f"{source_revision.title} / {revision_code}",
            change_summary=(
                f"应用计划变更集 {locked.change_set_id} 生成；"
                f"来源仿真运行 {locked.run_id}；源版本 {source_revision.revision_code}。"
            ),
            created_at=applied_at,
            created_by=actor_payload or deepcopy(source_revision.created_by or {}),
            published_at=None,
            metadata={
                **deepcopy(source_revision.metadata or {}),
                "source_revision_id": source_revision.revision_id,
                "source_revision_code": source_revision.revision_code,
                "applied_change_set_id": locked.change_set_id,
                "source_simulation_run_id": locked.run_id,
            },
        )
        context = PlanApplicationContext(
            using=using,
            revision=new_revision,
            revision_slug=slugify(revision_code),
            applied_at=applied_at,
        )
        copy_revision_contents(source_revision=source_revision, context=context)
        apply_operations(change_set=locked, context=context)

        revision_metadata = deepcopy(new_revision.metadata or {})
        revision_metadata["plan_change_application"] = {
            "change_set_id": locked.change_set_id,
            "source_revision_id": source_revision.revision_id,
            "source_simulation_run_id": locked.run_id,
            "actor": actor_payload,
            "applied_at": applied_at.isoformat(),
            "operations": context.operation_results,
            "notes": context.notes,
        }
        new_revision.metadata = revision_metadata
        new_revision.save(update_fields=["metadata"])
        if publish:
            publish_plan_revision(new_revision, published_at=applied_at, using=using)

        change_set_metadata = deepcopy(locked.metadata or {})
        change_set_metadata["application_result"] = {
            "applied_revision_id": new_revision.revision_id,
            "applied_revision_code": new_revision.revision_code,
            "source_revision_id": source_revision.revision_id,
            "source_simulation_run_id": locked.run_id,
            "actor": actor_payload,
            "applied_at": applied_at.isoformat(),
            "operations": context.operation_results,
            "notes": context.notes,
        }
        locked.status = PlanChangeSet.Status.APPLIED
        locked.applied_at = applied_at
        locked.applied_revision = new_revision
        locked.metadata = change_set_metadata
        locked.save(update_fields=["status", "applied_at", "applied_revision", "metadata"])
        return new_revision


def publish_plan_revision(revision: PlanRevision, *, published_at, using: str) -> None:
    """Publish one plan revision as the current baseline for its plan."""

    PlanRevision.objects.using(using).select_for_update().filter(
        plan_id=revision.plan_id,
        status=PlanRevision.Status.PUBLISHED,
    ).exclude(revision_id=revision.revision_id).update(status=PlanRevision.Status.RETIRED)
    if revision.status != PlanRevision.Status.PUBLISHED or revision.published_at is None:
        revision.status = PlanRevision.Status.PUBLISHED
        revision.published_at = published_at
        revision.save(update_fields=["status", "published_at"])


def actor_ref(actor) -> dict[str, object]:
    if actor is None:
        return {}
    if isinstance(actor, dict):
        return deepcopy(actor)
    if isinstance(actor, str):
        return {"actor_id": actor}
    get_username = getattr(actor, "get_username", None)
    if callable(get_username):
        username = str(get_username() or "").strip()
        return {"actor_id": username or f"user:{actor.pk}", "user_id": actor.pk}
    return {"actor_id": str(actor)}


def next_revision_code(source_revision: PlanRevision, *, using: str) -> str:
    source_code = source_revision.revision_code.strip() or "revision"
    semver = SEMVER_RE.match(source_code)
    if semver:
        major = int(semver.group("major"))
        minor = int(semver.group("minor"))
        patch = int(semver.group("patch"))
        for candidate_patch in range(patch + 1, patch + 1000):
            candidate = f"v{major}.{minor}.{candidate_patch}"
            if not PlanRevision.objects.using(using).filter(plan=source_revision.plan, revision_code=candidate).exists():
                return candidate
    for index in range(1, 1000):
        candidate = f"{source_code}-sim-{index:03d}"
        if not PlanRevision.objects.using(using).filter(plan=source_revision.plan, revision_code=candidate).exists():
            return candidate
    raise DomainError(f"无法为计划 {source_revision.plan_id} 生成新的版本号。")


def slugify(value: str, *, separator: str = "-") -> str:
    slug = re.sub(r"[^0-9A-Za-z]+", separator, value).strip(separator).lower()
    return slug or "item"


def unique_model_id(model, field_name: str, base: str, *, using: str) -> str:
    max_length = model._meta.get_field(field_name).max_length
    cleaned = base.strip("-_") or model._meta.model_name
    for index in range(1, 1000):
        suffix = "" if index == 1 else f"-{index:03d}"
        candidate = f"{cleaned[: max_length - len(suffix)]}{suffix}"
        if not model.objects.using(using).filter(**{field_name: candidate}).exists():
            return candidate
    raise DomainError(f"无法为 {model.__name__}.{field_name} 生成唯一 ID。")


def copy_revision_contents(*, source_revision: PlanRevision, context: PlanApplicationContext) -> None:
    using = context.using
    source_nodes = list(
        PlanNode.objects.using(using).filter(revision=source_revision).order_by("sequence", "node_id")
    )
    for source_node in source_nodes:
        node = PlanNode.objects.using(using).create(
            node_id=unique_model_id(
                PlanNode,
                "node_id",
                f"{source_node.node_id}-{context.revision_slug}",
                using=using,
            ),
            revision=context.revision,
            parent=None,
            sequence=source_node.sequence,
            code=source_node.code,
            title=source_node.title,
            node_type=source_node.node_type,
            status=source_node.status,
            is_required=source_node.is_required,
            is_expandable=source_node.is_expandable,
            allow_simulation_adjustment=source_node.allow_simulation_adjustment,
            description=source_node.description,
            planned_start_day=source_node.planned_start_day,
            planned_duration_days=source_node.planned_duration_days,
            planned_end_day=source_node.planned_end_day,
            estimated_cost_low=source_node.estimated_cost_low,
            estimated_cost_expected=source_node.estimated_cost_expected,
            estimated_cost_high=source_node.estimated_cost_high,
            required_people_min=source_node.required_people_min,
            required_people_max=source_node.required_people_max,
            required_person_days=source_node.required_person_days,
            required_skills=deepcopy(source_node.required_skills or []),
            required_resources=deepcopy(source_node.required_resources or []),
            completion_criteria=deepcopy(source_node.completion_criteria or []),
            risk_notes=source_node.risk_notes,
            created_at=context.applied_at,
            updated_at=context.applied_at,
            metadata={
                **deepcopy(source_node.metadata or {}),
                "copied_from_node_id": source_node.node_id,
                "source_revision_id": source_revision.revision_id,
            },
        )
        context.remember_node(node, source_node_id=source_node.node_id)

    for source_node in source_nodes:
        if not source_node.parent_id:
            continue
        node = context.nodes_by_source_id[source_node.node_id]
        parent = context.nodes_by_source_id.get(source_node.parent_id)
        if parent is None:
            raise DomainError(f"源计划节点 {source_node.node_id} 的父节点 {source_node.parent_id} 不在同一版本中。")
        node.parent = parent
        node.save(update_fields=["parent"])

    copy_requirements(source_nodes=source_nodes, context=context)
    copy_capacity_impacts(source_nodes=source_nodes, context=context)
    copy_dependencies(source_revision=source_revision, context=context)


def copy_requirements(*, source_nodes: list[PlanNode], context: PlanApplicationContext) -> None:
    source_node_ids = [node.node_id for node in source_nodes]
    for requirement in PlanRequirement.objects.using(context.using).filter(node_id__in=source_node_ids).order_by("requirement_id"):
        node = context.nodes_by_source_id[requirement.node_id]
        PlanRequirement.objects.using(context.using).create(
            requirement_id=unique_model_id(
                PlanRequirement,
                "requirement_id",
                f"{requirement.requirement_id}-{context.revision_slug}",
                using=context.using,
            ),
            node=node,
            requirement_type=requirement.requirement_type,
            name=requirement.name,
            quantity=requirement.quantity,
            unit=requirement.unit,
            unit_cost=requirement.unit_cost,
            total_cost_estimate=requirement.total_cost_estimate,
            is_must=requirement.is_must,
            notes=requirement.notes,
            metadata={
                **deepcopy(requirement.metadata or {}),
                "copied_from_requirement_id": requirement.requirement_id,
            },
        )


def copy_capacity_impacts(*, source_nodes: list[PlanNode], context: PlanApplicationContext) -> None:
    source_node_ids = [node.node_id for node in source_nodes]
    for impact in PlanCapacityImpact.objects.using(context.using).filter(node_id__in=source_node_ids).order_by("impact_id"):
        node = context.nodes_by_source_id[impact.node_id]
        PlanCapacityImpact.objects.using(context.using).create(
            impact_id=unique_model_id(
                PlanCapacityImpact,
                "impact_id",
                f"{impact.impact_id}-{context.revision_slug}",
                using=context.using,
            ),
            node=node,
            impact_type=impact.impact_type,
            delta=impact.delta,
            unit=impact.unit,
            description=impact.description,
            metadata={
                **deepcopy(impact.metadata or {}),
                "copied_from_impact_id": impact.impact_id,
            },
        )


def copy_dependencies(*, source_revision: PlanRevision, context: PlanApplicationContext) -> None:
    dependencies = (
        PlanDependency.objects.using(context.using)
        .filter(revision=source_revision)
        .select_related("node", "depends_on")
        .order_by("dependency_id")
    )
    for dependency in dependencies:
        PlanDependency.objects.using(context.using).create(
            dependency_id=unique_model_id(
                PlanDependency,
                "dependency_id",
                f"{dependency.dependency_id}-{context.revision_slug}",
                using=context.using,
            ),
            revision=context.revision,
            node=context.nodes_by_source_id[dependency.node_id],
            depends_on=context.nodes_by_source_id[dependency.depends_on_id],
            dependency_type=dependency.dependency_type,
            description=dependency.description,
            metadata={
                **deepcopy(dependency.metadata or {}),
                "copied_from_dependency_id": dependency.dependency_id,
            },
        )


def apply_operations(*, change_set: PlanChangeSet, context: PlanApplicationContext) -> None:
    operations = PlanChangeOperation.objects.using(context.using).filter(change_set=change_set).order_by("sequence", "operation_id")
    for operation in operations:
        if operation.operation_type not in SUPPORTED_OPERATION_TYPES:
            if operation.is_required:
                raise DomainError(f"不支持的计划变更操作：{operation.operation_type}")
            record_note(operation, context, note=f"跳过不支持的非必要操作：{operation.operation_type}")
            continue
        if operation.operation_type == PlanChangeOperation.OperationType.NOTE:
            record_note(operation, context)
        elif operation.operation_type in {
            PlanChangeOperation.OperationType.ADD_NODE,
            PlanChangeOperation.OperationType.ADD_PREPARATION,
        }:
            apply_add_node(operation, context)
        elif operation.operation_type == PlanChangeOperation.OperationType.ADD_DEPENDENCY:
            apply_add_dependency(operation, context)
        elif operation.operation_type == PlanChangeOperation.OperationType.ADD_REQUIREMENT:
            apply_add_requirement(operation, context)
        elif operation.operation_type == PlanChangeOperation.OperationType.ADD_CAPACITY_IMPACT:
            apply_add_capacity_impact(operation, context)
        elif operation.operation_type == PlanChangeOperation.OperationType.UPDATE_NODE_FIELD:
            apply_update_node_field(operation, context)
        elif operation.operation_type == PlanChangeOperation.OperationType.REDUCE_ADMISSION:
            apply_revision_metadata_note(operation, context, key="capacity_policy")


def record_operation_result(operation: PlanChangeOperation, context: PlanApplicationContext, **result) -> None:
    context.operation_results.append(
        {
            "operation_id": operation.operation_id,
            "sequence": operation.sequence,
            "operation_type": operation.operation_type,
            **result,
        }
    )


def record_note(operation: PlanChangeOperation, context: PlanApplicationContext, *, note: str | None = None) -> None:
    new_value = operation.new_value if isinstance(operation.new_value, dict) else {}
    note_text = note or str(new_value.get("note") or operation.rationale or "")
    context.notes.append({"operation_id": operation.operation_id, "note": note_text})
    record_operation_result(operation, context, action="note", note=note_text)


def apply_revision_metadata_note(operation: PlanChangeOperation, context: PlanApplicationContext, *, key: str) -> None:
    metadata = deepcopy(context.revision.metadata or {})
    metadata.setdefault(key, []).append(
        {
            "operation_id": operation.operation_id,
            "target_field": operation.target_field,
            "new_value": deepcopy(operation.new_value or {}),
            "rationale": operation.rationale,
        }
    )
    context.revision.metadata = metadata
    context.revision.save(update_fields=["metadata"])
    record_operation_result(operation, context, action="update_revision_metadata", key=key)


def apply_add_node(operation: PlanChangeOperation, context: PlanApplicationContext) -> None:
    payload = operation_payload(operation)
    code = required_str(payload, "code", operation=operation)
    if code in context.nodes_by_code:
        raise DomainError(f"计划版本 {context.revision.revision_id} 中已存在节点编号：{code}")
    expected_cost = decimal_value(payload.get("estimated_cost_expected", payload.get("cost")), default=Decimal("0.00"))
    metadata = deepcopy(payload.get("metadata") or {})
    metadata.update({"source_change_operation_id": operation.operation_id})
    node = PlanNode.objects.using(context.using).create(
        node_id=unique_model_id(
            PlanNode,
            "node_id",
            f"node-{slugify(context.revision.plan_id)}-{slugify(code)}-{context.revision_slug}",
            using=context.using,
        ),
        revision=context.revision,
        parent=resolve_optional_parent(payload, context),
        sequence=int_value(payload.get("sequence"), default=next_node_sequence(context)),
        code=code,
        title=required_str(payload, "title", operation=operation),
        node_type=str(payload.get("node_type") or PlanNode.NodeType.WORK_PACKAGE),
        status=str(payload.get("status") or PlanNode.Status.PLANNED),
        is_required=bool_value(payload.get("is_required"), default=True),
        is_expandable=bool_value(payload.get("is_expandable"), default=False),
        allow_simulation_adjustment=bool_value(payload.get("allow_simulation_adjustment"), default=True),
        description=str(payload.get("description") or ""),
        planned_start_day=optional_int_value(payload.get("planned_start_day")),
        planned_duration_days=int_value(payload.get("planned_duration_days", payload.get("duration")), default=1),
        planned_end_day=optional_int_value(payload.get("planned_end_day")),
        estimated_cost_low=decimal_value(payload.get("estimated_cost_low"), default=expected_cost),
        estimated_cost_expected=expected_cost,
        estimated_cost_high=decimal_value(payload.get("estimated_cost_high"), default=expected_cost),
        required_people_min=int_value(payload.get("required_people_min"), default=0),
        required_people_max=int_value(payload.get("required_people_max"), default=0),
        required_person_days=decimal_value(payload.get("required_person_days"), default=Decimal("0.00")),
        required_skills=list_value(payload.get("required_skills")),
        required_resources=list_value(payload.get("required_resources")),
        completion_criteria=list_value(payload.get("completion_criteria")),
        risk_notes=str(payload.get("risk_notes") or ""),
        created_at=context.applied_at,
        updated_at=context.applied_at,
        metadata=metadata,
    )
    context.remember_node(node)
    for index, requirement_payload in enumerate(list_value(payload.get("requirements")), start=1):
        apply_add_requirement(operation, context, payload=requirement_payload, target_node=node, ordinal=index)
    record_operation_result(operation, context, action="add_node", node_id=node.node_id, code=node.code)


def apply_add_dependency(operation: PlanChangeOperation, context: PlanApplicationContext) -> None:
    payload = operation_payload(operation)
    node = resolve_node(payload, context, id_keys=("node_id", "target_node_id"), code_keys=("node_code", "target_node_code", "code"))
    depends_on = resolve_node(payload, context, id_keys=("depends_on_id",), code_keys=("depends_on_code",))
    dependency = PlanDependency.objects.using(context.using).create(
        dependency_id=unique_model_id(
            PlanDependency,
            "dependency_id",
            f"dep-{slugify(depends_on.code)}-{slugify(node.code)}-{context.revision_slug}",
            using=context.using,
        ),
        revision=context.revision,
        node=node,
        depends_on=depends_on,
        dependency_type=str(payload.get("dependency_type") or PlanDependency.DependencyType.FINISH_TO_START),
        description=str(payload.get("description") or ""),
        metadata={
            **deepcopy(payload.get("metadata") or {}),
            "source_change_operation_id": operation.operation_id,
        },
    )
    record_operation_result(
        operation,
        context,
        action="add_dependency",
        dependency_id=dependency.dependency_id,
        node_id=node.node_id,
        depends_on_id=depends_on.node_id,
    )


def apply_add_requirement(
    operation: PlanChangeOperation,
    context: PlanApplicationContext,
    *,
    payload: dict[str, Any] | None = None,
    target_node: PlanNode | None = None,
    ordinal: int | None = None,
) -> None:
    payload = deepcopy(payload) if payload is not None else operation_payload(operation)
    node = target_node or resolve_node(payload, context, id_keys=("node_id", "target_node_id"), code_keys=("node_code", "target_node_code"))
    requirement_type = str(payload.get("requirement_type") or PlanRequirement.RequirementType.MATERIAL)
    name = required_str(payload, "name", operation=operation)
    requirement = PlanRequirement.objects.using(context.using).create(
        requirement_id=unique_model_id(
            PlanRequirement,
            "requirement_id",
            f"req-{slugify(node.code)}-{slugify(requirement_type)}-{slugify(name)}-{context.revision_slug}",
            using=context.using,
        ),
        node=node,
        requirement_type=requirement_type,
        name=name,
        quantity=decimal_value(payload.get("quantity"), default=Decimal("0")),
        unit=str(payload.get("unit") or ""),
        unit_cost=decimal_value(payload.get("unit_cost"), default=Decimal("0.00")),
        total_cost_estimate=decimal_value(payload.get("total_cost_estimate"), default=Decimal("0.00")),
        is_must=bool_value(payload.get("is_must"), default=True),
        notes=str(payload.get("notes") or ""),
        metadata={
            **deepcopy(payload.get("metadata") or {}),
            "source_change_operation_id": operation.operation_id,
        },
    )
    result: dict[str, object] = {
        "action": "add_requirement",
        "requirement_id": requirement.requirement_id,
        "node_id": node.node_id,
    }
    if ordinal is not None:
        result["ordinal"] = ordinal
    record_operation_result(operation, context, **result)


def apply_add_capacity_impact(operation: PlanChangeOperation, context: PlanApplicationContext) -> None:
    payload = operation_payload(operation)
    node = resolve_node(payload, context, id_keys=("node_id", "target_node_id"), code_keys=("node_code", "target_node_code"))
    impact_type = str(payload.get("impact_type") or PlanCapacityImpact.ImpactType.MEMBER_CAPACITY)
    impact = PlanCapacityImpact.objects.using(context.using).create(
        impact_id=unique_model_id(
            PlanCapacityImpact,
            "impact_id",
            f"impact-{slugify(node.code)}-{slugify(impact_type)}-{context.revision_slug}",
            using=context.using,
        ),
        node=node,
        impact_type=impact_type,
        delta=decimal_value(payload.get("delta"), default=Decimal("0")),
        unit=str(payload.get("unit") or ""),
        description=str(payload.get("description") or ""),
        metadata={
            **deepcopy(payload.get("metadata") or {}),
            "source_change_operation_id": operation.operation_id,
        },
    )
    record_operation_result(operation, context, action="add_capacity_impact", impact_id=impact.impact_id, node_id=node.node_id)


def apply_update_node_field(operation: PlanChangeOperation, context: PlanApplicationContext) -> None:
    field_name = operation.target_field
    if field_name not in UPDATABLE_NODE_FIELDS:
        raise DomainError(f"不允许通过计划变更操作更新 PlanNode.{field_name}。")
    payload = operation_payload(operation)
    node = resolve_node(
        {"node_id": operation.target_id, **payload},
        context,
        id_keys=("node_id", "target_node_id"),
        code_keys=("node_code", "target_node_code", "code"),
    )
    value = payload.get("value") if isinstance(payload, dict) and "value" in payload else payload
    save_field = "parent" if field_name == "parent_id" else field_name
    if save_field == "parent":
        value = resolve_optional_parent({"parent_id": value}, context)
    elif save_field in DECIMAL_NODE_FIELDS:
        value = decimal_value(value, default=Decimal("0"))
    elif save_field in INT_NODE_FIELDS:
        value = optional_int_value(value) if value in (None, "") else int_value(value, default=0)
    elif save_field in BOOL_NODE_FIELDS:
        value = bool_value(value, default=False)
    elif save_field in JSON_NODE_FIELDS:
        value = deepcopy(value if value is not None else ([] if save_field != "metadata" else {}))
    setattr(node, save_field, value)
    update_fields = [save_field]
    if save_field != "updated_at":
        node.updated_at = context.applied_at
        update_fields.append("updated_at")
    node.save(update_fields=update_fields)
    record_operation_result(operation, context, action="update_node_field", node_id=node.node_id, field=save_field)


def operation_payload(operation: PlanChangeOperation) -> dict[str, Any]:
    payload = deepcopy(operation.new_value or {})
    if not isinstance(payload, dict):
        raise DomainError(f"计划变更操作 {operation.operation_id} 的 new_value 必须是对象。")
    return payload


def resolve_optional_parent(payload: dict[str, Any], context: PlanApplicationContext) -> PlanNode | None:
    parent_id = payload.get("parent_id")
    parent_code = payload.get("parent_code")
    if parent_id in (None, "") and parent_code in (None, ""):
        return None
    return resolve_node(payload, context, id_keys=("parent_id",), code_keys=("parent_code",))


def resolve_node(
    payload: dict[str, Any],
    context: PlanApplicationContext,
    *,
    id_keys: tuple[str, ...],
    code_keys: tuple[str, ...],
) -> PlanNode:
    for key in id_keys:
        raw = payload.get(key)
        if raw in (None, ""):
            continue
        node_id = str(raw)
        node = context.nodes_by_source_id.get(node_id) or context.nodes_by_new_id.get(node_id)
        if node is not None:
            return node
    for key in code_keys:
        raw = payload.get(key)
        if raw in (None, ""):
            continue
        node = context.nodes_by_code.get(str(raw))
        if node is not None:
            return node
    raise DomainError(f"无法解析计划节点引用：{payload}")


def required_str(payload: dict[str, Any], key: str, *, operation: PlanChangeOperation) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise DomainError(f"计划变更操作 {operation.operation_id} 缺少必填字段：{key}")
    return value


def next_node_sequence(context: PlanApplicationContext) -> int:
    if not context.nodes_by_new_id:
        return 10
    return max(node.sequence for node in context.nodes_by_new_id.values()) + 10


def list_value(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return deepcopy(value)
    return [value]


def decimal_value(value, *, default: Decimal) -> Decimal:
    if value in (None, ""):
        return default
    return Decimal(str(value))


def int_value(value, *, default: int) -> int:
    if value in (None, ""):
        return default
    return int(value)


def optional_int_value(value) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def bool_value(value, *, default: bool) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
