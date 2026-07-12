from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from core.models import (
    Event,
    PlanChangeOperation,
    PlanNodeRunState,
    SimulationFailure,
    SimulationRun,
    SimulationRunDisposition,
    SimulationSnapshot,
    SimulationSnapshotItem,
    SimulationTurn,
)


@override_settings(
    WORLD_DATABASE_ROUTING_ENABLED=False,
    DEFAULT_WORLD_DATABASE_ALIAS="default",
    WORLD_DATABASE_ALIASES=("default",),
)
class SimulationArchiveTests(TestCase):
    def test_archive_simulation_run_preserves_raw_package_and_normalized_index(self) -> None:
        call_command("run_simulation_smoke", "--world-id", "simulation0001", "--max-turns", "30", stdout=StringIO())
        run = SimulationRun.objects.get()

        with TemporaryDirectory() as archive_root:
            output = StringIO()
            call_command(
                "archive_simulation_run",
                "--world-id",
                "simulation0001",
                "--run-id",
                run.run_id,
                "--archive-root",
                archive_root,
                stdout=output,
            )

            snapshot = SimulationSnapshot.objects.get(source_world_id="simulation0001", source_run_id=run.run_id)
            disposition = SimulationRunDisposition.objects.get(source_world_id="simulation0001", source_run_id=run.run_id)
            self.assertIn("Simulation snapshot archived", output.getvalue())
            self.assertEqual(snapshot.simulation_round, 1)
            self.assertEqual(snapshot.run_status, SimulationRun.Status.FAILED)
            self.assertEqual(snapshot.failure_type, SimulationFailure.FailureType.RESPONSIBILITY_CLOSURE_MISSING)
            self.assertEqual(disposition.disposition, SimulationRunDisposition.Disposition.ARCHIVED)
            self.assertEqual(disposition.snapshot, snapshot)
            self.assertEqual(disposition.simulation_round, snapshot.simulation_round)
            self.assertTrue(snapshot.raw_archive_hash)
            self.assertIn("core.SimulationRun", snapshot.raw_table_counts)
            self.assertIn("core.PlanNode", snapshot.raw_table_counts)
            self.assertIn("core.Event", snapshot.raw_table_counts)

            manifest_path = snapshot.metadata["manifest_path"]
            with open(manifest_path, encoding="utf-8") as handle:
                manifest = json.load(handle)
            self.assertEqual(manifest["source"]["run_id"], run.run_id)
            self.assertEqual(manifest["raw_scope"], "all_core_domain_models")
            self.assertEqual(manifest["raw_archive_format_version"], 2)
            self.assertEqual(manifest["raw_archive_hash"], snapshot.raw_archive_hash)
            self.assertTrue((snapshot.raw_archive_path and snapshot.report_path))

            raw_model_names = {item["model"] for item in manifest["raw_models"]}
            self.assertIn("core.SimulationRun", raw_model_names)
            self.assertIn("core.SimulationFailure", raw_model_names)
            self.assertIn("core.PlanChangeOperation", raw_model_names)

            item_types = set(SimulationSnapshotItem.objects.filter(snapshot=snapshot).values_list("item_type", flat=True))
            self.assertIn(SimulationSnapshotItem.ItemType.RUN, item_types)
            self.assertIn(SimulationSnapshotItem.ItemType.TURN, item_types)
            self.assertIn(SimulationSnapshotItem.ItemType.FAILURE, item_types)
            self.assertIn(SimulationSnapshotItem.ItemType.EVENT, item_types)
            self.assertIn(SimulationSnapshotItem.ItemType.CHANGE_OPERATION, item_types)
            self.assertEqual(
                SimulationSnapshotItem.objects.filter(
                    snapshot=snapshot,
                    item_type=SimulationSnapshotItem.ItemType.TURN,
                ).count(),
                SimulationTurn.objects.filter(run=run).count(),
            )
            self.assertEqual(
                SimulationSnapshotItem.objects.filter(
                    snapshot=snapshot,
                    item_type=SimulationSnapshotItem.ItemType.EVENT,
                ).count(),
                Event.objects.filter(simulation_run=run).count(),
            )
            self.assertEqual(
                SimulationSnapshotItem.objects.filter(
                    snapshot=snapshot,
                    item_type=SimulationSnapshotItem.ItemType.CHANGE_OPERATION,
                ).count(),
                PlanChangeOperation.objects.filter(change_set__run=run).count(),
            )
            self.assertTrue(
                SimulationSnapshotItem.objects.filter(
                    snapshot=snapshot,
                    item_type=SimulationSnapshotItem.ItemType.NODE_STATE,
                    title__contains="光伏一期",
                ).exists()
            )
            self.assertFalse(
                SimulationSnapshotItem.objects.filter(
                    snapshot=snapshot,
                    item_type=SimulationSnapshotItem.ItemType.NODE_STATE,
                    title__startswith="node-",
                ).exists()
            )
            self.assertEqual(
                SimulationSnapshotItem.objects.filter(
                    snapshot=snapshot,
                    item_type=SimulationSnapshotItem.ItemType.NODE_STATE,
                ).count(),
                PlanNodeRunState.objects.filter(run=run).count(),
            )
            snapshot.title = "should not change"
            with self.assertRaisesMessage(ValueError, "SimulationSnapshot is immutable"):
                snapshot.save()
            item = SimulationSnapshotItem.objects.filter(snapshot=snapshot).first()
            self.assertIsNotNone(item)
            item.title = "should not change"
            with self.assertRaisesMessage(ValueError, "SimulationSnapshotItem is immutable"):
                item.save()

            second_output = StringIO()
            call_command(
                "archive_simulation_run",
                "--world-id",
                "simulation0001",
                "--run-id",
                run.run_id,
                "--archive-root",
                archive_root,
                stdout=second_output,
            )
            self.assertIn("already exists", second_output.getvalue())
            self.assertEqual(SimulationSnapshot.objects.filter(source_run_id=run.run_id).count(), 1)
            self.assertEqual(SimulationRunDisposition.objects.filter(source_run_id=run.run_id).count(), 1)

            verify_output = StringIO()
            call_command("verify_simulation_snapshot", snapshot.snapshot_id, stdout=verify_output)
            self.assertIn("Simulation snapshot verified", verify_output.getvalue())

            raw_file_path = Path(snapshot.raw_archive_path) / manifest["raw_models"][0]["path"]
            raw_payload = json.loads(raw_file_path.read_text(encoding="utf-8"))
            raw_payload.append({"model": "tampered", "pk": "tampered", "fields": {}})
            raw_file_path.write_text(json.dumps(raw_payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesMessage(CommandError, "raw model file sha256 mismatch"):
                call_command("verify_simulation_snapshot", snapshot.snapshot_id, stdout=StringIO())

    def test_finished_run_requires_archive_or_discard_before_next_run(self) -> None:
        call_command("run_simulation_smoke", "--world-id", "simulation0001", "--max-turns", "30", stdout=StringIO())
        run = SimulationRun.objects.get()

        with self.assertRaisesMessage(CommandError, "已结束但未处置"):
            call_command("run_simulation_smoke", "--world-id", "simulation0001", "--max-turns", "30", stdout=StringIO())

        discard_output = StringIO()
        call_command(
            "discard_simulation_run",
            "--world-id",
            "simulation0001",
            "--run-id",
            run.run_id,
            "--reason",
            "参数误设，作为调试运行放弃归档。",
            stdout=discard_output,
        )
        disposition = SimulationRunDisposition.objects.get(source_world_id="simulation0001", source_run_id=run.run_id)
        self.assertEqual(disposition.disposition, SimulationRunDisposition.Disposition.DISCARDED)
        self.assertEqual(disposition.simulation_round, 1)
        self.assertIn("Simulation run discarded", discard_output.getvalue())
        disposition.reason = "should not change"
        with self.assertRaisesMessage(ValueError, "SimulationRunDisposition is immutable"):
            disposition.save()

        second_output = StringIO()
        call_command("run_simulation_smoke", "--world-id", "simulation0001", "--max-turns", "30", stdout=second_output)
        self.assertIn("Simulation smoke passed", second_output.getvalue())

    def test_archived_run_cannot_be_discarded(self) -> None:
        call_command("run_simulation_smoke", "--world-id", "simulation0001", "--max-turns", "30", stdout=StringIO())
        run = SimulationRun.objects.get()

        with TemporaryDirectory() as archive_root:
            call_command(
                "archive_simulation_run",
                "--world-id",
                "simulation0001",
                "--run-id",
                run.run_id,
                "--archive-root",
                archive_root,
                stdout=StringIO(),
            )

            with self.assertRaisesMessage(CommandError, "Archived simulation run cannot be discarded"):
                call_command(
                    "discard_simulation_run",
                    "--world-id",
                    "simulation0001",
                    "--run-id",
                    run.run_id,
                    "--reason",
                    "不应允许放弃已经归档的运行。",
                    stdout=StringIO(),
                )
