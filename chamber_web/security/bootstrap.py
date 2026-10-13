"""Offline, interactive first-administrator provisioning. No HTTP bootstrap."""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from .auth import AuthorizationError, SecurityStore


def interactive_bootstrap(directory: Path | None = None) -> int:
    """Shared by source CLI and the frozen standalone Windows server EXE."""
    if not sys.stdin.isatty():
        print("Refusing bootstrap without an interactive local terminal", file=sys.stderr)
        return 2
    store = SecurityStore(directory)
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline climate chamber admin setup")
    parser.add_argument("--data-dir", type=Path, default=None,
                        help="Local security data folder (default ~/.chamber_web/security)")
    options = parser.parse_args()
    return interactive_bootstrap(options.data_dir)


if __name__ == "__main__":
    raise SystemExit(main())
