"""G07-C: read-only adapters from the G07-A run journal to the G02-B seams.

These adapters project already-durable ``RunStore`` rows into the backend-neutral
``RunRecord``/``EventRecord`` shapes that ``/history`` and ``/logs`` render. They
never synthesize, infer or recompute evidence: missing values stay missing, a
chamber's rows are scoped by chamber, and an unavailable journal returns an
unavailable page rather than an empty (fabricated) success.

Authorization is NOT implemented here. G08-min must guard every read at the
page/service boundary; these are server-service APIs only, never HTTP routes.
The journal is synchronous SQLite, so callers must offload these reads off the
NiceGUI event loop (the pages use ``asyncio.to_thread``).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from chamber_web.domain.chamber import validate_chamber_id
from chamber_web.persistence.runs import (
    FINAL,
    RunIntegrityError,
    RunNotFoundError,
    RunStore,
)
from chamber_web.services.web_read_models import (
    EventRecord,
    RecordPage,
    RunRecord,
    bounded_search,
)

# The pages request up to 50 rows; RecordPage rejects more than 100 in total.
_MAX_RECORDS = 100
_MAX_RUN_SCAN = 25  # chamber-wide event scans stay bounded by recent runs

# A read that cannot be served truthfully degrades to an unavailable page; it
# must never be reported as an empty (successful) history.
_READ_ERRORS = (RunIntegrityError, RunNotFoundError, sqlite3.DatabaseError, ValueError)

# Conservative, documented severity. The journal records an event ``kind`` and a
# run ``state``, NOT an operator log level; this mapping is presentation only and
# never upgrades an observation into a claim about the chamber.
_FAULT_STATES = frozenset({"FAULT", "UNKNOWN"})
_DEBUG_KINDS = frozenset({"SAMPLE", "STATE"})


def _severity(kind: str, state: str) -> str:
    if state in _FAULT_STATES:
        return "ERROR"          # FAULT/UNKNOWN: never reported as benign.
    if kind == "RECOVERY":
        return "WARNING"        # Interrupted-run reconciliation needs review.
    if kind in _DEBUG_KINDS:
        return "DEBUG"          # High-volume observations (SAMPLE/STATE).
    return "INFO"


def _parse_utc(value: str) -> datetime:
    """Reject a journal timestamp the public read API cannot trust."""
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset().total_seconds() != 0:
        raise RunIntegrityError("Journal timestamp is not UTC")
    return stamp.astimezone(timezone.utc)


def _bounded_limit(limit: int) -> int:
    if type(limit) is not int or limit < 1:
        return 50
    return min(limit, _MAX_RECORDS)


class RunStoreReader:
    """Serve RunRecord/EventRecord pages from one composition-owned RunStore.

    ``store_provider`` returns the deployed journal or raises/returns nothing
    when it is unavailable (fail-closed). This indirection keeps a single
    RunStore owner in the composition root instead of a second journal handle.
    """

    def __init__(self, store_provider) -> None:
        self._store_provider = store_provider

    def _store(self) -> RunStore | None:
        try:
            store = self._store_provider()
        except Exception:
            return None
        return store if isinstance(store, RunStore) else None

    @staticmethod
    def _detail() -> str:
        return "G07 run recording/history service is not installed."

    def list_runs(self, chamber_id: str, *, search: str = "",
                  limit: int = 50) -> RecordPage:
        store = self._store()
        if store is None:
            return RecordPage(False, detail=self._detail())
        try:
            validate_chamber_id(chamber_id)
        except Exception:
            return RecordPage(True, detail="Invalid chamber identifier.")
        try:
            rows = store.list_runs(chamber_id, limit=_bounded_limit(limit))
            needle = bounded_search(search).casefold()
            records = []
            for row in rows:
                record = self._run_record(store, chamber_id, row)
                if needle and needle not in record.run_id.casefold() and (
                        needle not in record.profile_name.casefold()):
                    continue
                records.append(record)
        except (*_READ_ERRORS, KeyError, TypeError, json.JSONDecodeError):
            return RecordPage(False, detail="Run history failed integrity check; retry after review.")
        return RecordPage(True, records=tuple(records[:_MAX_RECORDS]))

    @staticmethod
    def _run_record(store: RunStore, chamber_id: str,
                    row: dict[str, Any]) -> RunRecord:
        # list_runs omits snapshot_json; get_run re-verifies the snapshot
        # digest and returns the immutable provenance this record needs.
        full = store.get_run(chamber_id, row["run_id"])
        snapshot = json.loads(full["snapshot_json"])
        return RunRecord(
            chamber_id=row["chamber_id"],
            run_id=row["run_id"],
            profile_name=str(snapshot.get("profile_name", "")),
            profile_revision=int(snapshot.get("revision", 0)),
            operator=snapshot.get("operator_id") or None,
            started_at_utc=_parse_utc(row["created_at_utc"]),
            ended_at_utc=RunStoreReader._ended_at(store, chamber_id, row),
            outcome=str(row.get("terminal_state") or row["lifecycle"]),
        )

    @staticmethod
    def _ended_at(store: RunStore, chamber_id: str, row: dict[str, Any]) -> datetime | None:
        """Durable end observation: the last journaled event of a final run.

        The runs table stores no separate end timestamp; the terminal event's
        observed time is the only recorded end evidence. Only finalized runs
        are queried, and only for rows actually being returned (bounded).
        """
        lifecycle = row.get("lifecycle")
        event_count = row.get("event_count")
        if lifecycle not in FINAL or not isinstance(event_count, int) or event_count < 1:
            return None
        tail = store.list_events(chamber_id, row["run_id"],
                                 limit=1, after_sequence=event_count - 1)
        if not tail:
            raise RunIntegrityError("Final run has no terminal event")
        return _parse_utc(tail[0]["observed_at_utc"])

    def list_events(self, chamber_id: str, *, severity: str = "ALL",
                    search: str = "", limit: int = 50) -> RecordPage:
        store = self._store()
        if store is None:
            return RecordPage(False, detail=self._detail())
        try:
            validate_chamber_id(chamber_id)
        except Exception:
            return RecordPage(True, detail="Invalid chamber identifier.")
        record_limit = _bounded_limit(limit)
        wanted = str(severity or "ALL").upper()
        needle = bounded_search(search).casefold()
        try:
            runs = store.list_runs(chamber_id, limit=_MAX_RUN_SCAN)
            records: list[EventRecord] = []
            for run in runs:
                event_count = run["event_count"]
                if type(event_count) is not int or event_count < 0:
                    raise RunIntegrityError("Invalid event count")
                # RunStore pages forward by sequence; start near the durable
                # tail so the operational log never substitutes old events for
                # a recent fault on a long-running profile.
                after = max(0, event_count - _MAX_RECORDS)
                rows = store.list_events(
                    chamber_id, run["run_id"], limit=_MAX_RECORDS,
                    after_sequence=after,
                )
                for row in rows:
                    record = self._event_record(row, chamber_id, run["run_id"])
                    if wanted != "ALL" and record.severity != wanted:
                        continue
                    if needle and needle not in record.message.casefold():
                        continue
                    records.append(record)
        except (*_READ_ERRORS, KeyError, TypeError):
            return RecordPage(False, detail="Event log failed integrity check; retry after review.")
        records.sort(
            key=lambda item: (
                item.timestamp_utc,
                item.run_id or "",
                int(item.event_id.rsplit(":", 1)[1]),
            ),
            reverse=True,
        )
        return RecordPage(True, records=tuple(records[:record_limit]))

    @staticmethod
    def _event_record(row: dict[str, Any], chamber_id: str,
                      run_id: str) -> EventRecord:
        kind = str(row["kind"])
        state = str(row["state"])
        step = row.get("step_index")
        return EventRecord(
            event_id=f"{run_id}:{int(row['sequence'])}",
            chamber_id=chamber_id,
            timestamp_utc=_parse_utc(row["observed_at_utc"]),
            severity=_severity(kind, state),
            message=str(row.get("detail") or f"{kind} {state}"),
            operator=None,  # The G06 event carries no per-event principal.
            run_id=run_id,
            step=int(step) if isinstance(step, int) and step >= 0 else None,
        )


def run_record_reader(store_provider) -> RunStoreReader:
    """One adapter serves both the HistoryReader and EventReader protocols."""
    return RunStoreReader(store_provider)
