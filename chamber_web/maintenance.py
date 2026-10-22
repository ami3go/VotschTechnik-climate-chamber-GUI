"""Offline security maintenance commands shared by every desktop entry point.

These operations never touch the network listener: they run before the server
starts, on the local security directory. Interactive bootstrap/recovery and
restores always require a local terminal. Signed security backups may run
unattended (for example from a Windows scheduled task) when the deployment
explicitly opts in with ``CHAMBER_UNATTENDED_MAINTENANCE=1``; the command still
refuses an existing destination and writes a signed manifest next to it.
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
    parser.add_argument("--issue-recovery-token", action="store_true")
    parser.add_argument("--recover-admin", action="store_true")
    parser.add_argument("--reset-credentials", action="store_true")
    parser.add_argument("--backup-security", type=Path,
                        help="Signed consistent security backup destination")
    parser.add_argument("--verify-security", type=Path)
    parser.add_argument("--stage-restore-security", type=Path)
    parser.add_argument("--restore-directory", type=Path)


def unattended_allowed() -> bool:
    return os.environ.get(UNATTENDED_ENV, "").strip() == "1"


def run(args: argparse.Namespace) -> int | None:
    """Execute one maintenance operation; None when none was requested."""
    modes = (args.bootstrap_admin, args.issue_recovery_token,
             args.recover_admin, args.reset_credentials,
             args.backup_security is not None,
             args.verify_security is not None,
             args.stage_restore_security is not None)
    if sum(bool(mode) for mode in modes) > 1:
        raise ValueError("Choose only one maintenance operation")
    if not any(modes):
        return None
    if args.bootstrap_admin:
        from chamber_web.security.bootstrap import interactive_bootstrap
        return interactive_bootstrap()
    if args.issue_recovery_token or args.recover_admin:
        from chamber_web.security.bootstrap import interactive_recovery
        return interactive_recovery(issue=args.issue_recovery_token)
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
            security_directory(), args.stage_restore_security,
            args.restore_directory)
        banner("Staged restore with all sessions revoked: " + str(output))
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
        banner("Signed manifest: " + str(manifest))
    else:
        verify_security_backup(security_directory(), args.verify_security)
        banner("Security backup verified")
    return 0
