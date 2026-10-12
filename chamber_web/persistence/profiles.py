"""G03-B SQLite profile revisions, isolated by stable chamber_id.

This stores canonical ZIPs (including original legacy CSV bytes), not flattened
steps. Revisions are append-only; all imports and head changes are transactional.
No hardware commands, browser sessions, or simulated run state live here.
"""
from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterator
from uuid import UUID, uuid4
from zipfile import BadZipFile

from chamber_web.domain.chamber import validate_chamber_id
from chamber_web.domain.profile import (
    ParsedProfile, export_profile_csv, export_profile_zip,
    import_profile_zip, parse_profile_csv,
)

_SCHEMA_VERSION = 1
_APP_ID = 0x43484231  # CHB1, distinct from an arbitrary SQLite database
_ALLOWED_SOURCES = frozenset({"editor", "csv", "legacy_csv", "zip"})


class ProfileSchemaError(RuntimeError):
    """Unknown or inconsistent database schema: never migrate implicitly."""


class ProfileNotFoundError(LookupError):
    """Missing profile or one belonging to a different chamber."""


class ProfileConflictError(RuntimeError):
    """Revision changed since the editor fetched it; no lost-update write."""


@dataclass(frozen=True)
class ProfileHeader:
    chamber_id: str
    profile_id: str
    current_revision: int
    name: str
    created_at_utc: str
    updated_at_utc: str


