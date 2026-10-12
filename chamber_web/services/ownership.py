"""Process-exclusive, transactionally fenced one-device lease (G04-A).

The OS lock is the cross-process authority; SQLite persists generations and
uncertainty across restarts. Never substitute a DB timeout for hardware STOP.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import uuid
from pathlib import Path

from chamber_web.domain.chamber import ChamberSafetyError, validate_chamber_id

_IN_PROCESS: set[Path] = set()
_MUTEX = threading.Lock()


class DeviceLease:
    def __init__(self, chamber_id: str, directory: Path | None = None):
        self.chamber_id = validate_chamber_id(chamber_id)
        # Application-wide default; NOT one random temporary directory per process.
        self.directory = Path(directory) if directory is not None else (
            Path.home() / ".chamber_web" / "ownership"
        )
        self.directory = self.directory.resolve()
        self._file = None
        self._locked = False
        self._db = None
        self.owner = uuid.uuid4().hex
        self.generation = 0
        self.needs_reconciliation = True

    def acquire(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / (self.chamber_id + ".lock")
        with _MUTEX:
            if path in _IN_PROCESS:
                raise ChamberSafetyError("Device already owned by a controller in this process")
            _IN_PROCESS.add(path)
        try:
            self._file = open(path, "a+b")
            self._file.seek(0)
            if self._file.read(1) == b"":
                self._file.write(b"0")
                self._file.flush()
            self._file.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (OSError, BlockingIOError) as exc:
                raise ChamberSafetyError("Device process lock is held") from exc
            self._locked = True
            self._db = sqlite3.connect(
                self.directory / "ownership.sqlite3", timeout=2.0,
                isolation_level=None, check_same_thread=False,
            )
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS device_lease ("
                "chamber_id TEXT PRIMARY KEY, owner TEXT, generation INTEGER NOT NULL,"
                " uncertain INTEGER NOT NULL CHECK(uncertain IN (0,1)))"
            )
            self._db.execute("BEGIN IMMEDIATE")
            try:
                prior = self._db.execute(
                    "SELECT owner, generation, uncertain FROM device_lease WHERE chamber_id=?",
                    (self.chamber_id,),
                ).fetchone()
                self.needs_reconciliation = prior is not None and (
                    prior[0] is not None or bool(prior[2])
                )
                self.generation = int(prior[1]) + 1 if prior else 1
                self._db.execute(
                    "INSERT INTO device_lease(chamber_id,owner,generation,uncertain) "
                    "VALUES(?,?,?,?) ON CONFLICT(chamber_id) DO UPDATE SET "
                    "owner=excluded.owner, generation=excluded.generation, "
                    "uncertain=excluded.uncertain",
                    (self.chamber_id, self.owner, self.generation,
                     int(self.needs_reconciliation)),
                )
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
        except BaseException:
            self._release_resources()
            raise

    def _transaction(self, *, increment: bool = False,
                     uncertain: bool | None = None) -> int:
        if self._db is None:
            raise ChamberSafetyError("Device lease not acquired")
        self._db.execute("BEGIN IMMEDIATE")
        try:
            row = self._db.execute(
                "SELECT owner,generation FROM device_lease WHERE chamber_id=?",
                (self.chamber_id,),
            ).fetchone()
            if row != (self.owner, self.generation):
                raise ChamberSafetyError("Stale device ownership/generation")
            next_generation = self.generation + int(increment)
            if increment or uncertain is not None:
                if uncertain is None:
                    self._db.execute(
                        "UPDATE device_lease SET generation=? WHERE chamber_id=?",
                        (next_generation, self.chamber_id),
                    )
                else:
                    self._db.execute(
                        "UPDATE device_lease SET generation=?, uncertain=? WHERE chamber_id=?",
                        (next_generation, int(uncertain), self.chamber_id),
                    )
            self._db.execute("COMMIT")
            self.generation = next_generation
            return next_generation
        except BaseException:
            self._db.execute("ROLLBACK")
            raise

    def verify(self, generation: int) -> None:
        if self._transaction() != generation:
            raise ChamberSafetyError("Stale command generation")

    def fence(self) -> int:
        return self._transaction(increment=True, uncertain=True)

    def mark_uncertain(self) -> None:
        self._transaction(uncertain=True)

    def reconcile(self) -> None:
        self._transaction(uncertain=False)
        self.needs_reconciliation = False

    def close(self, *, verified_stopped: bool = False) -> None:
        try:
            if self._db is not None:
                self._db.execute("BEGIN IMMEDIATE")
                try:
                    row = self._db.execute(
                        "SELECT owner,generation FROM device_lease WHERE chamber_id=?",
                        (self.chamber_id,),
                    ).fetchone()
                    if row == (self.owner, self.generation):
                        self._db.execute(
                            "UPDATE device_lease SET owner=NULL, generation=?, uncertain=? "
                            "WHERE chamber_id=?",
                            (self.generation + 1, int(not verified_stopped),
                             self.chamber_id),
                        )
                    self._db.execute("COMMIT")
                except BaseException:
                    self._db.execute("ROLLBACK")
                    raise
        finally:
            self._release_resources()

    def _release_resources(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None
        if self._file is not None:
            try:
                self._file.seek(0)
                if self._locked and os.name == "nt":
                    import msvcrt
                    msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
                elif self._locked:
                    import fcntl
                    fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            finally:
                self._file.close()
                self._file = None
                self._locked = False
        with _MUTEX:
            _IN_PROCESS.discard(self.directory / (self.chamber_id + ".lock"))
