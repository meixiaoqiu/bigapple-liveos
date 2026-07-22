"""Simulation run archival services."""

from __future__ import annotations

import hashlib
import html
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from django.apps import apps
from django.conf import settings
from django.core import serializers
from django.db import connections, transaction
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone

from core.models import (
    Event,
    PlanChangeOperation,
    PlanChangeSet,
    PlanNodeRunState,
    PlanRevisionProposal,
    SimulationFailure,
    SimulationRun,
    SimulationSnapshot,
    SimulationSnapshotItem,
    SimulationTurn,
)
from simulation.disposition import next_simulation_round, record_archived_disposition, scenario_from_run
from worlds.models import WorldRegistry


SNAPSHOT_SCHEMA_VERSION = 1
RAW_ARCHIVE_FORMAT_VERSION = 2
CONTROL_DATABASE_ALIAS: str = getattr(settings, "CONTROL_DATABASE_ALIAS", "default")
EXCLUDED_RAW_MODELS = {
    "core.SimulationSnapshot",
    "core.SimulationSnapshotItem",
}


@dataclass(frozen=True)
class ArchiveResult:
    snapshot: SimulationSnapshot
    created: bool


@dataclass(frozen=True)
class ArchiveVerificationResult:
    snapshot: SimulationSnapshot
    ok: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    raw_model_count: int
    normalized_item_count: int


def archive_simulation_run(
    *,
    world: WorldRegistry,
    run_id: str,
    archive_root: Path | None = None,
    simulation_round: int | None = None,
    scenario: str = "",
    purpose: str = "",
    hypothesis: str = "",
    parameter_summary: dict[str, object] | None = None,
    public_title: str = "",
    public_summary: str = "",
    review_conclusion: str = "",
    next_run_basis: str = "",
    publication_status: str = SimulationSnapshot.PublicationStatus.PUBLIC,
    decided_by: str = "",
    disposition_reason: str = "",
) -> ArchiveResult:
    """Archive one simulation run into immutable raw files and control-DB indexes."""

    source_alias = archive_source_alias(world.database_alias)
    run = SimulationRun.objects.using(source_alias).select_related("plan_revision").get(run_id=run_id)
    existing = SimulationSnapshot.objects.using(CONTROL_DATABASE_ALIAS).filter(
        source_world_id=world.world_id,
        source_run_id=run.run_id,
    ).first()
    if existing is not None:
        record_archived_disposition(
            world=world,
            run=run,
            snapshot=existing,
            reason=disposition_reason,
            decided_by=decided_by,
        )
        return ArchiveResult(snapshot=existing, created=False)

    snapshot_id = _generate_snapshot_id()
    archived_at = timezone.now()
    failure = (
        SimulationFailure.objects.using(source_alias)
        .filter(run_id=run.run_id)
        .order_by("detected_at", "failure_id")
        .first()
    )
    scenario = scenario or scenario_from_run(run)
    simulation_round = simulation_round or next_simulation_round(world_id=world.world_id)
    root = Path(archive_root or settings.SIMULATION_ARCHIVE_ROOT)
    snapshot_dir = root / snapshot_id
    raw_dir = snapshot_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=False)

    raw_models = _export_raw_core_models(source_alias=source_alias, raw_dir=raw_dir)
    raw_archive_hash = _hash_raw_manifest_entries(raw_models)
    manifest = _build_manifest(
        snapshot_id=snapshot_id,
        world=world,
        run=run,
        archived_at=archived_at,
        raw_models=raw_models,
        snapshot_dir=snapshot_dir,
    )
    manifest["raw_archive_hash"] = raw_archive_hash
    manifest_path = snapshot_dir / "manifest.json"
    _write_json(manifest_path, manifest)

    normalized_summary = _normalized_summary(world=world, run=run, source_alias=source_alias)
    report_path = snapshot_dir / "report.html"
    report_path.write_text(_render_report_html(normalized_summary), encoding="utf-8")

    with transaction.atomic(using=CONTROL_DATABASE_ALIAS):
        snapshot = SimulationSnapshot.objects.using(CONTROL_DATABASE_ALIAS).create(
            snapshot_id=snapshot_id,
            title=_snapshot_title(world=world, run=run, failure=failure),
            simulation_round=simulation_round,
            scenario=scenario,
            purpose=purpose,
            hypothesis=hypothesis,
            parameter_summary=parameter_summary or {},
            public_title=public_title,
            public_summary=public_summary,
            review_conclusion=review_conclusion,
            next_run_basis=next_run_basis,
            publication_status=publication_status,
            source_world_id=world.world_id,
            source_world_type=world.world_type,
            source_database_alias=source_alias,
            source_database_name=world.database_name,
            source_run_id=run.run_id,
            plan_revision_id=run.plan_revision_id,
            run_status=run.status,
            failure_type=getattr(failure, "failure_type", "") or "",
            failure_title=getattr(failure, "title", "") or "",
            snapshot_schema_version=SNAPSHOT_SCHEMA_VERSION,
            status=SimulationSnapshot.Status.ARCHIVED,
            raw_archive_path=str(snapshot_dir),
            raw_archive_hash=raw_archive_hash,
            report_path=str(report_path),
            raw_table_counts={item["model"]: item["count"] for item in raw_models},
            normalized_summary=normalized_summary,
            code_version=manifest["code_version"],
            archived_at=archived_at,
            metadata={
                "raw_archive_format_version": RAW_ARCHIVE_FORMAT_VERSION,
                "manifest_path": str(manifest_path),
                "raw_scope": "all_core_domain_models",
            },
        )
        SimulationSnapshotItem.objects.using(CONTROL_DATABASE_ALIAS).bulk_create(
            _normalized_items(snapshot=snapshot, run=run, source_alias=source_alias)
        )
        record_archived_disposition(
            world=world,
            run=run,
            snapshot=snapshot,
            reason=disposition_reason,
            decided_by=decided_by,
        )
    return ArchiveResult(snapshot=snapshot, created=True)


