"""Local operator-issued, 24-hour PIN gate for physical HIL *test tools*.

This does not alter the product's G04/G05/G06 safety or site release policies.
Only operator-terminal CLI commands issue/reset PINs. Physical test entrypoints
must call require_hil_pin BEFORE any device connection.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import stat
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

PIN_ENV = "CHAMBER_HIL_PIN"
TTL = timedelta(hours=24)
_VERSION = 1


class HilPinError(RuntimeError):
    """PIN absent, invalid, expired, or local state unsafe."""


def state_path() -> Path:
    """User-local fixed location (not configurable by an agent-controlled env var)."""
    return Path.home() / ".local" / "state" / "votsch-climate-chamber" / "hil-pin.json"


def _state_directory(path: Path, *, create: bool = True) -> None:
    parent = path.parent
    if parent.is_symlink():
        raise HilPinError("HIL PIN state directory must not be a symlink")
    try:
        if create:
            parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        info = parent.stat()
    except OSError as exc:
        raise HilPinError("HIL PIN state directory is unavailable") from exc
    if not stat.S_ISDIR(info.st_mode) or parent.is_symlink():
        raise HilPinError("HIL PIN state directory is unsafe")
    if os.name == "posix":
        if info.st_mode & 0o077:
            raise HilPinError("HIL PIN state directory must have mode 0700")
        if info.st_uid != os.getuid():
            raise HilPinError("HIL PIN state directory belongs to another user")


def _read(path: Path) -> dict:
    try:
        _state_directory(path, create=False)
        if path.is_symlink():
            raise HilPinError("HIL PIN state file must not be a symlink")
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            raise HilPinError("HIL PIN state must be a regular file")
        if os.name == "posix":
            if info.st_mode & 0o077:
                raise HilPinError("HIL PIN state file must have mode 0600")
            if info.st_uid != os.getuid():
                raise HilPinError("HIL PIN state file belongs to another user")
        with path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
        if not isinstance(data, dict) or set(data) != {
            "version", "issued_at_utc", "expires_at_utc", "salt", "digest"
        } or data["version"] != _VERSION:
            raise HilPinError("HIL PIN state is malformed")
        return data
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HilPinError("HIL PIN state unavailable or malformed") from exc


def _timestamp(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo is None or result.utcoffset() != timedelta(0):
            raise ValueError("timestamp must be UTC")
        return result
    except (TypeError, ValueError) as exc:
        raise HilPinError("HIL PIN state has invalid timestamps") from exc


def _expiry(data: dict) -> datetime:
    issued = _timestamp(data["issued_at_utc"])
    expiry = _timestamp(data["expires_at_utc"])
    if expiry - issued != TTL:
        raise HilPinError("HIL PIN state has an invalid validity window")
    return expiry


def _hash(pin: str, salt: bytes) -> bytes:
    return hashlib.scrypt(pin.encode("ascii"), salt=salt, n=2**14, r=8, p=1, dklen=32)


def issue_pin(*, reset: bool = False, path: Path | None = None,
              now: datetime | None = None) -> tuple[str, datetime]:
    """Generate/rotate PIN; CLI adds human-in-terminal confirmation."""
    path = path or state_path()
    _state_directory(path)
    if path.is_symlink():
        raise HilPinError("HIL PIN state file must not be a symlink")
    if path.exists() and not reset:
        raise HilPinError("PIN already exists; use reset to rotate it")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise HilPinError("UTC clock required")
    pin = f"{secrets.randbelow(100_000_000):08d}"
    salt = secrets.token_bytes(16)
    expires = now + TTL
    payload = json.dumps({
        "version": _VERSION,
        "issued_at_utc": now.isoformat(),
        "expires_at_utc": expires.isoformat(),
        "salt": salt.hex(),
        "digest": _hash(pin, salt).hex(),
    }, sort_keys=True) + "\n"
    tmp = None
    created = False
    try:
        if reset:
            fd, tmp = tempfile.mkstemp(prefix=".hil-pin-", dir=path.parent)
        else:
            # O_EXCL makes two simultaneous setup attempts deterministic: one
            # wins and the other fails instead of silently rotating the PIN.
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created = True
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if reset:
            os.replace(tmp, path)
            tmp = None
    except FileExistsError as exc:
        raise HilPinError("PIN already exists; use reset to rotate it") from exc
    except OSError as exc:
        if created:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise HilPinError("Could not write HIL PIN state") from exc
    finally:
        if tmp is not None and os.path.exists(tmp):
            os.unlink(tmp)
    return pin, expires


def verify_pin(pin: str | None, *, path: Path | None = None,
               now: datetime | None = None) -> None:
    """Fail closed; PIN is never put into errors or audit logs."""
    if not isinstance(pin, str) or len(pin) != 8 or not pin.isascii() or not pin.isdigit():
        raise HilPinError("Missing or invalid HIL operator PIN")
    path = path or state_path()
    data = _read(path)
    now = now or datetime.now(timezone.utc)
    expiry = _expiry(data)
    if now >= expiry or now < _timestamp(data["issued_at_utc"]):
        raise HilPinError("HIL operator PIN has expired or is not yet valid")
    try:
        salt = bytes.fromhex(data["salt"])
        digest = bytes.fromhex(data["digest"])
        if len(salt) != 16 or len(digest) != 32:
            raise ValueError("invalid hash length")
    except (ValueError, TypeError) as exc:
        raise HilPinError("HIL PIN state is malformed") from exc
    if not hmac.compare_digest(_hash(pin, salt), digest):
        raise HilPinError("Missing or invalid HIL operator PIN")


def require_hil_pin(env: Mapping[str, str] | None = None) -> None:
    """Call before *all* real-chamber test probes, including read-only probes."""
    verify_pin((os.environ if env is None else env).get(PIN_ENV))


def revoke_pin(*, path: Path | None = None) -> None:
    path = path or state_path()
    if path.exists() or path.is_symlink():
        _state_directory(path, create=False)
    if path.is_symlink():
        raise HilPinError("HIL PIN state file must not be a symlink")
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise HilPinError("Could not revoke HIL PIN") from exc


def _operator_confirmation(action: str) -> None:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise HilPinError(f"{action} requires an interactive local operator terminal")
    print("Local operator: confirm bench is free, chamber is STOPPED,")
    print("the correct serial/envelope is configured, and the physical STOP is accessible.")
    if input("Type AUTHORIZE to proceed: ").strip() != "AUTHORIZE":
        raise HilPinError("Operator did not authorize PIN change")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local 24-hour HIL test PIN")
    parser.add_argument("action", choices=("setup", "reset", "revoke", "status", "verify"))
    args = parser.parse_args(argv)
    try:
        path = state_path()
        if args.action in ("setup", "reset", "revoke"):
            _operator_confirmation(args.action)
        if args.action in ("setup", "reset"):
            pin, expires = issue_pin(reset=args.action == "reset", path=path)
            print("Operator PIN (displayed only once):", pin)
            print("Valid until (UTC):", expires.isoformat())
            print("Do not commit, log or paste the PIN into a GitHub issue.")
        elif args.action == "revoke":
            revoke_pin(path=path)
            print("PIN revoked; no new HIL test may be admitted.")
        elif args.action == "status":
            data = _read(path)
            expiry = _expiry(data)
            print("PIN:", "VALID" if datetime.now(timezone.utc) < expiry else "EXPIRED")
            print("Expiry UTC:", expiry.isoformat())
        else:
            require_hil_pin()
            print("HIL PIN verified.")
        return 0
    except HilPinError as exc:
        print("HIL PIN denied:", exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
