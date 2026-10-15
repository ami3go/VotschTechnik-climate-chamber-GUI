"""G07-A deterministic durability, security and crash recovery tests.

These exercise the exact G06 EventSink shape without relying on a browser,
driver, scheduler, or physical chamber. The million-sample test runs when
G07_STRESS=1, including on the dedicated Windows CI job.
"""
from __future__ import annotations

import errno
import io
import json
import os
import sqlite3
import tempfile
import unittest
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile

from chamber_web.domain.chamber import ChamberSafetyError
from chamber_web.persistence.runs import RunIntegrityError, RunNotFoundError, RunRecorder, RunStore


@dataclass(frozen=True)
class Identity:
    chamber_id: str
    backend_id: str = "fake"
    manufacturer: str = "Simulator"
    model: str = "Mock"
    serial_number: str = "TEST"
    is_simulation: bool = True


@dataclass(frozen=True)
class Snapshot:
    schema_version: int
    run_id: str
    chamber_id: str
    identity: Identity
    controller_generation: int
    created_at_utc: str


@dataclass(frozen=True)
class Event:
    run_id: str
    chamber_id: str
    sequence: int
    kind: str
    state: str = "PREPARING"
    monotonic_elapsed_s: float = 0.0
    step_index: int = 0
    detail: str = ""
    temperature_c: float | None = None
    quality: str | None = None
    observed_at_utc: str = "2026-10-13T12:00:00+00:00"
    source_sampled_at_utc: str | None = None
    sample_index: int | None = None


