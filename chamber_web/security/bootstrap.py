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
        print("WARNING: Restore factory administrator username/password: "
              "admin / admin.")
        print("This restores General login and revokes ALL user sessions. "
              "It does NOT stop chamber hardware or erase test data.")
        print("First bring the chamber to a verified safe state and stop "
              "the server using approved local procedures.")
        if input("Type RESET to restore factory credentials: ").strip() != "RESET":
            print("Reset cancelled; no credentials changed.", file=sys.stderr)
            return 2
        store.reset_factory_credentials_offline()
        print("Factory credentials restored: username admin, password admin. "
              "Sessions revoked.")
        print("Change the factory password immediately before LAN use.")
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
    parser.add_argument("--reset-credentials", action="store_true",
                        help="Host-console-only recovery to factory admin/admin")
    options = parser.parse_args()
    if options.reset_credentials:
        return interactive_reset_credentials(options.data_dir)
    return interactive_bootstrap(options.data_dir)


if __name__ == "__main__":
    raise SystemExit(main())
