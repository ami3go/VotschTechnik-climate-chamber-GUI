"""Offline, interactive first-administrator provisioning. No HTTP bootstrap."""
from __future__ import annotations

import argparse
import getpass
import os
import sqlite3
import sys
from pathlib import Path

from .auth import AuthorizationError, SecurityStore
from .paths import security_directory


def interactive_bootstrap(directory: Path | None = None) -> int:
    """Shared by source CLI and the frozen standalone Windows server EXE."""
    if not sys.stdin.isatty():
        print("Refusing bootstrap without an interactive local terminal", file=sys.stderr)
        return 2
    store = SecurityStore.from_environment(directory)
    if store.is_bootstrapped():
        print("Administrator already provisioned; bootstrap disabled", file=sys.stderr)
        return 2
    username = input("New administrator username: ").strip()
    password = getpass.getpass("New administrator password (12+ bytes): ")
    repeat = getpass.getpass("Repeat password: ")
    if password != repeat:
        print("Passwords do not match", file=sys.stderr)
        return 2
    try:
        store.bootstrap_admin(username, password)
    except (ValueError, PermissionError, AuthorizationError) as exc:
        print(f"Bootstrap rejected: {exc}", file=sys.stderr)
        return 2
    print("Administrator provisioned locally. No default password exists.")
    return 0


def interactive_recovery(*, issue: bool = False, directory: Path | None = None) -> int:
    """Offline host-only recovery enrollment or one-use consumption.

    Do not invoke from a web route or unattended launch script. Back up the
    signing key and store issued recovery credentials in separate offline media.
    """
    if not sys.stdin.isatty():
        print("Recovery requires an interactive local terminal", file=sys.stderr)
        return 2
    from .auth import AuthenticationError
    store = SecurityStore.from_environment(directory)
    if not store.is_bootstrapped():
        print("No administrator provisioned", file=sys.stderr)
        return 2
    username = input("Administrator account: ").strip()
    try:
        if issue:
            password = getpass.getpass("Current administrator password: ")
            session = store.login(username, password, offline_primary_password=True)
            try:
                token = store.issue_recovery_token(session.session, session.csrf)
            finally:
                store.logout(session.session)
            print("Store this one-time credential OFFLINE. It is not logged:")
            print(token)
            return 0
        token = getpass.getpass("Offline recovery credential: ")
        password = getpass.getpass("New administrator password: ")
        repeat = getpass.getpass("Repeat new password: ")
        if password != repeat:
            print("Passwords do not match", file=sys.stderr)
            return 2
        store.recover_admin_offline(token, username, password)
        print("Credential consumed, password reset and sessions revoked.")
        return 0
    except (ValueError, PermissionError, AuthenticationError, AuthorizationError) as exc:
        print(f"Offline recovery rejected: {type(exc).__name__}", file=sys.stderr)
        return 2

def _local_reset_console() -> bool:
    """Best-effort remote-session rejection; filesystem ACLs are authoritative.

    Never offer this operation as an HTTP, RPC, or web-admin callback.
    TTY alone does not distinguish an on-host terminal emulator from SSH,
    hence the additional common remote-session indicators.
    """
    if not sys.stdin.isatty():
        return False
    if any(os.environ.get(key) for key in ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY")):
        return False
    if os.environ.get("SESSIONNAME", "").upper().startswith("RDP-"):
        return False
    if os.name == "nt":
        try:
            import ctypes
            if ctypes.windll.user32.GetSystemMetrics(0x1000):
                return False
        except (AttributeError, OSError):
            return False
    return True


def interactive_reset_credentials(directory: Path | None = None) -> int:
    """Host-console-only factory credential recovery, without old credentials.

    This privileged maintenance operation requires OS access to the existing
    deployment identity database. Explicit confirmation is mandatory.
    """
    if not _local_reset_console():
        print("Factory credential reset requires an interactive console on the "
              "server PC (SSH/RDP/unattended sessions refused)", file=sys.stderr)
        return 2
    root = (Path(directory).expanduser().resolve()
            if directory is not None else security_directory())
    if not (root / "security.sqlite3").is_file():
        print("Existing security database not found; reset refused",
              file=sys.stderr)
        return 2
    try:
        store = SecurityStore.from_environment(root)
        if not store.is_bootstrapped():
            print("No administrator provisioned; reset refused", file=sys.stderr)
            return 2
        print("WARNING: Restore factory administrator username/password/PIN: "
              "admin / admin / 12345678.")
        print("This restores General login and revokes ALL user sessions. "
              "It does NOT stop chamber hardware or erase test data.")
        print("First bring the chamber to a verified safe state and stop "
              "the server using approved local procedures.")
        if input("Type RESET to restore factory credentials: ").strip() != "RESET":
            print("Reset cancelled; no credentials changed.", file=sys.stderr)
            return 2
        store.reset_factory_credentials_offline()
        print("Factory credentials restored: username admin, password admin, "
              "PIN 12345678, profile General. Sessions revoked.")
        print("Change the factory password and PIN immediately before LAN use.")
        return 0
    except (ValueError, PermissionError, AuthorizationError,
            RuntimeError, OSError, sqlite3.Error) as exc:
        print(f"Factory credential reset rejected: {type(exc).__name__}",
              file=sys.stderr)
        return 2

def main() -> int:
    parser = argparse.ArgumentParser(description="Offline climate chamber admin setup")
    parser.add_argument("--data-dir", type=Path, default=None,
                        help="Local security data folder (default ~/.chamber_web/security)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--issue-recovery-token", action="store_true")
    group.add_argument("--recover-admin", action="store_true")
    group.add_argument("--reset-credentials", action="store_true",
                       help="Host-console-only recovery to factory admin/admin and PIN 12345678")
    options = parser.parse_args()
    if options.reset_credentials:
        return interactive_reset_credentials(options.data_dir)
    if options.issue_recovery_token or options.recover_admin:
        return interactive_recovery(issue=options.issue_recovery_token,
                                    directory=options.data_dir)
    return interactive_bootstrap(options.data_dir)


if __name__ == "__main__":
    raise SystemExit(main())
