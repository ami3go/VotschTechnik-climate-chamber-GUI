"""G07-A: durable, vendor-neutral journal for the G06 EventSink protocol.

SQLite is authoritative; CSV and manifest files are reproducible, checksum-
verified exports. All mutating methods are synchronous and must run outside
the NiceGUI event loop. No chamber I/O occurs in this module.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Iterator
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

from chamber_web.domain.chamber import validate_chamber_id


APP_ID = 0x43485237  # CHR7; NOT the G03 profile database.
VERSION = 1
FINAL = frozenset({"COMPLETED", "ABORTED", "FAULT", "INTERRUPTED", "UNKNOWN"})
EVENT_KINDS = frozenset({
    "PREPARED", "START_INTENT", "SETPOINT_INTENT", "STATE",
    "SAMPLE", "STEP_COMPLETED", "STOP_INTENT", "TERMINAL", "RECOVERY",
})

SCHEMA_DDL = (
    "CREATE TABLE runs (run_id TEXT PRIMARY KEY, chamber_id TEXT NOT NULL, "
    "snapshot_json TEXT NOT NULL, snapshot_sha256 TEXT NOT NULL, "
    "created_at_utc TEXT NOT NULL, lifecycle TEXT NOT NULL, "
    "terminal_state TEXT, event_count INTEGER NOT NULL DEFAULT 0, "
    "sample_count INTEGER NOT NULL DEFAULT 0, last_elapsed REAL NOT NULL DEFAULT 0, "
    "last_setpoint REAL, manifest_sha256 TEXT)",
    "CREATE INDEX runs_by_chamber ON runs(chamber_id, created_at_utc DESC)",
    "CREATE TABLE events (run_id TEXT NOT NULL REFERENCES runs(run_id), "
    "sequence INTEGER NOT NULL, kind TEXT NOT NULL, state TEXT NOT NULL, "
    "observed_at_utc TEXT NOT NULL, elapsed_s REAL NOT NULL, "
    "step_index INTEGER NOT NULL, sample_index INTEGER, "
    "temperature_c REAL, quality TEXT, source_sampled_at_utc TEXT, "
    "intended_setpoint_c REAL, detail TEXT NOT NULL, payload_json TEXT NOT NULL, "
    "PRIMARY KEY(run_id,sequence), UNIQUE(run_id,sample_index))",
    "CREATE INDEX events_by_time ON events(run_id,observed_at_utc,sequence)",
    "CREATE INDEX events_by_samples ON events(run_id,sample_index)",
    "CREATE TRIGGER immutable_events_update BEFORE UPDATE ON events "
    "BEGIN SELECT RAISE(ABORT,'run events immutable'); END",
    "CREATE TRIGGER immutable_events_delete BEFORE DELETE ON events "
    "BEGIN SELECT RAISE(ABORT,'run events immutable'); END",
    "CREATE TRIGGER immutable_run_identity BEFORE UPDATE OF "
    "run_id,chamber_id,snapshot_json,snapshot_sha256,created_at_utc ON runs "
    "BEGIN SELECT RAISE(ABORT,'run identity immutable'); END",

)


class RunIntegrityError(RuntimeError):
    """Corrupt journal, conflicting replay or altered run evidence."""


class RunNotFoundError(LookupError):
    """No run with this identifier belongs to the requested chamber."""


def _run_uuid(run_id: str) -> str:
    if not isinstance(run_id, str):
        raise ValueError("Run identifier must be a canonical UUID4")
    try:
        parsed = UUID(run_id)
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("Invalid run identifier") from exc
    if parsed.version != 4 or str(parsed) != run_id:
        raise ValueError("Run identifier must be a canonical UUID4")
    return run_id


def _utc(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("UTC timestamp required")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid UTC timestamp") from exc
    if stamp.tzinfo is None or stamp.utcoffset().total_seconds() != 0:
        raise ValueError("UTC timestamp with timezone required")
    return stamp.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _encode(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Non-finite profile snapshot decimal")
        return str(value)  # lossless G03 canonical decimal representation
    if is_dataclass(value) and not isinstance(value, type):
        return _encode(asdict(value))
    if isinstance(value, dict):
        return {str(key): _encode(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_encode(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _json(value: Any) -> str:
    return json.dumps(_encode(value), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _positive_limit(value: int, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"Limit must be between 1 and {maximum}")
    return value


def _nonnegative(value: int) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("Offset/index must be a nonnegative integer")
    return value


def _safe_cell(value: Any) -> Any:
    """Protect spreadsheet users from formulas in untrusted diagnostic detail."""
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


class RunStore:
    """Single-deployment journal; independent SQLite DB, keyed by chamber/run.

    Per-event FULL synchronous SQLite transactions are the durability boundary
    before every controller mutation. Bulk replay/import is explicit and bounded
    to 1000 events per transaction; the G06 synchronous sink never buffers intents.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.data = self.root / "data"
        self.data.mkdir(parents=True, exist_ok=True)
        self.database = self.data / "runs.sqlite3"
        # A missing SQLite file alongside surviving run evidence is data loss,
        # not a clean installation. sqlite3.connect would otherwise create an
        # empty journal and silently hide interrupted or completed runs.
        # Check before the first SQLite connection (which can create the file).
        if not self.database.is_file() and (
            (self.data / "chambers").exists()
            or any((self.data / ("runs.sqlite3" + ext)).exists()
                   for ext in ("-journal", "-wal", "-shm"))
        ):
            raise RunIntegrityError(
                "Run SQLite database missing with surviving evidence; restore from backup"
            )
        # Check existing SQLite pages before accepting control-run evidence. A
        # corrupt journal is a startup NO-GO, never a request to recreate it.
        # quick_check is structural, not a substitute for site backup/restore.
        try:
            with self._read() as check:
                result = check.execute("PRAGMA quick_check(1)").fetchone()
                if result is None or result[0] != "ok":
                    raise RunIntegrityError("Run journal SQLite integrity check failed")
        except sqlite3.DatabaseError as exc:
            raise RunIntegrityError("Corrupted/unreadable run journal; startup refused") from exc
        with self._write() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            app = db.execute("PRAGMA application_id").fetchone()[0]
            if version == 0 and app == 0:
                objects = db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1"
                ).fetchone()
                if objects:
                    raise RunIntegrityError("Unrecognized nonempty run database")
                for ddl in SCHEMA_DDL:
                    db.execute(ddl)
                db.execute(f"PRAGMA application_id={APP_ID}")
                db.execute(f"PRAGMA user_version={VERSION}")
            elif version != VERSION or app != APP_ID:
                raise RunIntegrityError("Unsupported run database version/application ID")
            # Verify the *definitions*, not merely names: missing CHECK/PK/UNIQUE
            # or replaced no-op immutability triggers are unacceptable.
            def definitions(connection: sqlite3.Connection) -> dict[str, tuple[str, str, str]]:
                return {row[0]: (row[1], row[2], row[3]) for row in connection.execute(
                    "SELECT name,type,tbl_name,sql FROM sqlite_master "
                    "WHERE name NOT LIKE 'sqlite_%'"
                )}
            expected_db = sqlite3.connect(":memory:")
            try:
                for ddl in SCHEMA_DDL:
                    expected_db.execute(ddl)
                if definitions(db) != definitions(expected_db):
                    raise RunIntegrityError("Unrecognized or weakened run journal schema")
            finally:
                expected_db.close()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.database), timeout=10, isolation_level=None)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=10000")
            db.execute("PRAGMA synchronous=FULL")
            return db
        except BaseException:
            # Failed PRAGMA setup (including corrupt SQLite headers) must not
            # leak an open Windows file handle or prevent safe recovery.
            db.close()
            raise

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        db = self._connect()
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._read() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def _directory(self, chamber_id: str, run_id: str) -> Path:
        validate_chamber_id(chamber_id)
        _run_uuid(run_id)
        path = self.data / "chambers" / chamber_id / "runs" / run_id
        if not path.resolve().is_relative_to(self.data.resolve()):
            raise RunIntegrityError("Run artifact directory escapes data root")
        return path

    @staticmethod
    def _find(db: sqlite3.Connection, chamber_id: str, run_id: str) -> sqlite3.Row:
        row = db.execute("SELECT * FROM runs WHERE chamber_id=? AND run_id=?",
                         (chamber_id, run_id)).fetchone()
        if row is None:
            raise RunNotFoundError("Run not found for chamber")
        if _hash(row["snapshot_json"].encode("utf-8")) != row["snapshot_sha256"]:
            raise RunIntegrityError("Execution snapshot digest mismatch")
        return row

    def prepare(self, snapshot: Any) -> None:
        """Commit immutable PREPARED evidence before any G04 mutation."""
        run_id = _run_uuid(snapshot.run_id)
        chamber_id = validate_chamber_id(snapshot.chamber_id)
        value = _encode(snapshot)
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise ValueError("Unsupported execution snapshot schema")
        if not isinstance(value.get("identity"), dict) or value["identity"].get("chamber_id") != chamber_id:
            raise RunIntegrityError("Execution identity belongs to another chamber")
        if type(value.get("controller_generation")) is not int or value["controller_generation"] < 0:
            raise ValueError("Invalid controller generation")
        created = _utc(value["created_at_utc"])
        value["created_at_utc"] = created
        payload = _json(value)
        if len(payload.encode("utf-8")) > 1024 * 1024:
            raise ValueError("Snapshot exceeds 1 MiB")
        with self._write() as db:
            previous = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if previous is not None:
                if (previous["chamber_id"] == chamber_id and
                        previous["snapshot_json"] == payload and
                        previous["lifecycle"] == "PREPARED" and
                        previous["event_count"] <= 1):
                    return  # idempotent preparation ONLY before any command-intent
                raise RunIntegrityError("Conflicting immutable snapshot or chamber")
            db.execute(
                "INSERT INTO runs(run_id,chamber_id,snapshot_json,snapshot_sha256,"
                "created_at_utc,lifecycle) VALUES(?,?,?,?,?,?)",
                (run_id, chamber_id, payload, _hash(payload.encode()), created, "PREPARED"),
            )
        # If this fails, caller MUST NOT issue hardware commands.
        self._directory(chamber_id, run_id).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _event(event: Any) -> dict[str, Any]:
        value = _encode(event)
        if not isinstance(value, dict):
            raise ValueError("RunEvent must be a structured object")
        if value.get("kind") not in EVENT_KINDS:
            raise ValueError("Unknown run event kind")
        _run_uuid(value["run_id"])
        validate_chamber_id(value["chamber_id"])
        if type(value.get("sequence")) is not int or value["sequence"] < 1:
            raise ValueError("Event sequence must be positive")
        if type(value.get("step_index")) is not int or value["step_index"] < 0:
            raise ValueError("Invalid step index")
        elapsed = value.get("monotonic_elapsed_s")
        if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or (
            not math.isfinite(elapsed) or elapsed < 0
        ):
            raise ValueError("Invalid monotonic elapsed time")
        value["observed_at_utc"] = _utc(value["observed_at_utc"])
        if value["kind"] == "SAMPLE":
            if type(value.get("sample_index")) is not int or value["sample_index"] < 1:
                raise ValueError("SAMPLE requires positive sample_index")
            value["source_sampled_at_utc"] = _utc(value["source_sampled_at_utc"])
        elif value.get("sample_index") is not None:
            raise ValueError("Non-sample event cannot have sample_index")
        if value.get("temperature_c") is not None:
            temperature = value["temperature_c"]
            if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not math.isfinite(temperature):
                raise ValueError("Invalid event temperature")
        if not isinstance(value.get("detail", ""), str) or len(value.get("detail", "")) > 8192:
            raise ValueError("Invalid or oversized diagnostic")
        return value

    @staticmethod
    def _append(db: sqlite3.Connection, value: dict[str, Any]) -> bool:
        run = RunStore._find(db, value["chamber_id"], value["run_id"])
        sequence = value["sequence"]
        payload = _json(value)
        if sequence <= run["event_count"]:
            prior = db.execute(
                "SELECT payload_json FROM events WHERE run_id=? AND sequence=?",
                (value["run_id"], sequence),
            ).fetchone()
            if prior is not None and prior[0] == payload:
                return False
            raise RunIntegrityError("Conflicting duplicate event")
        if sequence != run["event_count"] + 1:
            raise RunIntegrityError("Missing event sequence")
        if run["terminal_state"] is not None or run["lifecycle"] == "FINALIZING":
            raise RunIntegrityError("Run already finalized")
        elapsed = float(value["monotonic_elapsed_s"])
        if elapsed < run["last_elapsed"]:
            raise RunIntegrityError("Monotonic elapsed time decreased")
        kind = value["kind"]
        sample_index = value.get("sample_index")
        if kind == "SAMPLE" and sample_index != run["sample_count"] + 1:
            raise RunIntegrityError("Sample index must be exactly increasing")
        if kind == "PREPARED" and sequence != 1:
            raise RunIntegrityError("PREPARED must be the first event")
        if sequence == 1 and kind not in ("PREPARED", "RECOVERY"):
            raise RunIntegrityError("Missing PREPARED event")
        if kind == "RECOVERY" and run["lifecycle"] != "PREPARED" and sequence == 1:
            raise RunIntegrityError("Recovery without a prepared snapshot")
        if kind == "START_INTENT" and run["lifecycle"] != "PREPARED":
            raise RunIntegrityError("START_INTENT replay/late delivery")
        if kind == "SETPOINT_INTENT" and run["lifecycle"] not in {"START_INTENT", "RUNNING"}:
            raise RunIntegrityError("Setpoint without durable START_INTENT")
        if kind == "SAMPLE" and run["lifecycle"] not in {"START_INTENT", "RUNNING", "STOP_INTENT"}:
            raise RunIntegrityError("Sample before START_INTENT")
        if kind == "STEP_COMPLETED" and run["lifecycle"] not in {"RUNNING", "STOP_INTENT"}:
            raise RunIntegrityError("Step completion before execution")
        if kind == "STATE" and run["lifecycle"] == "PREPARED" and value["state"] != "PREPARING":
            raise RunIntegrityError("Running state without START_INTENT")
        if kind == "TERMINAL":
            if run["lifecycle"] != "STOP_INTENT":
                raise RunIntegrityError("TERMINAL requires committed STOP_INTENT")
            terminal = {"COMPLETED": "COMPLETED", "CANCELLED": "ABORTED",
                        "FAULT": "FAULT", "UNKNOWN": "UNKNOWN"}.get(value["state"])
            if terminal is None:
                raise RunIntegrityError("Invalid terminal state")
            lifecycle = "FINALIZING"
        elif kind == "STOP_INTENT":
            lifecycle = "STOP_INTENT"
            terminal = None
        elif kind == "START_INTENT":
            lifecycle = "START_INTENT"
            terminal = None
        elif kind == "STATE" and run["lifecycle"] in ("START_INTENT", "RUNNING"):
            lifecycle = "RUNNING"
            terminal = None
        else:
            lifecycle = run["lifecycle"]
            terminal = None
        setpoint = (float(value["temperature_c"]) if kind == "SETPOINT_INTENT"
                    else run["last_setpoint"])
        db.execute(
            "INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (value["run_id"], sequence, kind, value["state"],
             value["observed_at_utc"], elapsed, value["step_index"],
             sample_index, value.get("temperature_c"), value.get("quality"),
             value.get("source_sampled_at_utc"), setpoint,
             value.get("detail", ""), payload),
        )
        db.execute(
            "UPDATE runs SET lifecycle=?,terminal_state=?,event_count=?,"
            "sample_count=?,last_elapsed=?,last_setpoint=? WHERE run_id=?",
            (lifecycle, terminal, sequence,
             run["sample_count"] + (kind == "SAMPLE"), elapsed, setpoint,
             value["run_id"]),
        )
        return True

    def emit(self, event: Any) -> None:
        value = self._event(event)
        with self._write() as db:
            inserted = self._append(db, value)
        if value["kind"] == "TERMINAL":
            # Duplicate terminal delivery after ENOSPC must retry a committed
            # FINALIZING journal, without altering immutable event evidence.
            if inserted or self.get_run(value["chamber_id"], value["run_id"])["lifecycle"] == "FINALIZING":
                self._finalize(value["chamber_id"], value["run_id"])

    def emit_batch(self, events: Iterable[Any]) -> int:
        """Bounded bulk test/import API; G06 uses synchronous emit() for intents.

        Every batch commits as one transaction; maximum 1000 objects per batch.
        """
        values = [self._event(event) for event in events]
        if len(values) > 1000:
            raise ValueError("Batch exceeds 1000 events")
        if any(item["kind"] == "TERMINAL" for item in values):
            raise ValueError("Terminal events require synchronous emit()")
        with self._write() as db:
            return sum(self._append(db, item) for item in values)

    def get_run(self, chamber_id: str, run_id: str) -> dict[str, Any]:
        self._directory(chamber_id, run_id)
        with self._read() as db:
            return dict(self._find(db, chamber_id, run_id))

    def list_runs(self, chamber_id: str, *, limit: int = 100, offset: int = 0,
                  since_utc: str | None = None, until_utc: str | None = None) -> list[dict[str, Any]]:
        validate_chamber_id(chamber_id)
        _positive_limit(limit, 200)
        _nonnegative(offset)
        start = _utc(since_utc) if since_utc is not None else ""
        end = _utc(until_utc) if until_utc is not None else "9999-12-31T23:59:59+00:00"
        with self._read() as db:
            return [dict(row) for row in db.execute(
                "SELECT run_id,chamber_id,created_at_utc,lifecycle,terminal_state,"
                "event_count,sample_count,manifest_sha256 FROM runs "
                "WHERE chamber_id=? AND created_at_utc>=? AND created_at_utc<=? "
                "ORDER BY created_at_utc DESC,run_id DESC LIMIT ? OFFSET ?",
                (chamber_id, start, end, limit, offset),
            )]

    def list_events(self, chamber_id: str, run_id: str, *, limit: int = 100,
                    after_sequence: int = 0, since_utc: str | None = None,
                    until_utc: str | None = None) -> list[dict[str, Any]]:
        self._directory(chamber_id, run_id)
        _positive_limit(limit, 500)
        _nonnegative(after_sequence)
        start = _utc(since_utc) if since_utc is not None else ""
        end = _utc(until_utc) if until_utc is not None else "9999-12-31T23:59:59+00:00"
        with self._read() as db:
            self._find(db, chamber_id, run_id)
            return [dict(row) for row in db.execute(
                "SELECT sequence,kind,state,observed_at_utc,elapsed_s,"
                "step_index,sample_index,temperature_c,quality,source_sampled_at_utc,"
                "intended_setpoint_c,detail FROM events WHERE run_id=? "
                "AND sequence>? AND observed_at_utc>=? AND observed_at_utc<=? "
                "ORDER BY sequence LIMIT ?",
                (run_id, after_sequence, start, end, limit),
            )]

    def plot_samples(self, chamber_id: str, run_id: str, *, limit: int = 1000,
                     first_sample: int = 1, last_sample: int | None = None) -> list[dict[str, Any]]:
        self._directory(chamber_id, run_id)
        _positive_limit(limit, 5000)
        if type(first_sample) is not int or first_sample < 1:
            raise ValueError("First sample must be positive")
        with self._read() as db:
            run = self._find(db, chamber_id, run_id)
            last = run["sample_count"] if last_sample is None else last_sample
            if type(last) is not int or last < first_sample:
                raise ValueError("Invalid last sample")
            stride = max(1, (last - first_sample + 1 + limit - 1) // limit)
            return [dict(row) for row in db.execute(
                "SELECT sample_index,observed_at_utc,source_sampled_at_utc,"
                "elapsed_s,step_index,temperature_c,intended_setpoint_c,quality,"
                "state FROM events WHERE run_id=? AND sample_index>=? "
                "AND sample_index<=? AND (sample_index-?)%?=0 "
                "ORDER BY sample_index LIMIT ?",
                (run_id, first_sample, last, first_sample, stride, limit),
            )]

    @staticmethod
    def _sync_parent(path: Path) -> None:
        # Windows does not reliably support opening directories for fsync.
        if os.name == "nt":
            return
        fd = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def _atomic_file(path: Path, produce: Any) -> str:
        """Write/fsync temporary file, rename, then sync containing directory.

        Existing final evidence is immutable: mismatches are corruption, not
        permission to overwrite. Crash-left temporary files are nonauthoritative.
        """
        fd, name = tempfile.mkstemp(prefix=".partial-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                produce(stream)
                stream.flush()
                os.fsync(stream.fileno())
            digest = hashlib.sha256()
            with open(name, "rb") as inp:
                for chunk in iter(lambda: inp.read(1024 * 1024), b""):
                    digest.update(chunk)
            expected = digest.hexdigest()
            if path.exists():
                if RunStore._digest_file(path) != expected:
                    raise RunIntegrityError("Existing immutable artifact conflicts")
                return expected
            os.replace(name, path)
            RunStore._sync_parent(path.parent)
            return expected
        finally:
            if os.path.exists(name):
                os.unlink(name)

    @staticmethod
    def _digest_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _csv(stream: Any, headings: tuple[str, ...], rows: Iterable[tuple[Any, ...]]) -> None:
        wrapper = io.TextIOWrapper(stream, encoding="utf-8", newline="", write_through=True)
        try:
            writer = csv.writer(wrapper, lineterminator="\n")
            writer.writerow(headings)
            for row in rows:
                writer.writerow([_safe_cell(cell) for cell in row])
            wrapper.flush()
        finally:
            wrapper.detach()  # Caller still owns the binary fd.

    def _finalize(self, chamber_id: str, run_id: str) -> None:
        path = self._directory(chamber_id, run_id)
        path.mkdir(parents=True, exist_ok=True)
        with self._read() as db:
            run = self._find(db, chamber_id, run_id)
            if run["lifecycle"] != "FINALIZING" or run["terminal_state"] not in FINAL:
                raise RunIntegrityError("Only fully journaled terminal runs can finalize")
            columns = ("sequence", "kind", "state", "observed_at_utc", "elapsed_s",
                       "step_index", "sample_index", "temperature_c", "quality",
                       "source_sampled_at_utc", "intended_setpoint_c", "detail")
            def event_rows() -> Iterator[tuple[Any, ...]]:
                for row in db.execute("SELECT " + ",".join(columns) +
                                      " FROM events WHERE run_id=? ORDER BY sequence", (run_id,)):
                    yield tuple(row)
            snapshot_sha = self._atomic_file(
                path / "snapshot.json",
                lambda stream: stream.write(run["snapshot_json"].encode("utf-8")),
            )
            if snapshot_sha != run["snapshot_sha256"]:
                raise RunIntegrityError("Exported immutable snapshot digest mismatch")
            ev_sha = self._atomic_file(path / "events.csv", lambda f: self._csv(f, columns, event_rows()))
            sample_cols = ("sample_index", "sequence", "observed_at_utc",
                           "source_sampled_at_utc", "elapsed_s", "step_index",
                           "temperature_c", "intended_setpoint_c", "quality", "state")
            def sample_rows() -> Iterator[tuple[Any, ...]]:
                for row in db.execute(
                    "SELECT " + ",".join(sample_cols) + " FROM events "
                    "WHERE run_id=? AND kind='SAMPLE' ORDER BY sample_index", (run_id,)
                ):
                    yield tuple(row)
            sample_sha = self._atomic_file(
                path / "samples.csv", lambda f: self._csv(f, sample_cols, sample_rows())
            )
            manifest = {
                "schema_version": VERSION, "run_id": run_id, "chamber_id": chamber_id,
                "snapshot_sha256": run["snapshot_sha256"],
                "terminal_state": run["terminal_state"], "event_count": run["event_count"],
                "sample_count": run["sample_count"], "controller_generation":
                json.loads(run["snapshot_json"])["controller_generation"],
                "artifacts": {"snapshot.json": snapshot_sha, "events.csv": ev_sha, "samples.csv": sample_sha},
            }
            manifest_bytes = (_json(manifest) + "\n").encode("utf-8")
            manifest_sha = self._atomic_file(
                path / "manifest.json", lambda stream: stream.write(manifest_bytes)
            )
        with self._write() as db:
            run = self._find(db, chamber_id, run_id)
            if run["lifecycle"] != "FINALIZING":
                raise RunIntegrityError("Run finalization raced")
            db.execute("UPDATE runs SET lifecycle=?,manifest_sha256=? WHERE run_id=?",
                       (run["terminal_state"], manifest_sha, run_id))

    def verify_artifacts(self, chamber_id: str, run_id: str) -> dict[str, Any]:
        path = self._directory(chamber_id, run_id)
        run = self.get_run(chamber_id, run_id)
        if run["lifecycle"] not in FINAL or run["manifest_sha256"] is None:
            raise RunIntegrityError("Run is not finalized")
        manifest_path = path / "manifest.json"
        if not manifest_path.is_file() or self._digest_file(manifest_path) != run["manifest_sha256"]:
            raise RunIntegrityError("Manifest missing or altered")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise RunIntegrityError("Invalid manifest") from exc
        if not isinstance(manifest, dict) or not isinstance(manifest.get("artifacts"), dict):
            raise RunIntegrityError("Invalid manifest structure")
        if (set(manifest) != {"schema_version", "run_id", "chamber_id",
                              "snapshot_sha256", "terminal_state", "event_count",
                              "sample_count", "controller_generation", "artifacts"} or
            manifest["run_id"] != run_id or manifest["chamber_id"] != chamber_id or
            manifest["snapshot_sha256"] != run["snapshot_sha256"] or
            manifest["terminal_state"] != run["terminal_state"] or
            manifest["event_count"] != run["event_count"] or
            manifest["sample_count"] != run["sample_count"] or
            manifest["controller_generation"] != json.loads(run["snapshot_json"])["controller_generation"] or
            set(manifest["artifacts"]) != {"snapshot.json", "events.csv", "samples.csv"} or
            manifest["artifacts"].get("snapshot.json") != run["snapshot_sha256"]):
            raise RunIntegrityError("Manifest journal mismatch")
        for name, expected in manifest["artifacts"].items():
            artifact = path / name
            if not artifact.is_file() or self._digest_file(artifact) != expected:
                raise RunIntegrityError("Missing or corrupted run artifact")
        return manifest

    def read_csv(self, chamber_id: str, run_id: str, *, name: str,
                 max_bytes: int = 16 * 1024 * 1024) -> bytes:
        if name not in {"events.csv", "samples.csv"}:
            raise ValueError("Export filename not permitted")
        _positive_limit(max_bytes, 128 * 1024 * 1024)
        self.verify_artifacts(chamber_id, run_id)
        path = self._directory(chamber_id, run_id) / name
        if path.stat().st_size > max_bytes:
            raise ValueError("CSV exceeds bounded download size")
        return path.read_bytes()

    def read_zip(self, chamber_id: str, run_id: str, *,
                 max_bytes: int = 32 * 1024 * 1024) -> bytes:
        _positive_limit(max_bytes, 128 * 1024 * 1024)
        self.verify_artifacts(chamber_id, run_id)
        path = self._directory(chamber_id, run_id)
        names = ("manifest.json", "snapshot.json", "events.csv", "samples.csv")
        if sum((path / name).stat().st_size for name in names) > max_bytes:
            raise ValueError("Evidence exceeds bounded ZIP size")
        output = io.BytesIO()
        with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=6) as zip_file:
            for name in names:
                zip_file.write(path / name, arcname=name)
        if output.tell() > max_bytes:
            raise ValueError("ZIP exceeds bounded download size")
        return output.getvalue()

    def reconcile_startup(self) -> list[tuple[str, str, str]]:
        """Offline, once at exclusive service startup; NEVER dispatch G04 commands.

        PREPARED-only => INTERRUPTED. Any started-but-unfinalized run =>
        UNKNOWN, not a claim of physical STOP. FINALIZING with a committed
        TERMINAL event can re-create materialized artifacts without new I/O.
        """
        with self._read() as db:
            pending = [(row["chamber_id"], row["run_id"], row["lifecycle"])
                       for row in db.execute(
                           "SELECT chamber_id,run_id,lifecycle FROM runs WHERE "
                           "lifecycle NOT IN ('COMPLETED','ABORTED','FAULT','INTERRUPTED','UNKNOWN')"
                       )]
        result = []
        for chamber_id, run_id, lifecycle in pending:
            if lifecycle == "FINALIZING":
                # Committed G06 TERMINAL evidence already exists; only redo exports.
                self._finalize(chamber_id, run_id)
                result.append((chamber_id, run_id, self.get_run(chamber_id, run_id)["lifecycle"]))
                continue
            state = "INTERRUPTED" if lifecycle == "PREPARED" else "UNKNOWN"
            with self._write() as db:
                run = self._find(db, chamber_id, run_id)
                sequence = run["event_count"] + 1
                event = {
                    "run_id": run_id, "chamber_id": chamber_id,
                    "sequence": sequence, "kind": "RECOVERY", "state": state,
                    "monotonic_elapsed_s": run["last_elapsed"], "step_index": 0,
                    "detail": "Process exited without durable terminal evidence; chamber state NOT verified",
                    "temperature_c": None, "quality": None,
                    "observed_at_utc": _now(), "source_sampled_at_utc": None,
                    "sample_index": None,
                }
                self._append(db, self._event(event))
                db.execute("UPDATE runs SET lifecycle='FINALIZING',terminal_state=? WHERE run_id=?",
                           (state, run_id))
            self._finalize(chamber_id, run_id)
            result.append((chamber_id, run_id, state))
        return result


class RunRecorder:
    """G06 EventSink adapter; server composition supplies one per deployment."""

    def __init__(self, store: RunStore):
        self.store = store

    def prepare(self, snapshot: Any) -> None:
        self.store.prepare(snapshot)

    def emit(self, event: Any) -> None:
        self.store.emit(event)
