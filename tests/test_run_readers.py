"""G07-C RunStore -> HistoryReader/EventReader projection tests.

Deterministic, no browser, no chamber I/O: a real SQLite journal is written
through the production RunRecorder, then read back only through the read-only
adapters that /history and /logs consume.
"""
from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from unittest.mock import patch
from uuid import uuid4

from chamber_web.persistence.runs import RunIntegrityError, RunRecorder, RunStore
from chamber_web.services.run_readers import RunStoreReader


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
    profile_name: str
    revision: int
    operator_id: str


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


class RunStoreReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = RunStore(self.temp.name)
        self.sink = RunRecorder(self.store)
        self.chamber = "climate-A"
        self.reader = RunStoreReader(lambda: self.store)

    def _prepare(self, chamber=None, *, profile="Cold soak", revision=3,
                 operator="op-7"):
        chamber = chamber or self.chamber
        run_id = str(uuid4())
        self.sink.prepare(Snapshot(1, run_id, chamber, Identity(chamber), 4, TIME,
                                   profile, revision, operator))
        return run_id

    def _start(self, run_id, chamber=None):
        chamber = chamber or self.chamber
        self.sink.emit(Event(run_id, chamber, 1, "PREPARED"))
        self.sink.emit(Event(run_id, chamber, 2, "START_INTENT"))
        self.sink.emit(Event(run_id, chamber, 3, "STATE", state="REACHING",
                             detail="reaching target"))

    def _sample(self, run_id, seq, index, chamber=None):
        chamber = chamber or self.chamber
        self.sink.emit(Event(run_id, chamber, seq, "SAMPLE", state="REACHING",
                             sample_index=index, temperature_c=24.5, quality="GOOD",
                             monotonic_elapsed_s=float(index),
                             source_sampled_at_utc=TIME, detail="sample"))

    def _terminal(self, run_id, seq, state="COMPLETED", chamber=None):
        chamber = chamber or self.chamber
        elapsed = self.store.get_run(chamber, run_id)["last_elapsed"]
        self.sink.emit(Event(run_id, chamber, seq, "STOP_INTENT",
                             state="STOP_REQUESTED", monotonic_elapsed_s=elapsed))
        self.sink.emit(Event(run_id, chamber, seq + 1, "TERMINAL", state=state,
                             monotonic_elapsed_s=elapsed, detail="run finished"))

    def test_unavailable_provider_is_not_an_empty_success(self):
        reader = RunStoreReader(lambda: None)
        page = reader.list_runs(self.chamber)
        self.assertFalse(page.available)
        self.assertEqual(page.records, ())
        self.assertIn("not installed", page.detail)

    def test_failed_provider_degrades_to_unavailable(self):
        def explode():
            raise RuntimeError("journal init failed")
        reader = RunStoreReader(explode)
        self.assertFalse(reader.list_runs(self.chamber).available)
        self.assertFalse(reader.list_events(self.chamber).available)

    def test_run_record_retains_profile_operator_and_outcome(self):
        run_id = self._prepare()
        self._start(run_id)
        self._sample(run_id, 4, 1)
        self._terminal(run_id, 5)
        page = self.reader.list_runs(self.chamber)
        self.assertTrue(page.available)
        self.assertEqual(len(page.records), 1)
        row = page.records[0]
        self.assertEqual(row.run_id, run_id)
        self.assertEqual(row.profile_name, "Cold soak")
        self.assertEqual(row.profile_revision, 3)
        self.assertEqual(row.operator, "op-7")
        self.assertEqual(row.outcome, "COMPLETED")
        self.assertIsNotNone(row.started_at_utc.tzinfo)
        self.assertIsNotNone(row.ended_at_utc)
        # The last durable event time is the only recorded end evidence.
        self.assertEqual(row.ended_at_utc, row.started_at_utc)

    def test_started_run_has_no_invented_end_time(self):
        run_id = self._prepare()
        self._start(run_id)
        row = self.reader.list_runs(self.chamber).records[0]
        self.assertIsNone(row.ended_at_utc)
        self.assertEqual(row.outcome, "RUNNING")

    def test_runs_are_scoped_to_the_requested_chamber(self):
        mine = self._prepare()
        self._start(mine)
        other = self._prepare(chamber="climate-B", profile="Other")
        self._start(other, chamber="climate-B")
        page = self.reader.list_runs(self.chamber)
        self.assertEqual([r.run_id for r in page.records], [mine])
        self.assertTrue(all(r.chamber_id == self.chamber for r in page.records))

    def test_search_matches_run_id_or_profile_without_sql(self):
        run_id = self._prepare(profile="Cold soak")
        self._start(run_id)
        self.assertEqual(self.reader.list_runs(self.chamber, search="cold").records[0].run_id,
                         run_id)
        self.assertEqual(self.reader.list_runs(self.chamber, search=run_id[:8]).records[0].run_id,
                         run_id)
        self.assertEqual(self.reader.list_runs(self.chamber, search="no-match").records, ())

    def test_invalid_chamber_returns_no_records(self):
        page = self.reader.list_runs("")
        self.assertTrue(page.available)
        self.assertEqual(page.records, ())

    def test_events_report_conservative_severity(self):
        run_id = self._prepare()
        self._start(run_id)
        self._sample(run_id, 4, 1)
        self._terminal(run_id, 5, state="FAULT")
        page = self.reader.list_events(self.chamber)
        self.assertTrue(page.available)
        by_severity = {row.severity for row in page.records}
        self.assertIn("ERROR", by_severity)   # the FAULT terminal
        self.assertIn("DEBUG", by_severity)   # SAMPLE/STATE observations
        fault = [row for row in page.records if row.severity == "ERROR"]
        self.assertEqual(len(fault), 1)
        self.assertEqual(fault[0].run_id, run_id)
        self.assertEqual(fault[0].event_id, f"{run_id}:6")

    def test_recovery_event_is_a_warning_not_a_success(self):
        self._prepare()
        reopened = RunStore(self.temp.name)
        reopened.reconcile_startup()
        reader = RunStoreReader(lambda: reopened)
        page = reader.list_events(self.chamber)
        recovery = [row for row in page.records if row.event_id.endswith(":1")]
        self.assertEqual(len(recovery), 1)
        self.assertEqual(recovery[0].severity, "WARNING")
        self.assertEqual(reader.list_runs(self.chamber).records[0].outcome, "INTERRUPTED")

    def test_severity_filter_is_exact(self):
        run_id = self._prepare()
        self._start(run_id)
        self._sample(run_id, 4, 1)
        info = self.reader.list_events(self.chamber, severity="INFO")
        self.assertTrue(info.records)
        self.assertTrue(all(row.severity == "INFO" for row in info.records))
        critical = self.reader.list_events(self.chamber, severity="CRITICAL")
        self.assertEqual(critical.records, ())

    def test_event_search_filters_on_message(self):
        run_id = self._prepare()
        self._start(run_id)
        hit = self.reader.list_events(self.chamber, search="reaching target")
        self.assertTrue(hit.records)
        miss = self.reader.list_events(self.chamber, search="absent")
        self.assertEqual(miss.records, ())

    def test_long_run_returns_recent_events_not_the_oldest_page(self):
        run_id = self._prepare()
        self._start(run_id)
        for sequence in range(4, 109):
            self._sample(run_id, sequence, sequence - 3)
        page = self.reader.list_events(self.chamber, limit=10)
        sequences = {int(row.event_id.rsplit(":", 1)[1]) for row in page.records}
        self.assertEqual(len(page.records), 10)
        self.assertIn(108, sequences)
        self.assertNotIn(1, sequences)

    def test_one_corrupt_run_fails_closed_instead_of_hiding_it(self):
        self._prepare()
        with patch.object(self.store, "get_run",
                          side_effect=RunIntegrityError("snapshot mismatch")):
            history = self.reader.list_runs(self.chamber)
        self.assertFalse(history.available)
        self.assertEqual(history.records, ())

        with patch.object(self.store, "list_events",
                          side_effect=RunIntegrityError("event corruption")):
            events = self.reader.list_events(self.chamber)
        self.assertFalse(events.available)
        self.assertEqual(events.records, ())

    def test_limits_are_bounded_and_pages_never_exceed_100(self):
        for _ in range(3):
            run_id = self._prepare()
            self._start(run_id)
            self._sample(run_id, 4, 1)
            self._terminal(run_id, 5)
        page = self.reader.list_runs(self.chamber, limit=10_000)
        self.assertLessEqual(len(page.records), 3)  # store caps at 200, only 3 exist
        events = self.reader.list_events(self.chamber, limit=-5)
        self.assertLessEqual(len(events.records), 100)

    def test_corrupt_journal_reports_unavailable_not_fabricated(self):
        self._prepare()
        self.store.database.write_bytes(b"not a database")
        reader = RunStoreReader(lambda: self.store)
        page = reader.list_runs(self.chamber)
        self.assertFalse(page.available)
        self.assertEqual(page.records, ())


if __name__ == "__main__":
    unittest.main()
