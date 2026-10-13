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




def interactive_recovery(*, issue: bool = False, directory: Path | None = None) -> int:
    """Offline host-only recovery enrollment or one-use consumption.

    Do not invoke from a web route or unattended launch script. Back up the
    signing key and store issued recovery credentials in separate offline media.
    """
    if not sys.stdin.isatty():
        print("Recovery requires an interactive local terminal", file=sys.stderr)
        return 2
    from .auth import AuthenticationError
    store = SecurityStore(directory)
    if not store.is_bootstrapped():
        print("No administrator provisioned", file=sys.stderr)
        return 2
    username = input("Administrator account: ").strip()
    try:
        if issue:
            password = getpass.getpass("Current administrator password: ")
            session = store.login(username, password)
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

def main() -> int:
    parser = argparse.ArgumentParser(description="Offline climate chamber admin setup")
    parser.add_argument("--data-dir", type=Path, default=None,
                        help="Local security data folder (default ~/.chamber_web/security)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--issue-recovery-token", action="store_true")
    group.add_argument("--recover-admin", action="store_true")
    options = parser.parse_args()
    if options.issue_recovery_token or options.recover_admin:
        return interactive_recovery(issue=options.issue_recovery_token,
                                    directory=options.data_dir)
    return interactive_bootstrap(options.data_dir)


if __name__ == "__main__":
    raise SystemExit(main())
