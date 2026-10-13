"""Bounded HMAC-chained local audit ledger with one-time legacy migration.

Tamper-evident if the database is altered without access to the separately
protected key. A privileged attacker controlling BOTH key and database can
rewrite evidence; external sealed exports are needed for stronger assurance.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3


class AuditIntegrityError(RuntimeError):
    """Audit continuity failed: operations must fail closed."""


class AuditLedger:
    def __init__(self, directory: Path, *, max_rows: int = 10000):
        if not 100 <= max_rows <= 1000000:
            raise ValueError("Audit retention outside 100..1000000 rows")
        self.max_rows = max_rows
        self.key_path = Path(directory) / "audit_hmac_key"
        self.key: bytes | None = None

    def initialize(self, db: sqlite3.Connection) -> None:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS audit_chain (
                sequence INTEGER PRIMARY KEY REFERENCES audit(sequence)
                    ON DELETE CASCADE,
                mac TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_anchor (
                id INTEGER PRIMARY KEY CHECK(id=1),
                last_pruned INTEGER NOT NULL,
                mac TEXT NOT NULL
            );
        """)
        existing = db.execute("SELECT count(*) FROM audit_chain").fetchone()[0]
        if self.key_path.is_symlink():
            raise AuditIntegrityError("Audit key symlink forbidden")
        if not self.key_path.exists():
            if existing:
                raise AuditIntegrityError("Existing audit ledger key missing")
            try:
                fd = os.open(self.key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                             0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, "wb") as output:
                    output.write(secrets.token_bytes(32))
                    output.flush()
                    os.fsync(output.fileno())
        if os.name != "nt" and self.key_path.stat().st_mode & 0o077:
            raise AuditIntegrityError("Audit key permissions unsafe")
        self.key = self.key_path.read_bytes()
        if len(self.key) != 32:
            raise AuditIntegrityError("Invalid audit key")
        db.execute("BEGIN IMMEDIATE")
        try:
            checkpoint = db.execute(
                "SELECT last_pruned,mac FROM audit_anchor WHERE id=1"
            ).fetchone()
            if checkpoint is None:
                if existing:
                    raise AuditIntegrityError("Audit checkpoint missing")
                # One-time migration: seal pre-existing G08-min audit records.
                db.execute("INSERT INTO audit_anchor VALUES(1,0,?)", ("0" * 64,))
                for row in db.execute("SELECT * FROM audit ORDER BY sequence"):
                    self._append_row(db, row)
            self.verify(db)
            db.commit()
        except BaseException:
            db.rollback()
            raise

    def _mac(self, previous: str, row: tuple) -> str:
        payload = json.dumps(
            list(row), separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        return hmac.new(self.key, previous.encode("ascii") + b":" + payload,
                        hashlib.sha256).hexdigest()

    def _append_row(self, db: sqlite3.Connection, row: tuple) -> None:
        previous = db.execute("SELECT mac FROM audit_chain ORDER BY sequence DESC"
                              " LIMIT 1").fetchone()
        if previous is None:
            previous = db.execute("SELECT mac FROM audit_anchor WHERE id=1").fetchone()
        mac = self._mac(previous[0], row)
        db.execute("INSERT INTO audit_chain(sequence,mac) VALUES(?,?)",
                   (row[0], mac))

    def append(self, db: sqlite3.Connection, sequence: int) -> None:
        row = db.execute("SELECT * FROM audit WHERE sequence=?", (sequence,)).fetchone()
        if row is None or self.key is None:
            raise AuditIntegrityError("Audit ledger not initialized")
        self._append_row(db, row)
        # Preserve proof of truncated prefix in an anchor checkpoint.
        count = db.execute("SELECT count(*) FROM audit").fetchone()[0]
        if count > self.max_rows:
            remove = count - self.max_rows
            anchor = db.execute(
                "SELECT sequence,mac FROM audit_chain ORDER BY sequence"
                " LIMIT 1 OFFSET ?", (remove - 1,),
            ).fetchone()
            if anchor is None:
                raise AuditIntegrityError("Audit prune checkpoint missing")
            db.execute("UPDATE audit_anchor SET last_pruned=?,mac=? WHERE id=1",
                       anchor)
            db.execute("DELETE FROM audit WHERE sequence<=?", (anchor[0],))

    def verify(self, db: sqlite3.Connection) -> int:
        anchor = db.execute(
            "SELECT last_pruned,mac FROM audit_anchor WHERE id=1").fetchone()
        if anchor is None or self.key is None:
            raise AuditIntegrityError("Missing audit integrity anchor")
        prior_seq, previous = anchor
        count = 0
        rows = db.execute(
            "SELECT a.*,c.mac FROM audit a LEFT JOIN audit_chain c"
            " ON c.sequence=a.sequence ORDER BY a.sequence",
        )
        for joined in rows:
            row, mac = joined[:-1], joined[-1]
            if row[0] != prior_seq + 1 or not isinstance(mac, str):
                raise AuditIntegrityError("Missing or reordered audit sequence")
            expected = self._mac(previous, row)
            if not hmac.compare_digest(expected, mac):
                raise AuditIntegrityError("Audit HMAC mismatch")
            prior_seq, previous = row[0], mac
            count += 1
        orphaned = db.execute("SELECT count(*) FROM audit_chain c"
                              " LEFT JOIN audit a ON a.sequence=c.sequence"
                              " WHERE a.sequence IS NULL").fetchone()[0]
        if orphaned:
            raise AuditIntegrityError("Orphaned audit chain entry")
        return count
