"""Append-only audit export with an independent SHA-256 checksum.

The SQLite audit table is the source of truth. Operators copy a CSV snapshot
to offline media on a daily schedule and retain the adjacent ``.sha256`` file.
There is no key, row chain or startup integrity gate.
"""
from __future__ import annotations

import csv
from hashlib import sha256
import os
from pathlib import Path
import sqlite3


_COLUMNS = (
    "sequence", "at_utc", "user_id", "username", "role", "action",
    "outcome", "chamber_id", "detail",
)


def export_audit_csv(database: Path, destination: Path) -> tuple[Path, str]:
    """Write one non-overwriting CSV snapshot and its SHA-256 sidecar."""
    database, destination = Path(database), Path(destination)
    sidecar = Path(str(destination) + ".sha256")
    for path in (destination, sidecar):
        if path.exists() or path.is_symlink():
            raise FileExistsError("Audit export destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    try:
        with sqlite3.connect(
                f"file:{database.resolve().as_posix()}?mode=ro", uri=True) as db, \
                temporary.open("w", encoding="utf-8", newline="") as output:
            writer = csv.writer(output, lineterminator="\n")
            writer.writerow(_COLUMNS)
            writer.writerows(db.execute(
                "SELECT sequence,at_utc,user_id,username,role,action,outcome,"
                "chamber_id,detail FROM audit ORDER BY sequence"))
            output.flush()
            os.fsync(output.fileno())
        checksum = _hash_file(temporary)
        os.replace(temporary, destination)
        sidecar.write_text(f"{checksum}  {destination.name}\n", encoding="ascii")
        return destination, checksum
    finally:
        temporary.unlink(missing_ok=True)


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for piece in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(piece)
    return digest.hexdigest()