def verify_simulation_snapshot(snapshot_id: str) -> ArchiveVerificationResult:
    """Verify one archived simulation snapshot against its raw package and index."""

    snapshot = SimulationSnapshot.objects.using(CONTROL_DATABASE_ALIAS).get(snapshot_id=snapshot_id)
    errors: list[str] = []
    warnings: list[str] = []
    raw_model_count = 0

    snapshot_dir = Path(snapshot.raw_archive_path)
    manifest_path = Path(str(snapshot.metadata.get("manifest_path") or snapshot_dir / "manifest.json"))
    if not snapshot_dir.is_dir():
        errors.append(f"raw archive directory is missing: {snapshot_dir}")
    if not manifest_path.is_file():
        errors.append(f"manifest is missing: {manifest_path}")
        manifest: dict[str, object] = {}
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"manifest is not valid JSON: {manifest_path}: {exc}")
            manifest = {}

    if manifest:
        raw_models = manifest.get("raw_models")
        if not isinstance(raw_models, list):
            errors.append("manifest.raw_models must be a list")
            raw_models = []
        raw_model_count = len(raw_models)
        _verify_manifest_metadata(snapshot=snapshot, manifest=manifest, errors=errors)
        _verify_raw_models(
            snapshot=snapshot,
            snapshot_dir=snapshot_dir,
            manifest=manifest,
            raw_models=raw_models,
            errors=errors,
            warnings=warnings,
        )

    if snapshot.report_path and not Path(snapshot.report_path).is_file():
        errors.append(f"report file is missing: {snapshot.report_path}")

    normalized_item_count = _verify_normalized_items(snapshot=snapshot, errors=errors)
    return ArchiveVerificationResult(
        snapshot=snapshot,
        ok=not errors,
        errors=tuple(errors),
        warnings=tuple(warnings),
        raw_model_count=raw_model_count,
        normalized_item_count=normalized_item_count,
    )


def _export_raw_core_models(*, source_alias: str, raw_dir: Path) -> list[dict[str, object]]:
    exports: list[dict[str, object]] = []
    for model in sorted(apps.get_app_config("core").get_models(), key=lambda item: item._meta.label):
        model_label = model._meta.label
        if model_label in EXCLUDED_RAW_MODELS:
            continue
        queryset = model._default_manager.using(source_alias).all().order_by(model._meta.pk.name)
        content = serializers.serialize("json", queryset, indent=2)
        filename = f"{model_label}.json"
        path = raw_dir / filename
        path.write_text(content, encoding="utf-8")
        exports.append(
            {
                "model": model_label,
                "db_table": model._meta.db_table,
                "count": queryset.count(),
                "path": f"raw/{filename}",
                "sha256": _sha256_file(path),
            }
        )
    return exports


