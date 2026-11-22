"""Signed, bench-only enrollment for a network chamber *emulator*.

This is deliberately NOT a physical-chamber authorization. A real Vötsch
chamber is never admitted here: the enrollment must name an emulator serial
(``SIM...``) and the driver must report the emulator model
(``VT4011-EMULATOR``). The device is still classified separately from a real
chamber in :class:`~chamber_web.domain.chamber.ChamberIdentity` and in the UI.

Why a signed record instead of a serial prefix check: a matching USB/Ethernet
serial is useful bench evidence but is not cryptographic attestation. The
operator signs one exact device identity, address, envelope and validity
window with an Ed25519 key provisioned outside the browser and repository.
The server verifies that record before opening a socket.

Fail-closed rules:

* no enrollment/trusted key -> no emulator I/O;
* any ``CHAMBER_HIL_*``, ``CHAMBER_LAB_MODE`` or ``CHAMBER_H02_*`` setting
  present -> refuse to start (the operating policies are mutually exclusive);
* a release/offline-package launch -> refuse to start;
* expired, overlong, wrong-scope or wrong-model record -> refuse;
* a serial that does not start with ``SIM`` -> refuse (no real chamber).

The enrollment authorizes a *bench emulator*, never a production chamber, a
site acceptance or an R01 release. The normal G04/G06/G07/G08 safety path is
still exercised; this module only selects a non-production device class.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Mapping

from chamber_web.domain.chamber import ChamberSafetyError, validate_chamber_id

ENROLLMENT_ENV = "CHAMBER_EMULATOR_ENROLLMENT_FILE"
TRUSTED_KEY_ENV = "CHAMBER_EMULATOR_TRUSTED_KEY"
TRUSTED_KEY_FILE_ENV = "CHAMBER_EMULATOR_TRUSTED_KEY_FILE"
ACK_ENV = "CHAMBER_EMULATOR_ACK"
ACK = "ISOLATED-BENCH-EMULATOR"
SCOPE = "EMULATOR_BENCH_DEVICE"
SCHEMA_VERSION = 1
EMULATOR_MODEL = "VT4011-EMULATOR"
MAX_VALIDITY = timedelta(days=14)
MAX_ENROLLMENT_BYTES = 64 * 1024
MAX_ENVELOPE_SPAN_C = 60.0
HARD_MIN_C = -40.0
HARD_MAX_C = 130.0
# Real Vötsch serials are numeric. A signed enrollment for a real serial is
# therefore rejected before any socket is opened.
_SERIAL_RE = re.compile(r"SIM[A-Z0-9]{1,13}\Z")
_FIRMWARE_RE = re.compile(r"[0-9a-f]{64}\Z")
_FIELDS = {
    "schema_version", "scope", "chamber_id", "backend_id", "address",
    "expected_serial", "expected_model", "temperature_min_c",
    "temperature_max_c", "valid_from_utc", "valid_until_utc", "operator",
    "approval_reference", "isolated_network_ack", "firmware_sha256",
}
_CONFLICT_KEYS = (
    "CHAMBER_HIL_ADDRESS", "CHAMBER_HIL_EXPECTED_SERIAL",
    "CHAMBER_HIL_TEMP_MIN_C", "CHAMBER_HIL_TEMP_MAX_C", "CHAMBER_HIL_ACK",
    "CHAMBER_HIL_CHAMBER_ID", "CHAMBER_LAB_MODE", "CHAMBER_H02_PERMIT_FILE",
    "CHAMBER_H02_TRUSTED_KEY",
)
_RELEASE_KEYS = ("CHAMBER_RELEASE", "CHAMBER_W02_RELEASE", "CHAMBER_PRODUCTION")


@dataclass(frozen=True)
class EmulatorAuthorization:
    """Verified bench-emulator identity; never a physical-chamber permit."""

    chamber_id: str
    address: str
    expected_serial: str
    expected_model: str
    temperature_min_c: float
    temperature_max_c: float
    valid_until_utc: datetime
    operator: str
    approval_reference: str
    enrollment_sha256: str
    firmware_sha256: str | None = None
    backend_id: str = "votsch_emulator"

    def __post_init__(self) -> None:
        validate_chamber_id(self.chamber_id)
        if self.backend_id != "votsch_emulator":
            raise ChamberSafetyError("Emulator enrollment backend must be votsch_emulator")
        try:
            ip = ipaddress.ip_address(self.address)
        except ValueError as exc:
            raise ChamberSafetyError(
                "Emulator address must be a literal IPv4 address") from exc
        if ip.version != 4 or not ip.is_private or ip.is_loopback or ip.is_unspecified:
            raise ChamberSafetyError(
                "Emulator address must be a private, non-loopback IPv4 address")
        if _SERIAL_RE.fullmatch(self.expected_serial) is None:
            raise ChamberSafetyError(
                "Emulator serial must start with SIM and be 4-16 alphanumeric characters")
        if self.expected_model != EMULATOR_MODEL:
            raise ChamberSafetyError(
                f"Emulator model must be {EMULATOR_MODEL}")
        lo, hi = self.temperature_min_c, self.temperature_max_c
        if not (math.isfinite(lo) and math.isfinite(hi) and lo < hi):
            raise ChamberSafetyError("Emulator envelope must be finite with min < max")
        if lo < HARD_MIN_C or hi > HARD_MAX_C or hi - lo > MAX_ENVELOPE_SPAN_C:
            raise ChamberSafetyError(
                f"Emulator envelope must lie within {HARD_MIN_C}..{HARD_MAX_C} °C "
                f"and span at most {MAX_ENVELOPE_SPAN_C} °C")
        if self.valid_until_utc.tzinfo is None or (
                self.valid_until_utc.utcoffset().total_seconds() != 0):
            raise ChamberSafetyError("Emulator enrollment expiry must be explicit UTC")
        if re.fullmatch(r"[0-9a-f]{64}", self.enrollment_sha256) is None:
            raise ChamberSafetyError("Invalid emulator enrollment digest")
        if self.firmware_sha256 is not None and (
                _FIRMWARE_RE.fullmatch(self.firmware_sha256) is None):
            raise ChamberSafetyError("Invalid emulator firmware SHA-256")
        if not self.operator.strip() or not self.approval_reference.strip():
            raise ChamberSafetyError("Emulator enrollment requires operator and reference")


def _canonical(data: Mapping[str, object]) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _utc(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ChamberSafetyError("Emulator enrollment requires " + name)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ChamberSafetyError("Invalid emulator enrollment timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ChamberSafetyError("Emulator enrollment timestamps must be UTC")
    return parsed


def _trusted_key(env: Mapping[str, str]) -> bytes:
    encoded = env.get(TRUSTED_KEY_ENV, "").strip()
    key_file = env.get(TRUSTED_KEY_FILE_ENV, "").strip()
    if bool(encoded) == bool(key_file):
        raise ChamberSafetyError(
            "Set exactly one of " + TRUSTED_KEY_ENV + " or " + TRUSTED_KEY_FILE_ENV)
    if key_file:
        path = Path(key_file)
        _require_safe_regular_file(path, "emulator trusted key")
        try:
            encoded = path.read_text(encoding="ascii").strip()
        except OSError as exc:
            raise ChamberSafetyError("Emulator trusted key is unavailable") from exc
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise ChamberSafetyError("Emulator trusted key is not base64") from exc
    if len(raw) != 32:
        raise ChamberSafetyError("Emulator trusted Ed25519 key must be 32 bytes")
    return raw


def _require_safe_regular_file(path: Path, name: str) -> None:
    try:
        if path.is_symlink():
            raise ChamberSafetyError(f"{name} must not be a symlink")
        info = path.stat()
    except OSError as exc:
        raise ChamberSafetyError(f"{name} is unavailable") from exc
    if not stat.S_ISREG(info.st_mode):
        raise ChamberSafetyError(f"{name} must be a regular file")
    if info.st_size <= 0 or info.st_size > MAX_ENROLLMENT_BYTES:
        raise ChamberSafetyError(f"{name} size is invalid")
    if os.name == "posix" and info.st_mode & 0o022:
        raise ChamberSafetyError(f"{name} must not be group/world writable")


def verify_signed_enrollment(
    signed: Mapping[str, object], *,
    trusted_public_key: bytes,
    now_utc: datetime | None = None,
) -> EmulatorAuthorization:
    """Verify one exact-scope Ed25519 enrollment; raise on any mismatch."""
    if not isinstance(signed, dict) or set(signed) != {
            "enrollment", "signature_base64"}:
        raise ChamberSafetyError("Expected signed emulator enrollment envelope")
    data = signed["enrollment"]
    if not isinstance(data, dict) or set(data) != _FIELDS:
        raise ChamberSafetyError("Emulator enrollment schema invalid or incomplete")
    if type(data["schema_version"]) is not int or (
            data["schema_version"] != SCHEMA_VERSION or data["scope"] != SCOPE):
        raise ChamberSafetyError("Wrong emulator enrollment scope/schema")
    if not isinstance(trusted_public_key, bytes) or len(trusted_public_key) != 32:
        raise ChamberSafetyError("Trusted emulator Ed25519 public key not installed")
    canonical = _canonical(data)
    try:
        signature = base64.b64decode(signed["signature_base64"], validate=True)
        if len(signature) != 64:
            raise ValueError("Ed25519 signature must be 64 bytes")
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(trusted_public_key).verify(
            signature, canonical)
    except (ImportError, ValueError, TypeError, UnicodeError, OverflowError) as exc:
        raise ChamberSafetyError(
            "Emulator enrollment signature unavailable/invalid") from exc
    except Exception as exc:
        raise ChamberSafetyError("Emulator enrollment signature rejected") from exc
    # Bind all checks to the exact bytes that were verified.
    data = json.loads(canonical.decode("utf-8"))
    if data["backend_id"] != "votsch_emulator":
        raise ChamberSafetyError("Wrong emulator backend")
    if type(data["isolated_network_ack"]) is not bool or not data["isolated_network_ack"]:
        raise ChamberSafetyError("Emulator enrollment requires isolated-network acknowledgement")
    for name in ("operator", "approval_reference"):
        if not isinstance(data[name], str) or not data[name].strip() or len(data[name]) > 256:
            raise ChamberSafetyError("Missing/invalid emulator enrollment field: " + name)
    start = _utc(data["valid_from_utc"], "valid_from_utc")
    end = _utc(data["valid_until_utc"], "valid_until_utc")
    current = now_utc or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset().total_seconds() != 0:
        raise ChamberSafetyError("Current time must be UTC")
    if end <= start or not start <= current <= end or end - start > MAX_VALIDITY:
        raise ChamberSafetyError("Emulator enrollment expired, premature or overlong")
    firmware = data["firmware_sha256"]
    if firmware is not None and not isinstance(firmware, str):
        raise ChamberSafetyError("Invalid emulator firmware SHA-256")
    return EmulatorAuthorization(
        chamber_id=data["chamber_id"],
        address=data["address"],
        expected_serial=data["expected_serial"],
        expected_model=data["expected_model"],
        temperature_min_c=float(data["temperature_min_c"]),
        temperature_max_c=float(data["temperature_max_c"]),
        valid_until_utc=end,
        operator=data["operator"].strip(),
        approval_reference=data["approval_reference"].strip(),
        enrollment_sha256=hashlib.sha256(canonical).hexdigest(),
        firmware_sha256=firmware,
    )


def emulator_authorization_from_env(
    env: Mapping[str, str], *, now_utc: datetime | None = None,
) -> EmulatorAuthorization | None:
    """None when no emulator setting is present; otherwise a verified record."""
    present = {key: env.get(key, "").strip() for key in (
        ENROLLMENT_ENV, TRUSTED_KEY_ENV, TRUSTED_KEY_FILE_ENV, ACK_ENV)}
    if not any(present.values()):
        return None
    for key in _RELEASE_KEYS:
        if env.get(key, "").strip().lower() in {"1", "true", "yes", "on"}:
            raise ChamberSafetyError(
                "Emulator enrollment is forbidden in a release/production launch")
    conflicts = [key for key in _CONFLICT_KEYS if env.get(key, "").strip()]
    if conflicts:
        raise ChamberSafetyError(
            "Emulator enrollment is mutually exclusive with physical/lab/H02 settings: "
            + ", ".join(conflicts))
    if present[ACK_ENV] != ACK:
        raise ChamberSafetyError(f"{ACK_ENV} must be exactly {ACK!r}")
    if not present[ENROLLMENT_ENV]:
        raise ChamberSafetyError("Missing " + ENROLLMENT_ENV)
    path = Path(present[ENROLLMENT_ENV])
    _require_safe_regular_file(path, "emulator enrollment")
    try:
        signed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ChamberSafetyError("Emulator enrollment unavailable or malformed") from exc
    return verify_signed_enrollment(
        signed, trusted_public_key=_trusted_key(env), now_utc=now_utc)


def check_emulator_deployment(
    authorization: EmulatorAuthorization | None, policy, env: Mapping[str, str],
) -> None:
    """Keep bench-emulator I/O on a loopback server unless explicitly reviewed."""
    if authorization is None or not getattr(policy, "is_lan", False):
        return
    if env.get("CHAMBER_EMULATOR_ALLOW_LAN", "").strip() != "1":
        raise ChamberSafetyError(
            "Emulator enrollment over LAN requires CHAMBER_EMULATOR_ALLOW_LAN=1")
    if getattr(policy, "certfile", None) is None or getattr(policy, "keyfile", None) is None:
        raise ChamberSafetyError("Emulator enrollment over LAN requires TLS")
    if ipaddress.ip_address(policy.bind_host).is_unspecified:
        raise ChamberSafetyError(
            "Emulator enrollment over LAN requires a specific CHAMBER_BIND_HOST")
    for network in policy.client_networks:
        if network.prefixlen < (24 if network.version == 4 else 64):
            raise ChamberSafetyError(
                f"Emulator LAN allows client networks of /24 or narrower, not {network}")
