"""Offline security maintenance commands shared by every desktop entry point.

These operations never touch the network listener: they run before the server
starts, on the local security directory. Interactive bootstrap and restores
always require a local terminal. Security backups and restores require an
explicit ``CHAMBER_UNATTENDED_MAINTENANCE=1`` opt-in for non-interactive use;
audit export needs only a readable database. Both backup and audit export refuse
an existing destination and write a SHA-256 sidecar next to it.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

UNATTENDED_ENV = "CHAMBER_UNATTENDED_MAINTENANCE"


def banner(label: str) -> None:
    print(label, flush=True)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--bootstrap-admin", action="store_true",
                        help="Interactive offline first administrator")
    parser.add_argument("--reset-credentials", action="store_true")
    parser.add_argument("--backup-security", type=Path,
                        help="Consistent security backup destination")
    parser.add_argument("--verify-security", type=Path)
    parser.add_argument("--stage-restore-security", type=Path)
    parser.add_argument("--restore-directory", type=Path)
    parser.add_argument("--export-audit", type=Path,
                        help="Append-only audit CSV snapshot plus SHA-256")


def unattended_allowed() -> bool:
    return os.environ.get(UNATTENDED_ENV, "").strip() == "1"


def run(args: argparse.Namespace) -> int | None:
    """Execute one maintenance operation; None when none was requested."""
    modes = (args.bootstrap_admin, args.reset_credentials,
             args.backup_security is not None,
             args.verify_security is not None,
             args.stage_restore_security is not None,
             args.export_audit is not None)
    if sum(bool(mode) for mode in modes) > 1:
        raise ValueError("Choose only one maintenance operation")
    if not any(modes):
        return None
    if args.bootstrap_admin:
        from chamber_web.security.bootstrap import interactive_bootstrap
        return interactive_bootstrap()
    if args.reset_credentials:
        from chamber_web.security.bootstrap import interactive_reset_credentials
        return interactive_reset_credentials()
    if args.stage_restore_security is not None:
        if not sys.stdin.isatty():
            raise RuntimeError("Security restore staging requires a local terminal")
        from chamber_web.security.backup import stage_security_restore
        from chamber_web.security.paths import security_directory
        if args.restore_directory is None:
            raise ValueError("--restore-directory required")
        output = stage_security_restore(
            args.stage_restore_security, args.restore_directory)
        banner("Staged restore with all sessions revoked: " + str(output))
        return 0
    if args.export_audit is not None:
        from chamber_web.security.audit_integrity import export_audit_csv
        from chamber_web.security.paths import security_directory
        database = security_directory() / "security.sqlite3"
        if not database.is_file():
            raise RuntimeError("Security database is missing")
        output, digest = export_audit_csv(database, args.export_audit)
        banner("Audit export: " + str(output))
        banner("SHA-256: " + digest)
        return 0
    if not sys.stdin.isatty() and not unattended_allowed():
        raise RuntimeError(
            "Security backup/verify requires a local terminal or "
            f"{UNATTENDED_ENV}=1")
    from chamber_web.security.backup import (
        backup_security_database,
        verify_security_backup,
    )
    from chamber_web.security.paths import security_directory
    if args.backup_security is not None:
        output, manifest = backup_security_database(
            security_directory(), args.backup_security)
        banner("Security backup: " + str(output))
        banner("SHA-256 manifest: " + str(manifest))
    else:
        verify_security_backup(args.verify_security)
        banner("Security backup verified")
    return 0