def archive_source_alias(database_alias: str) -> str:
    if not getattr(settings, "WORLD_DATABASE_ROUTING_ENABLED", True):
        return CONTROL_DATABASE_ALIAS
    return database_alias


def _build_manifest(
    *,
    snapshot_id: str,
    world: WorldRegistry,
    run: SimulationRun,
    archived_at,
    raw_models: list[dict[str, object]],
    snapshot_dir: Path,
) -> dict[str, object]:
    source_alias = archive_source_alias(world.database_alias)
    return {
        "snapshot_id": snapshot_id,
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "raw_archive_format_version": RAW_ARCHIVE_FORMAT_VERSION,
        "created_at": archived_at.isoformat(),
        "source": {
            "world_id": world.world_id,
            "world_type": world.world_type,
            "database_alias": source_alias,
            "database_name": world.database_name or connections[source_alias].settings_dict.get("NAME", ""),
            "run_id": run.run_id,
            "run_status": run.status,
            "plan_revision_id": run.plan_revision_id,
        },
        "code_version": _git_commit_hash(),
        "archive_path": str(snapshot_dir),
        "raw_scope": "all_core_domain_models",
        "raw_models": raw_models,
        "migrations": {
            "source": _migration_state(source_alias),
            "control": _migration_state(CONTROL_DATABASE_ALIAS),
        },
        "raw_archive_hash": "",
    }


def _normalized_summary(*, world: WorldRegistry, run: SimulationRun, source_alias: str) -> dict[str, object]:
    failures = list(SimulationFailure.objects.using(source_alias).filter(run_id=run.run_id).order_by("detected_at"))
    change_sets = list(PlanChangeSet.objects.using(source_alias).filter(run_id=run.run_id).order_by("created_at"))
    return {
        "world": {
            "world_id": world.world_id,
            "world_type": world.world_type,
            "database_alias": world.database_alias,
            "database_name": world.database_name,
        },
        "run": _serialized_payload(run),
        "counts": {
            "turns": SimulationTurn.objects.using(source_alias).filter(run_id=run.run_id).count(),
            "events": Event.objects.using(source_alias).filter(simulation_run_id=run.run_id).count(),
            "node_states": PlanNodeRunState.objects.using(source_alias).filter(run_id=run.run_id).count(),
            "failures": len(failures),
            "proposals": PlanRevisionProposal.objects.using(source_alias).filter(run_id=run.run_id).count(),
            "change_sets": len(change_sets),
            "change_operations": PlanChangeOperation.objects.using(source_alias)
            .filter(change_set__run_id=run.run_id)
            .count(),
        },
        "failures": [_failure_summary(item) for item in failures],
        "change_sets": [_change_set_summary(item, source_alias=source_alias) for item in change_sets],
    }