@dataclass(frozen=True)
class ProfileRevision:
    header: ProfileHeader
    revision: int
    saved_at_utc: str
    source_format: str
    sha256: str
    profile: ParsedProfile
    archive: bytes


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _profile_id(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Invalid profile ID")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError("Invalid profile ID") from exc
    if str(parsed) != value:
        raise ValueError("Profile ID must be canonical UUID")
    return value


def _source(value: str) -> str:
    if value not in _ALLOWED_SOURCES:
        raise ValueError("Unknown profile import source")
    return value


def _archive(profile: ParsedProfile) -> tuple[bytes, str]:
    data = export_profile_zip(profile)
    # Validation must also cover fields from manually constructed ParsedProfile.
    if import_profile_zip(data) != profile:
        raise ValueError("Profile failed canonical round-trip validation")
    return data, hashlib.sha256(data).hexdigest()


class ProfileStore:
    """One SQLite file; each call opens its own connection, writes use BEGIN IMMEDIATE.

    Schema creation is explicit and fail-closed on unrecognized/nonempty files.
    This is profile metadata only; G07 owns run journals and crash reconciliation.
    """

    def __init__(self, database_path: str | Path):
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            app_id = connection.execute("PRAGMA application_id").fetchone()[0]
            if version == 0 and app_id == 0:
                existing = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table','view','trigger','index') "
                    "AND name NOT LIKE 'sqlite_%'"
                ).fetchone()
                if existing:
                    raise ProfileSchemaError("Unversioned nonempty database: refusing overwrite")
                self._create_schema(connection)
            elif version != _SCHEMA_VERSION or app_id != _APP_ID:
                raise ProfileSchemaError("Unsupported profile database version or application ID")
            self._verify_schema(connection)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _create_schema(db: sqlite3.Connection) -> None:
        # executescript() would commit the surrounding transaction implicitly.
        # Each DDL statement is executed individually so bootstrap is atomic.
        statements = (
            "CREATE TABLE profiles ("
            "profile_id TEXT PRIMARY KEY, chamber_id TEXT NOT NULL, "
            "name TEXT NOT NULL, current_revision INTEGER NOT NULL "
            "CHECK(current_revision >= 1), created_at_utc TEXT NOT NULL, "
            "updated_at_utc TEXT NOT NULL)",
            "CREATE INDEX profiles_by_chamber ON profiles(chamber_id, updated_at_utc)",
            "CREATE TABLE profile_revisions ("
            "profile_id TEXT NOT NULL REFERENCES profiles(profile_id), "
            "revision INTEGER NOT NULL CHECK(revision >= 1), "
            "saved_at_utc TEXT NOT NULL, source_format TEXT NOT NULL, "
            "archive BLOB NOT NULL, archive_sha256 TEXT NOT NULL, "
            "PRIMARY KEY (profile_id, revision))",
            "CREATE TRIGGER revision_no_update BEFORE UPDATE ON profile_revisions "
            "BEGIN SELECT RAISE(ABORT, 'profile revisions are immutable'); END",
            "CREATE TRIGGER revision_no_delete BEFORE DELETE ON profile_revisions "
            "BEGIN SELECT RAISE(ABORT, 'profile revisions are immutable'); END",
        )
        for statement in statements:
            db.execute(statement)
        db.execute(f"PRAGMA application_id={_APP_ID}")
        db.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")

    @staticmethod
    def _verify_schema(db: sqlite3.Connection) -> None:
        expected = {
            "profiles": {"profile_id", "chamber_id", "name", "current_revision",
                         "created_at_utc", "updated_at_utc"},
            "profile_revisions": {"profile_id", "revision", "saved_at_utc",
                                  "source_format", "archive", "archive_sha256"},
        }
        for table, columns in expected.items():
            actual = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            if not columns.issubset(actual):
                raise ProfileSchemaError(f"Missing or incompatible {table} table")
        triggers = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        )}
        if not {"revision_no_update", "revision_no_delete"}.issubset(triggers):
            raise ProfileSchemaError("Immutable revision triggers missing")

    @staticmethod
    def _header(row: sqlite3.Row) -> ProfileHeader:
        return ProfileHeader(row["chamber_id"], row["profile_id"],
                             row["current_revision"], row["name"],
                             row["created_at_utc"], row["updated_at_utc"])

    @staticmethod
    def _find(db: sqlite3.Connection, chamber_id: str, profile_id: str) -> sqlite3.Row:
        row = db.execute(
            "SELECT * FROM profiles WHERE chamber_id=? AND profile_id=?",
            (chamber_id, profile_id),
        ).fetchone()
        if row is None:
            raise ProfileNotFoundError("Profile not found for chamber")
        return row

    def create_profile(self, chamber_id: str, profile: ParsedProfile, *,
                       source_format: str = "editor") -> ProfileHeader:
        validate_chamber_id(chamber_id)
        _source(source_format)
        archive, digest = _archive(profile)  # All validation before transaction.
        profile_id, now = str(uuid4()), _utc_now()
        with self._transaction() as db:
            db.execute(
                "INSERT INTO profiles VALUES (?,?,?,?,?,?)",
                (profile_id, chamber_id, profile.name, 1, now, now),
            )
            db.execute(
                "INSERT INTO profile_revisions VALUES (?,?,?,?,?,?)",
                (profile_id, 1, now, source_format, archive, digest),
            )
            return self._header(self._find(db, chamber_id, profile_id))

    def import_profile(self, chamber_id: str, content: bytes, *, filename: str,
                       legacy_reach_timeout_s: Decimal | None = None) -> ProfileHeader:
        """Parse entirely before committing. Legacy bytes survive in canonical ZIP."""
        if not isinstance(filename, str):
            raise ValueError("Profile filename required")
        if filename.lower().endswith(".zip"):
            try:
                profile = import_profile_zip(content)
            except BadZipFile as exc:
                raise ValueError("Invalid profile ZIP archive") from exc
            source = "zip"
        elif filename.lower().endswith(".csv"):
            profile = parse_profile_csv(
                content, legacy_reach_timeout_s=legacy_reach_timeout_s
            )
            source = "legacy_csv" if profile.legacy_original is not None else "csv"
        else:
            raise ValueError("Only .csv and .zip profiles can be imported")
        return self.create_profile(chamber_id, profile, source_format=source)

    def save_revision(self, chamber_id: str, profile_id: str,
                      profile: ParsedProfile, *, expected_revision: int) -> ProfileHeader:
        validate_chamber_id(chamber_id)
        _profile_id(profile_id)
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("Expected revision must be a positive integer")
        archive, digest = _archive(profile)
        with self._transaction() as db:
            old = self._find(db, chamber_id, profile_id)
            if old["current_revision"] != expected_revision:
                raise ProfileConflictError("Profile was modified by another editor")
            revision, now = expected_revision + 1, _utc_now()
            db.execute(
                "INSERT INTO profile_revisions VALUES (?,?,?,?,?,?)",
                (profile_id, revision, now, "editor", archive, digest),
            )
            db.execute(
                "UPDATE profiles SET current_revision=?, name=?, updated_at_utc=? "
                "WHERE profile_id=? AND chamber_id=? AND current_revision=?",
                (revision, profile.name, now, profile_id, chamber_id, expected_revision),
            )
            if db.execute("SELECT changes()").fetchone()[0] != 1:
                raise ProfileConflictError("Profile revision changed during update")
            return self._header(self._find(db, chamber_id, profile_id))

    def list_profiles(self, chamber_id: str, *, limit: int = 100,
                      offset: int = 0) -> tuple[ProfileHeader, ...]:
        validate_chamber_id(chamber_id)
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("Profile list limit must be 1..200")
        if type(offset) is not int or offset < 0:
            raise ValueError("Profile list offset must be nonnegative")
        with self._read() as db:
            return tuple(self._header(row) for row in db.execute(
                "SELECT * FROM profiles WHERE chamber_id=? "
                "ORDER BY updated_at_utc DESC, profile_id DESC LIMIT ? OFFSET ?",
                (chamber_id, limit, offset),
            ))

    def get_revision(self, chamber_id: str, profile_id: str, *,
                     revision: int | None = None) -> ProfileRevision:
        validate_chamber_id(chamber_id)
        _profile_id(profile_id)
        if revision is not None and (type(revision) is not int or revision < 1):
            raise ValueError("Revision must be a positive integer")
        with self._read() as db:
            header = self._header(self._find(db, chamber_id, profile_id))
            rev = revision if revision is not None else header.current_revision
            row = db.execute(
                "SELECT * FROM profile_revisions WHERE profile_id=? AND revision=?",
                (profile_id, rev),
            ).fetchone()
            if row is None:
                raise ProfileNotFoundError("Profile revision not found")
            data = bytes(row["archive"])
            digest = hashlib.sha256(data).hexdigest()
            if digest != row["archive_sha256"]:
                raise ProfileSchemaError("Profile archive checksum mismatch")
            try:
                profile = import_profile_zip(data)
            except (ValueError, TypeError, KeyError, OSError, BadZipFile) as exc:
                raise ProfileSchemaError("Stored profile archive invalid") from exc
            return ProfileRevision(header, rev, row["saved_at_utc"],
                                   row["source_format"], digest, profile, data)

    def export_revision_zip(self, chamber_id: str, profile_id: str, *,
                            revision: int | None = None) -> bytes:
        record = self.get_revision(chamber_id, profile_id, revision=revision)
        return record.archive

    def export_revision_csv(self, chamber_id: str, profile_id: str, *,
                            revision: int | None = None,
                            spreadsheet_safe: bool = False) -> bytes:
        record = self.get_revision(chamber_id, profile_id, revision=revision)
        return export_profile_csv(record.profile, spreadsheet_safe=spreadsheet_safe)