TIME = "2026-10-13T12:00:00+00:00"


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = RunStore(self.temp.name)
        self.sink = RunRecorder(self.store)
        self.chamber = "climate-A"
        self.run = str(uuid4())
        self.snapshot = Snapshot(1, self.run, self.chamber, Identity(self.chamber),
                                 11, TIME)
        self.sink.prepare(self.snapshot)

    def evt(self, seq, kind, **kwargs):
        return Event(self.run, self.chamber, seq, kind, **kwargs)

    def start(self):
        self.sink.emit(self.evt(1, "PREPARED"))
        self.sink.emit(self.evt(2, "START_INTENT"))
        self.sink.emit(self.evt(3, "SETPOINT_INTENT", temperature_c=25.0))
        self.sink.emit(self.evt(4, "STATE", state="REACHING"))

    def sample(self, seq, index):
        return self.evt(seq, "SAMPLE", state="REACHING",
                        sample_index=index, temperature_c=24.5,
                        quality="GOOD", monotonic_elapsed_s=float(index),
                        source_sampled_at_utc=TIME)

    def terminal(self, seq, state="COMPLETED"):
        elapsed = self.store.get_run(self.chamber, self.run)["last_elapsed"]
        self.sink.emit(self.evt(seq, "STOP_INTENT", state="STOP_REQUESTED",
                                monotonic_elapsed_s=elapsed))
        self.sink.emit(self.evt(seq + 1, "TERMINAL", state=state,
                                monotonic_elapsed_s=elapsed))

    def test_crash_between_snapshot_commit_and_first_prepared_event(self):
        # This is a distinct, valid power-loss boundary: prepare() commits
        # before the runner can emit its first PREPARED event.
        self.assertEqual(self.store.get_run(self.chamber, self.run)["event_count"], 0)
        reopened = RunStore(self.temp.name)
        self.assertEqual(reopened.reconcile_startup(),
                         [(self.chamber, self.run, "INTERRUPTED")])
        rows = reopened.list_events(self.chamber, self.run)
        self.assertEqual([(row["sequence"], row["kind"]) for row in rows],
                         [(1, "RECOVERY")])

    def test_cannot_reprepare_a_started_run(self):
        self.start()
        with self.assertRaises(RunIntegrityError):
            self.sink.prepare(self.snapshot)

    def test_decimal_profile_snapshot_is_lossless(self):
        @dataclass(frozen=True)
        class RichSnapshot(Snapshot):
            steps: tuple[Decimal, ...] = (Decimal("25.1250"),)
        new_id = str(uuid4())
        rich = RichSnapshot(1, new_id, self.chamber, Identity(self.chamber),
                            11, TIME)
        self.sink.prepare(rich)
        value = json.loads(self.store.get_run(self.chamber, new_id)["snapshot_json"])
        self.assertEqual(value["steps"], ["25.1250"])

    def test_sequential_fake_and_other_vendor_data_is_isolated(self):
        self.start()
        self.terminal(5)
        next_id = str(uuid4())
        alternate = Snapshot(1, next_id, "alternate-B",
                             Identity("alternate-B", "stub", "Other Manufacturer",
                                      "Different Model", "OTHER", True), 2, TIME)
        self.sink.prepare(alternate)
        self.store.emit(Event(next_id, "alternate-B", 1, "PREPARED"))
        self.store.emit(Event(next_id, "alternate-B", 2, "START_INTENT"))
        self.assertEqual(self.store.get_run(self.chamber, self.run)["lifecycle"], "COMPLETED")
        self.assertEqual(self.store.list_runs("alternate-B")[0]["run_id"], next_id)
        with self.assertRaises(RunNotFoundError):
            self.store.get_run(self.chamber, next_id)

    def test_prepared_snapshot_and_start_intent_durable_before_mutation(self):
        self.sink.prepare(self.snapshot)
        self.sink.emit(self.evt(1, "PREPARED"))
        self.sink.emit(self.evt(2, "START_INTENT"))
        reopened = RunStore(self.temp.name)
        row = reopened.get_run(self.chamber, self.run)
        self.assertEqual(row["lifecycle"], "START_INTENT")
        self.assertEqual(row["event_count"], 2)
        self.assertEqual(json.loads(row["snapshot_json"])["controller_generation"], 11)

    def test_end_to_end_manifest_csv_zip_and_read_api(self):
        self.start()
        self.sink.emit(self.sample(5, 1))
        self.sink.emit(self.evt(6, "STEP_COMPLETED", monotonic_elapsed_s=1.0, detail="=HYPERLINK(\"bad\")"))
        self.terminal(7)
        record = self.store.get_run(self.chamber, self.run)
        self.assertEqual(record["lifecycle"], "COMPLETED")
        self.assertEqual(self.store.verify_artifacts(self.chamber, self.run)["sample_count"], 1)
        self.assertEqual(self.store.plot_samples(self.chamber, self.run)[0]["intended_setpoint_c"], 25.0)
        text = self.store.read_csv(self.chamber, self.run, name="events.csv").decode()
        self.assertIn("'=HYPERLINK", text)
        archive_bytes = self.store.read_zip(self.chamber, self.run)
        self.assertTrue(archive_bytes.startswith(b"PK"))
        with ZipFile(io.BytesIO(archive_bytes)) as archive:
            self.assertEqual(set(archive.namelist()),
                             {"manifest.json", "snapshot.json", "events.csv", "samples.csv"})
            frozen = json.loads(archive.read("snapshot.json"))
            self.assertEqual(frozen["controller_generation"], 11)
        self.assertEqual(len(self.store.list_events(self.chamber, self.run, limit=5)), 5)
        self.assertEqual(self.store.list_runs(self.chamber)[0]["run_id"], self.run)

    def test_cross_chamber_replay_and_path_traversal_rejected(self):
        self.sink.emit(self.evt(1, "PREPARED"))
        with self.assertRaises(RunNotFoundError):
            self.store.get_run("another", self.run)
        with self.assertRaises(ChamberSafetyError):
            self.store.get_run("../unsafe", self.run)
        with self.assertRaises(ValueError):
            self.store.get_run(self.chamber, "../../etc/passwd")
        with self.assertRaises(RunIntegrityError):
            self.sink.prepare(Snapshot(1, self.run, "another", Identity("another"),
                                       11, TIME))
        with self.assertRaises(RunNotFoundError):
            self.store.emit(Event(self.run, "another", 2, "START_INTENT"))

    def test_idempotent_replay_and_sample_index_gaps(self):
        self.start()
        event = self.sample(5, 1)
        self.sink.emit(event)
        self.sink.emit(event)
        self.assertEqual(self.store.get_run(self.chamber, self.run)["sample_count"], 1)
        with self.assertRaises(RunIntegrityError):
            self.sink.emit(self.sample(5, 2))
        with self.assertRaises(RunIntegrityError):
            self.sink.emit(self.sample(6, 3))
        with self.assertRaises(RunIntegrityError):
            self.sink.emit(self.sample(7, 2))
        self.sink.emit(self.sample(6, 2))
        self.assertEqual([r["sample_index"] for r in self.store.plot_samples(self.chamber, self.run)],
                         [1, 2])

    def test_recovery_prepared_no_commands_is_interrupted(self):
        self.sink.emit(self.evt(1, "PREPARED"))
        new_process = RunStore(self.temp.name)
        recovered = new_process.reconcile_startup()
        self.assertEqual(recovered, [(self.chamber, self.run, "INTERRUPTED")])
        self.assertEqual(new_process.get_run(self.chamber, self.run)["lifecycle"], "INTERRUPTED")
        self.assertEqual(new_process.reconcile_startup(), [])
        self.assertEqual(new_process.list_events(self.chamber, self.run)[-1]["kind"], "RECOVERY")

    def test_crash_after_start_intent_is_unknown_not_stopped(self):
        self.start()
        self.sink.emit(self.sample(5, 1))
        reopened = RunStore(self.temp.name)
        self.assertEqual(reopened.reconcile_startup()[0][2], "UNKNOWN")
        self.assertEqual(reopened.get_run(self.chamber, self.run)["lifecycle"], "UNKNOWN")
        self.assertNotIn("STOPPED", reopened.read_csv(self.chamber, self.run,
                                                       name="events.csv").decode())

    def test_crash_after_stop_intent_does_not_assert_safe_stop(self):
        self.start()
        self.sink.emit(self.evt(5, "STOP_INTENT", state="STOP_REQUESTED"))
        reopened = RunStore(self.temp.name)
        self.assertEqual(reopened.reconcile_startup()[0][2], "UNKNOWN")

    def test_finalizing_crash_restart_preserves_committed_terminal(self):
        self.start()
        self.sink.emit(self.evt(5, "STOP_INTENT", state="STOP_REQUESTED"))
        with patch.object(RunStore, "_atomic_file", side_effect=OSError(errno.ENOSPC, "disk full")):
            with self.assertRaises(OSError):
                self.sink.emit(self.evt(6, "TERMINAL", state="CANCELLED"))
        self.assertEqual(self.store.get_run(self.chamber, self.run)["lifecycle"], "FINALIZING")
        recovered = RunStore(self.temp.name)
        self.assertEqual(recovered.reconcile_startup()[0][2], "ABORTED")
        self.assertEqual(recovered.get_run(self.chamber, self.run)["lifecycle"], "ABORTED")

    def test_idempotent_terminal_retries_failed_finalization(self):
        self.start()
        self.sink.emit(self.evt(5, "STOP_INTENT", state="STOP_REQUESTED"))
        terminal = self.evt(6, "TERMINAL", state="COMPLETED")
        with patch.object(RunStore, "_atomic_file",
                          side_effect=OSError(errno.ENOSPC, "disk full")):
            with self.assertRaises(OSError):
                self.sink.emit(terminal)
        self.assertEqual(self.store.get_run(self.chamber, self.run)["lifecycle"],
                         "FINALIZING")
        self.sink.emit(terminal)  # Replay must not append or rewrite evidence.
        row = self.store.get_run(self.chamber, self.run)
        self.assertEqual(row["lifecycle"], "COMPLETED")
        self.assertEqual(row["event_count"], 6)
        self.store.verify_artifacts(self.chamber, self.run)

    def test_interrupted_sql_transaction_rolls_back(self):
        self.sink.emit(self.evt(1, "PREPARED"))
        original = RunStore._append
        def inject(db, event):
            original(db, event)
            raise OSError(errno.EIO, "crash during journal transaction")
        with patch.object(RunStore, "_append", side_effect=inject):
            with self.assertRaises(OSError):
                self.sink.emit(self.evt(2, "START_INTENT"))
        self.assertEqual(self.store.get_run(self.chamber, self.run)["event_count"], 1)
        self.sink.emit(self.evt(2, "START_INTENT"))

    def test_corrupt_export_and_manifest_are_detected_not_replaced(self):
        self.start()
        self.terminal(5)
        directory = (Path(self.temp.name) / "data" / "chambers" /
                     self.chamber / "runs" / self.run)
        sample_path = directory / "samples.csv"
        sample_path.write_bytes(b"tampered")
        with self.assertRaises(RunIntegrityError):
            self.store.verify_artifacts(self.chamber, self.run)
        with self.assertRaises(RunIntegrityError):
            self.store.read_zip(self.chamber, self.run)
        sample_path.unlink()
        with self.assertRaises(RunIntegrityError):
            self.store.verify_artifacts(self.chamber, self.run)
        (directory / "manifest.json").write_text("{bad json", encoding="utf-8")
        with self.assertRaises(RunIntegrityError):
            self.store.verify_artifacts(self.chamber, self.run)

    def test_corrupt_snapshot_export_detected(self):
        self.start()
        self.terminal(5)
        path = (Path(self.temp.name) / "data" / "chambers" /
                self.chamber / "runs" / self.run / "snapshot.json")
        path.write_text('{"altered": true}', encoding="utf-8")
        with self.assertRaises(RunIntegrityError):
            self.store.verify_artifacts(self.chamber, self.run)

    def test_failure_during_export_never_marks_completed(self):
        self.start()
        self.sink.emit(self.evt(5, "STOP_INTENT", state="STOP_REQUESTED"))
        original = RunStore._sync_parent
        def fail_sync(path):
            raise OSError(errno.EIO, "directory fsync failed")
        with patch.object(RunStore, "_sync_parent", side_effect=fail_sync):
            with self.assertRaises(OSError):
                self.sink.emit(self.evt(6, "TERMINAL", state="COMPLETED"))
        self.assertEqual(self.store.get_run(self.chamber, self.run)["lifecycle"], "FINALIZING")
        # Since a final file may have been atomically installed, rerun must not
        # silently alter its bytes; unchanged artifacts can be reused.
        with patch.object(RunStore, "_sync_parent", original):
            self.store.reconcile_startup()
        self.assertEqual(self.store.get_run(self.chamber, self.run)["lifecycle"], "COMPLETED")

    def test_bounded_views_and_downloads(self):
        self.start()
        self.store.emit_batch([self.sample(i + 5, i + 1) for i in range(100)])
        self.assertLessEqual(len(self.store.plot_samples(self.chamber, self.run, limit=9)), 9)
        with self.assertRaises(ValueError):
            self.store.plot_samples(self.chamber, self.run, limit=10000)
        with self.assertRaises(ValueError):
            self.store.list_events(self.chamber, self.run, limit=10000)
        with self.assertRaises(ValueError):
            self.store.list_runs(self.chamber, limit=10000)
        self.terminal(105)
        with self.assertRaises(ValueError):
            self.store.read_csv(self.chamber, self.run, name="events.csv", max_bytes=1)
        with self.assertRaises(ValueError):
            self.store.read_csv(self.chamber, self.run, name="../runs.sqlite3")

    def test_missing_sqlite_with_surviving_run_directory_is_not_reset(self):
        # Removing the database must never masquerade as a clean install.
        # A surviving run directory proves the deployment already recorded a
        # PREPARED run, even if export files have not yet been materialized.
        run_directory = (Path(self.temp.name) / "data" / "chambers" /
                         self.chamber / "runs" / self.run)
        self.assertTrue(run_directory.is_dir())
        self.store.database.unlink()
        self.assertFalse(self.store.database.exists())
        with self.assertRaisesRegex(RunIntegrityError, "restore from backup"):
            RunStore(self.temp.name)
        self.assertFalse(self.store.database.exists())

    def test_missing_sqlite_with_sidecar_is_not_reset(self):
        # A former SQLite WAL/journal can survive independently of run files.
        # This must not be silently discarded by sqlite3.connect().
        (self.store.data / "chambers" / self.chamber / "runs" / self.run).rmdir()
        (self.store.data / "chambers" / self.chamber / "runs").rmdir()
        (self.store.data / "chambers" / self.chamber).rmdir()
        (self.store.data / "chambers").rmdir()
        self.store.database.unlink()
        sidecar = self.store.data / "runs.sqlite3-wal"
        sidecar.write_bytes(b"not a recovered SQLite database")
        with self.assertRaisesRegex(RunIntegrityError, "restore from backup"):
            RunStore(self.temp.name)
        self.assertFalse(self.store.database.exists())

    def test_damaged_sqlite_header_prevents_startup_without_recreation(self):
        # Never convert corrupt SQLite bytes into a fresh empty journal.
        original_bytes = self.store.database.read_bytes()
        self.assertGreater(len(original_bytes), 100)
        with self.store.database.open("r+b") as stream:
            stream.seek(0)
            stream.write(b"CORRUPTED_SQLITE!")
            stream.flush()
        with self.assertRaises(RunIntegrityError):
            RunStore(self.temp.name)
        self.assertNotEqual(self.store.database.read_bytes(), original_bytes)
        self.assertTrue(self.store.database.read_bytes().startswith(b"CORRUPTED_SQLITE!"))

    def test_unknown_schema_refused(self):
        db = sqlite3.connect(self.store.database)
        try:
            db.execute("PRAGMA user_version=99")
            db.commit()
        finally:
            db.close()
        with self.assertRaises(RunIntegrityError):
            RunStore(self.temp.name)

    def test_tampered_sqlite_trigger_same_name_is_rejected(self):
        db = sqlite3.connect(self.store.database)
        try:
            db.execute("DROP TRIGGER immutable_events_delete")
            db.execute("CREATE TRIGGER immutable_events_delete BEFORE DELETE ON events "
                       "BEGIN SELECT 1; END")
            db.commit()
        finally:
            db.close()
        with self.assertRaises(RunIntegrityError):
            RunStore(self.temp.name)

    def test_immutable_snapshot_checksum_cannot_be_updated_by_sql(self):
        db = sqlite3.connect(self.store.database)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE runs SET snapshot_sha256=? WHERE run_id=?",
                           ("0" * 64, self.run))
            db.rollback()
        finally:
            db.close()
        self.assertEqual(self.store.get_run(self.chamber, self.run)["lifecycle"],
                         "PREPARED")

    def test_recovery_retries_after_filesystem_disk_full(self):
        self.start()
        with patch.object(RunStore, "_atomic_file",
                          side_effect=OSError(errno.ENOSPC, "full")):
            with self.assertRaises(OSError):
                self.store.reconcile_startup()
        self.assertEqual(self.store.get_run(self.chamber, self.run)["lifecycle"],
                         "FINALIZING")
        reopened = RunStore(self.temp.name)
        self.assertEqual(reopened.reconcile_startup()[0][2], "UNKNOWN")

    def test_invalid_timestamp_nan_and_gaps_rejected(self):
        self.sink.emit(self.evt(1, "PREPARED"))
        with self.assertRaises(ValueError):
            self.sink.emit(self.evt(2, "START_INTENT", observed_at_utc="2026-10-13"))
        with self.assertRaises(ValueError):
            self.sink.emit(self.evt(2, "START_INTENT", monotonic_elapsed_s=float("nan")))
        with self.assertRaises(RunIntegrityError):
            self.sink.emit(self.evt(3, "START_INTENT"))
        self.sink.emit(self.evt(2, "START_INTENT"))
        with self.assertRaises(ValueError):
            self.sink.emit(self.evt(3, "SETPOINT_INTENT", monotonic_elapsed_s=-1,
                                    temperature_c=25.0))

    @unittest.skipUnless(os.environ.get("G07_STRESS") == "1", "Enable million-sample job via G07_STRESS=1")
    def test_one_million_samples_real_sqlite_and_bounded_plot(self):
        self.start()
        for base in range(0, 1_000_000, 1000):
            self.store.emit_batch(
                [self.sample(i + 5, i + 1) for i in range(base, base + 1000)]
            )
        row = self.store.get_run(self.chamber, self.run)
        self.assertEqual(row["sample_count"], 1_000_000)
        self.assertEqual(row["event_count"], 1_000_004)
        graph = self.store.plot_samples(self.chamber, self.run, limit=1000)
        self.assertLessEqual(len(graph), 1000)
        self.assertEqual(graph[0]["sample_index"], 1)
        self.terminal(1_000_005)
        self.assertEqual(self.store.verify_artifacts(self.chamber, self.run)["sample_count"],
                         1_000_000)


if __name__ == "__main__":
    unittest.main()