def _normalized_items(*, snapshot: SimulationSnapshot, run: SimulationRun, source_alias: str) -> list[SimulationSnapshotItem]:
    items: list[SimulationSnapshotItem] = [
        _item(
            snapshot=snapshot,
            sequence=1,
            item_type=SimulationSnapshotItem.ItemType.RUN,
            source_model="core.SimulationRun",
            source_pk=run.run_id,
            title=f"仿真运行 {run.run_id}",
            summary=run.failure_summary,
            payload=_serialized_payload(run),
        )
    ]
    sequence = 100
    for state in (
        PlanNodeRunState.objects.using(source_alias)
        .select_related("plan_node")
        .filter(run_id=run.run_id)
        .order_by("plan_node__sequence", "plan_node_id")
    ):
        sequence += 1
        items.append(
            _item(
                snapshot=snapshot,
                sequence=sequence,
                item_type=SimulationSnapshotItem.ItemType.NODE_STATE,
                source_model="core.PlanNodeRunState",
                source_pk=state.state_id,
                title=_plan_node_label(state.plan_node),
                summary=state.blocker_reason or state.get_status_display(),
                payload=_node_state_payload(state),
            )
        )
    sequence = 1000
    for turn in SimulationTurn.objects.using(source_alias).filter(run_id=run.run_id).order_by("turn_number"):
        sequence += 1
        items.append(
            _item(
                snapshot=snapshot,
                sequence=sequence,
                item_type=SimulationSnapshotItem.ItemType.TURN,
                source_model="core.SimulationTurn",
                source_pk=turn.turn_id,
                title=f"第 {turn.turn_number} 步",
                summary=turn.summary,
                payload=_serialized_payload(turn),
            )
        )
    sequence = 2000
    for failure in SimulationFailure.objects.using(source_alias).filter(run_id=run.run_id).order_by("detected_at"):
        sequence += 1
        items.append(
            _item(
                snapshot=snapshot,
                sequence=sequence,
                item_type=SimulationSnapshotItem.ItemType.FAILURE,
                source_model="core.SimulationFailure",
                source_pk=failure.failure_id,
                title=failure.title,
                summary=failure.description,
                payload=_serialized_payload(failure),
            )
        )
    sequence = 3000
    for event in Event.objects.using(source_alias).filter(simulation_run_id=run.run_id).order_by("occurred_at"):
        sequence += 1
        items.append(
            _item(
                snapshot=snapshot,
                sequence=sequence,
                item_type=SimulationSnapshotItem.ItemType.EVENT,
                source_model="core.Event",
                source_pk=event.event_id,
                title=event.title,
                summary=event.summary,
                payload=_serialized_payload(event),
            )
        )
    sequence = 4000
    for proposal in PlanRevisionProposal.objects.using(source_alias).filter(run_id=run.run_id).order_by("created_at"):
        sequence += 1
        items.append(
            _item(
                snapshot=snapshot,
                sequence=sequence,
                item_type=SimulationSnapshotItem.ItemType.PROPOSAL,
                source_model="core.PlanRevisionProposal",
                source_pk=proposal.proposal_id,
                title=proposal.title,
                summary=proposal.rationale,
                payload=_serialized_payload(proposal),
            )
        )
    sequence = 5000
    for change_set in PlanChangeSet.objects.using(source_alias).filter(run_id=run.run_id).order_by("created_at"):
        sequence += 1
        items.append(
            _item(
                snapshot=snapshot,
                sequence=sequence,
                item_type=SimulationSnapshotItem.ItemType.CHANGE_SET,
                source_model="core.PlanChangeSet",
                source_pk=change_set.change_set_id,
                title=change_set.title,
                summary=change_set.summary,
                payload=_serialized_payload(change_set),
            )
        )
        for operation in PlanChangeOperation.objects.using(source_alias).filter(change_set=change_set).order_by("sequence"):
            sequence += 1
            items.append(
                _item(
                    snapshot=snapshot,
                    sequence=sequence,
                    item_type=SimulationSnapshotItem.ItemType.CHANGE_OPERATION,
                    source_model="core.PlanChangeOperation",
                    source_pk=operation.operation_id,
                    title=f"{operation.sequence}. {operation.get_operation_type_display()}",
                    summary=operation.rationale,
                    payload=_serialized_payload(operation),
                )
            )
    return items


def _item(
    *,
    snapshot: SimulationSnapshot,
    sequence: int,
    item_type: str,
    source_model: str,
    source_pk: str,
    title: str,
    summary: str,
    payload: dict[str, object],
) -> SimulationSnapshotItem:
    return SimulationSnapshotItem(
        item_id=f"{snapshot.snapshot_id}-item-{sequence:06d}",
        snapshot=snapshot,
        item_type=item_type,
        source_model=source_model,
        source_pk=str(source_pk or ""),
        title=str(title or "")[:255],
        summary=str(summary or ""),
        sort_order=sequence,
        payload_json=payload,
    )


def _plan_node_label(node) -> str:
    return f"{node.code} {node.title}".strip() or str(node.pk)


def _node_state_payload(state: PlanNodeRunState) -> dict[str, object]:
    payload = _serialized_payload(state)
    payload["display"] = {
        "plan_node_id": state.plan_node_id,
        "plan_node_code": state.plan_node.code,
        "plan_node_title": state.plan_node.title,
        "plan_node_label": _plan_node_label(state.plan_node),
        "status": state.get_status_display(),
    }
    return payload


def _failure_summary(failure: SimulationFailure) -> dict[str, object]:
    return {
        "failure_id": failure.failure_id,
        "failure_type": failure.failure_type,
        "title": failure.title,
        "description": failure.description,
        "plan_node_id": failure.plan_node_id,
        "simulation_day": failure.simulation_day,
        "metadata": failure.metadata,
    }


def _change_set_summary(change_set: PlanChangeSet, *, source_alias: str) -> dict[str, object]:
    return {
        "change_set_id": change_set.change_set_id,
        "title": change_set.title,
        "summary": change_set.summary,
        "status": change_set.status,
        "operation_count": PlanChangeOperation.objects.using(source_alias).filter(change_set=change_set).count(),
    }


