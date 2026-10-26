"""SQLite security backups with a SHA-256 manifest. No HTTP endpoints.

Restoration is always into a NEW empty directory, never an in-place live SQLite
overwrite. All sessions are revoked. The backup is not signed; protect the
offline copy with filesystem ACLs and retain it on isolated media.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time


MAX_BACKUP_BYTES = 512 * 1024 * 1024
SCHEMA_VERSION = 1
FORMAT = "chamber-security-backup-v2"


class BackupError(RuntimeError):
    pass


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for piece in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(piece)
    return digest.hexdigest()


def _integrity(path: Path) -> int:
    with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise BackupError("SQLite integrity check failed")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version not in {0, SCHEMA_VERSION}:
            raise BackupError("Unknown backup schema")
        required = {"users", "sessions", "audit", "bootstrap"}
        found = {r[0] for r in db.execute("SELECT name FROM sqlite_master"
                                          " WHERE type='table'")}
        if not required.issubset(found):
            raise BackupError("Incomplete security schema")
        return version


def backup_security_database(source_dir: Path, destination: Path) -> tuple[Path, Path]:
    """Online SQLite consistent backup; overwrite and symlinks are forbidden."""
    source_dir, destination = Path(source_dir), Path(destination)
    if destination.exists() or destination.is_symlink():
        raise BackupError("Backup destination already exists")
    manifest_path = Path(str(destination) + ".manifest.json")
    if manifest_path.exists() or manifest_path.is_symlink():
        raise BackupError("Manifest destination already exists")
    database = source_dir / "security.sqlite3"
    if not database.is_file() or database.is_symlink():
        raise BackupError("Source security database missing or unsafe")
    destination.parent.mkdir(parents=True, exist_ok=True)
    scratch = destination.with_name(destination.name + "." + secrets.token_hex(8) + ".tmp")
    try:
        with closing(sqlite3.connect(database)) as source, closing(
                sqlite3.connect(scratch)) as dest:
            source.backup(dest, pages=1000, sleep=0.1)
        if scratch.stat().st_size > MAX_BACKUP_BYTES:
            raise BackupError("Security backup exceeds size limit")
        schema = _integrity(scratch)
        payload = {"format": FORMAT, "size": scratch.stat().st_size,
                   "schema": schema, "sha256": _hash_file(scratch),
                   "created_utc": int(time.time())}
        # Windows rejects fsync on a read-only descriptor and holds SQLite
        # files locked while connections remain open.
        with scratch.open("r+b") as file:
            os.fsync(file.fileno())
        os.replace(scratch, destination)
        manifest_path.write_text(json.dumps(payload, sort_keys=True) + "\n",
                                 encoding="utf-8")
        return destination, manifest_path
    finally:
        scratch.unlink(missing_ok=True)


def verify_security_backup(backup: Path) -> dict:
    backup = Path(backup)
    manifest_path = Path(str(backup) + ".manifest.json")
    if (backup.is_symlink() or manifest_path.is_symlink()
            or not backup.is_file() or not manifest_path.is_file()):
        raise BackupError("Missing or unsafe backup/manifest")
    if backup.stat().st_size > MAX_BACKUP_BYTES:
        raise BackupError("Backup exceeds maximum supported size")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        # Read manifests written by the earlier signed schema too; the MAC was
        # only an integrity aid and the payload checks below are equivalent.
        if set(payload) == {"payload", "mac_sha256"}:
            payload = payload["payload"]
        if (payload["format"] not in {FORMAT, "chamber-security-backup-v1"}
                or payload["size"] != backup.stat().st_size
                or payload["sha256"] != _hash_file(backup)
                or payload["schema"] != _integrity(backup)):
            raise BackupError("Backup content or schema mismatch")
    except (KeyError, ValueError, TypeError, OSError) as exc:
        raise BackupError("Invalid backup manifest") from exc
    return payload


def stage_security_restore(backup: Path, target_dir: Path) -> Path:
    """Stage offline restore only; stop the service before switching data root.

    A restore does not copy NiceGUI signing keys or existing authenticated
    sessions. A privileged operator must explicitly provision signing keys.
    """
    verify_security_backup(backup)
    target_dir = Path(target_dir)
    if target_dir.is_symlink() or (
            target_dir.exists() and any(target_dir.iterdir())):
        raise BackupError("Restore requires a new empty directory")
    target_dir.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        target_dir.chmod(0o700)
    destination = target_dir / "security.sqlite3"
    if destination.exists():
        raise BackupError("Refusing in-place database overwrite")
    temporary = target_dir / ("restore-" + secrets.token_hex(8) + ".tmp")
    try:
        with closing(sqlite3.connect(
                f"file:{Path(backup).resolve().as_posix()}?mode=ro",
                uri=True)) as source, closing(sqlite3.connect(temporary)) as dest:
            source.backup(dest)
            # Sessions from backup must NOT be resurrected as authenticated.
            dest.execute("UPDATE sessions SET revoked=1")
            dest.commit()
        _integrity(temporary)
        if os.name != "nt":
            temporary.chmod(0o600)
        os.replace(temporary, destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)