def _serialized_payload(instance) -> dict[str, object]:
    return json.loads(serializers.serialize("json", [instance]))[0]


def _snapshot_title(*, world: WorldRegistry, run: SimulationRun, failure: SimulationFailure | None) -> str:
    if failure is not None:
        return f"{world.world_id} / {run.run_id} / {failure.title}"
    return f"{world.world_id} / {run.run_id} / {run.status}"


def _render_report_html(summary: dict[str, object]) -> str:
    failures = summary.get("failures") or []
    failure_lines = "\n".join(
        f"<li><strong>{html.escape(str(item.get('title', '')))}</strong><br>{html.escape(str(item.get('description', '')))}</li>"
        for item in failures
        if isinstance(item, dict)
    )
    counts = summary.get("counts") if isinstance(summary.get("counts"), dict) else {}
    count_lines = "\n".join(
        f"<li>{html.escape(str(key))}: {html.escape(str(value))}</li>" for key, value in sorted(counts.items())
    )
    run = summary.get("run") if isinstance(summary.get("run"), dict) else {}
    run_pk = html.escape(str(run.get("pk", "")))
    return f"""<!doctype html>
<html lang="zh-Hans">
<head><meta charset="utf-8"><title>仿真快照 {run_pk}</title></head>
<body>
<h1>仿真快照 {run_pk}</h1>
<h2>计数</h2>
<ul>{count_lines}</ul>
<h2>失败</h2>
<ul>{failure_lines or "<li>无失败记录</li>"}</ul>
</body>
</html>
"""


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str), encoding="utf-8")


def _verify_manifest_metadata(
    *,
    snapshot: SimulationSnapshot,
    manifest: dict[str, object],
    errors: list[str],
) -> None:
    if manifest.get("snapshot_id") != snapshot.snapshot_id:
        errors.append("manifest.snapshot_id does not match SimulationSnapshot.snapshot_id")
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    if source.get("world_id") != snapshot.source_world_id:
        errors.append("manifest.source.world_id does not match SimulationSnapshot.source_world_id")
    if source.get("run_id") != snapshot.source_run_id:
        errors.append("manifest.source.run_id does not match SimulationSnapshot.source_run_id")
    if source.get("run_status") != snapshot.run_status:
        errors.append("manifest.source.run_status does not match SimulationSnapshot.run_status")


def _verify_raw_models(
    *,
    snapshot: SimulationSnapshot,
    snapshot_dir: Path,
    manifest: dict[str, object],
    raw_models: list[object],
    errors: list[str],
    warnings: list[str],
) -> None:
    normalized_raw_models: list[dict[str, object]] = []
    table_counts: dict[str, int] = {}
    for index, item in enumerate(raw_models, start=1):
        if not isinstance(item, dict):
            errors.append(f"manifest.raw_models[{index}] must be an object")
            continue
        model_label = str(item.get("model") or "")
        relative_path = str(item.get("path") or "")
        expected_sha = str(item.get("sha256") or "")
        if not model_label or not relative_path or not expected_sha:
            errors.append(f"manifest.raw_models[{index}] is missing model, path, or sha256")
            continue

        raw_path = _archive_child_path(snapshot_dir, relative_path)
        if raw_path is None:
            errors.append(f"raw model path escapes archive directory: {relative_path}")
            continue
        if not raw_path.is_file():
            errors.append(f"raw model file is missing: {relative_path}")
            continue
        actual_sha = _sha256_file(raw_path)
        if actual_sha != expected_sha:
            errors.append(f"raw model file sha256 mismatch: {relative_path}")

        try:
            raw_records = json.loads(raw_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"raw model file is not valid JSON: {relative_path}: {exc}")
            raw_records = []
        expected_count = int(item.get("count") or 0)
        if isinstance(raw_records, list) and len(raw_records) != expected_count:
            errors.append(f"raw model count mismatch: {relative_path}")
        elif not isinstance(raw_records, list):
            errors.append(f"raw model file must contain a JSON list: {relative_path}")

        table_counts[model_label] = expected_count
        normalized_raw_models.append(item)

    if table_counts != snapshot.raw_table_counts:
        errors.append("manifest raw model counts do not match SimulationSnapshot.raw_table_counts")

    expected_hash = str(manifest.get("raw_archive_hash") or "")
    if expected_hash != snapshot.raw_archive_hash:
        errors.append("manifest.raw_archive_hash does not match SimulationSnapshot.raw_archive_hash")

    raw_format_version = int(manifest.get("raw_archive_format_version") or 1)
    if raw_format_version >= 2:
        actual_hash = _hash_raw_manifest_entries(normalized_raw_models)
    else:
        actual_hash = _legacy_hash_archive_files_v1(snapshot_dir=snapshot_dir, manifest=manifest)
        warnings.append("legacy raw archive format verified with v1 manifest hash semantics")
    if expected_hash and actual_hash != expected_hash:
        errors.append("raw archive hash mismatch")


def _verify_normalized_items(*, snapshot: SimulationSnapshot, errors: list[str]) -> int:
    items = SimulationSnapshotItem.objects.using(CONTROL_DATABASE_ALIAS).filter(snapshot=snapshot)
    counts = snapshot.normalized_summary.get("counts")
    if not isinstance(counts, dict):
        errors.append("SimulationSnapshot.normalized_summary.counts is missing")
        return items.count()

    expected_by_type = {
        SimulationSnapshotItem.ItemType.RUN: 1,
        SimulationSnapshotItem.ItemType.TURN: int(counts.get("turns") or 0),
        SimulationSnapshotItem.ItemType.EVENT: int(counts.get("events") or 0),
        SimulationSnapshotItem.ItemType.NODE_STATE: int(counts.get("node_states") or 0),
        SimulationSnapshotItem.ItemType.FAILURE: int(counts.get("failures") or 0),
        SimulationSnapshotItem.ItemType.PROPOSAL: int(counts.get("proposals") or 0),
        SimulationSnapshotItem.ItemType.CHANGE_SET: int(counts.get("change_sets") or 0),
        SimulationSnapshotItem.ItemType.CHANGE_OPERATION: int(counts.get("change_operations") or 0),
    }
    for item_type, expected_count in expected_by_type.items():
        actual_count = items.filter(item_type=item_type).count()
        if actual_count != expected_count:
            errors.append(f"normalized item count mismatch: {item_type}")

    total_count = items.count()
    expected_total = sum(expected_by_type.values())
    if total_count != expected_total:
        errors.append("normalized item total count mismatch")
    return total_count


def _hash_raw_manifest_entries(raw_models: list[dict[str, object]]) -> str:
    digest = hashlib.sha256()
    for item in sorted(raw_models, key=lambda value: str(value.get("model", ""))):
        stable_payload = {
            "count": item.get("count"),
            "db_table": item.get("db_table"),
            "model": item.get("model"),
            "path": item.get("path"),
            "sha256": item.get("sha256"),
        }
        digest.update(
            json.dumps(stable_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode(
                "utf-8"
            )
        )
    return digest.hexdigest()


def _archive_child_path(snapshot_dir: Path, relative_path: str) -> Path | None:
    root = snapshot_dir.resolve()
    path = (snapshot_dir / relative_path).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def _legacy_hash_archive_files_v1(*, snapshot_dir: Path, manifest: dict[str, object]) -> str:
    digest = hashlib.sha256()
    manifest_copy = dict(manifest)
    manifest_copy["raw_archive_hash"] = ""
    for path in sorted(item for item in snapshot_dir.rglob("*") if item.is_file()):
        relative_path = str(path.relative_to(snapshot_dir)).replace("\\", "/")
        if relative_path == "report.html":
            continue
        digest.update(relative_path.encode("utf-8"))
        if relative_path == "manifest.json":
            manifest_content = json.dumps(
                manifest_copy,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                default=str,
            ).encode("utf-8")
            digest.update(hashlib.sha256(manifest_content).hexdigest().encode("ascii"))
        else:
            digest.update(_sha256_file(path).encode("ascii"))
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _migration_state(alias: str) -> list[dict[str, str]]:
    recorder = MigrationRecorder(connections[alias])
    return [
        {"app": item.app, "name": item.name, "applied": item.applied.isoformat()}
        for item in recorder.migration_qs.order_by("app", "name")
    ]


def _git_commit_hash() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=settings.BASE_DIR,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return ""
    return result.stdout.strip()


def _generate_snapshot_id() -> str:
    for _ in range(5):
        snapshot_id = f"snapshot-{uuid4().hex[:12]}"
        if not SimulationSnapshot.objects.using(CONTROL_DATABASE_ALIAS).filter(snapshot_id=snapshot_id).exists():
            return snapshot_id
    raise RuntimeError("Unable to allocate SimulationSnapshot id.")
