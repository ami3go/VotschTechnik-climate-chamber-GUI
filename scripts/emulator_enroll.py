"""Create and sign a bench-emulator enrollment (operator tool).

This is NOT an H02 physical-profile permit and NOT a HIL PIN. It records one
operator decision: "this exact bench emulator, at this address, with this
envelope, may be used by the GUI for development until this UTC deadline".
The server still refuses release/production launches, real serials and any
combination with physical HIL/lab mode.

    python -m scripts.emulator_enroll keygen --private-key KEY --public-key-out PUB
    python -m scripts.emulator_enroll template --out spec.json \
        --chamber-id leo-emu --address 192.168.31.146 --serial SIMLEO0001
    (edit spec.json: operator, approval_reference, envelope, validity)
    python -m scripts.emulator_enroll sign --spec spec.json \
        --private-key KEY --out enrollment.json
    python -m scripts.emulator_enroll verify --enrollment enrollment.json \
        --public-key PUB
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chamber_web.hil.emulator import (  # noqa: E402
    ACK, EMULATOR_MODEL, MAX_ENVELOPE_SPAN_C, MAX_VALIDITY, SCOPE,
    SCHEMA_VERSION, verify_signed_enrollment,
)


def _read_key(path: Path) -> bytes:
    if path.is_symlink():
        raise SystemExit("Private key must not be a symlink")
    info = path.stat()
    if os.name == "posix" and info.st_mode & 0o077:
        raise SystemExit("Private key must be mode 0600 (no group/world access)")
    raw = base64.b64decode(path.read_text(encoding="ascii").strip(), validate=True)
    if len(raw) != 32:
        raise SystemExit("Ed25519 private key must be 32 raw bytes (base64)")
    return raw


def _write_new(path: Path, text: str, *, secret: bool = False) -> None:
    if path.exists():
        raise SystemExit(f"Refusing to overwrite existing file: {path}")
    path.write_text(text, encoding="ascii" if secret else "utf-8")
    if os.name == "posix":
        # Umask 0 would otherwise create 0666 files, which the server rejects
        # for group/world writability. Keys stay 0600; public records 0644.
        path.chmod(0o600 if secret else 0o644)


def _canonical(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def keygen(args) -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private = Ed25519PrivateKey.generate()
    raw_private = private.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
        serialization.NoEncryption())
    raw_public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    _write_new(Path(args.private_key),
               base64.b64encode(raw_private).decode("ascii") + "\n", secret=True)
    _write_new(Path(args.public_key_out),
               base64.b64encode(raw_public).decode("ascii") + "\n")
    print("Wrote private key (keep offline) and public key.")


def template(args) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    spec = {
        "schema_version": SCHEMA_VERSION,
        "scope": SCOPE,
        "chamber_id": args.chamber_id,
        "backend_id": "votsch_emulator",
        "address": args.address,
        "expected_serial": args.serial,
        "expected_model": EMULATOR_MODEL,
        "temperature_min_c": args.min_c,
        "temperature_max_c": args.max_c,
        "valid_from_utc": now.isoformat().replace("+00:00", "Z"),
        "valid_until_utc": (now + timedelta(hours=args.valid_hours))
        .isoformat().replace("+00:00", "Z"),
        "operator": "REPLACE_ME",
        "approval_reference": "REPLACE_ME",
        "isolated_network_ack": True,
        "firmware_sha256": args.firmware_sha256,
    }
    _write_new(Path(args.out), json.dumps(spec, indent=2) + "\n")
    print(f"Wrote template {args.out}. Edit every REPLACE_ME and all limits.")


def sign(args) -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    spec_path = Path(args.spec)
    if spec_path.is_symlink():
        raise SystemExit("Spec must not be a symlink")
    data = json.loads(spec_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("Spec must be a JSON object")
    if data.get("operator") == "REPLACE_ME" or data.get("approval_reference") == "REPLACE_ME":
        raise SystemExit("Refusing to sign a template: replace operator/approval_reference")
    now = datetime.now(timezone.utc)
    print(json.dumps(data, indent=2, sort_keys=True))
    print("\nThis signs a BENCH EMULATOR enrollment, not a physical chamber permit.")
    if not sys.stdin.isatty():
        raise SystemExit("Signing requires an interactive terminal")
    if input("Type ENROLL to sign exactly this record: ").strip() != "ENROLL":
        raise SystemExit("Not signed")
    private = Ed25519PrivateKey.from_private_bytes(_read_key(Path(args.private_key)))
    signature = private.sign(_canonical(data))
    record = {
        "enrollment": data,
        "signature_base64": base64.b64encode(signature).decode("ascii"),
    }
    # Verify before writing, with the public half derived from the private key.
    from cryptography.hazmat.primitives import serialization
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    verify_signed_enrollment(record, trusted_public_key=public, now_utc=now)
    _write_new(Path(args.out), json.dumps(record, indent=2) + "\n")
    print(f"Wrote signed enrollment {args.out}")


def verify(args) -> None:
    path = Path(args.enrollment)
    if path.is_symlink():
        raise SystemExit("Enrollment must not be a symlink")
    if os.name == "posix" and path.stat().st_mode & 0o022:
        raise SystemExit("Enrollment must not be group/world writable")
    public = base64.b64decode(
        Path(args.public_key).read_text(encoding="ascii").strip(), validate=True)
    authorization = verify_signed_enrollment(
        json.loads(path.read_text(encoding="utf-8")), trusted_public_key=public)
    print(f"VALID until {authorization.valid_until_utc.isoformat()} "
          f"serial={authorization.expected_serial} "
          f"address={authorization.address} "
          f"sha256={authorization.enrollment_sha256}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("keygen")
    p.add_argument("--private-key", required=True)
    p.add_argument("--public-key-out", required=True)
    p.set_defaults(func=keygen)

    p = sub.add_parser("template")
    p.add_argument("--out", required=True)
    p.add_argument("--chamber-id", required=True)
    p.add_argument("--address", required=True)
    p.add_argument("--serial", required=True)
    p.add_argument("--min-c", type=float, default=15.0)
    p.add_argument("--max-c", type=float, default=35.0)
    p.add_argument("--valid-hours", type=int, default=24)
    p.add_argument("--firmware-sha256", default=None)
    p.set_defaults(func=template)

    p = sub.add_parser("sign")
    p.add_argument("--spec", required=True)
    p.add_argument("--private-key", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=sign)

    p = sub.add_parser("verify")
    p.add_argument("--enrollment", required=True)
    p.add_argument("--public-key", required=True)
    p.set_defaults(func=verify)

    args = parser.parse_args()
    if args.command == "template":
        if args.valid_hours <= 0 or args.valid_hours > MAX_VALIDITY.total_seconds() / 3600:
            raise SystemExit("valid-hours must be within the enrollment maximum")
        if args.max_c - args.min_c > MAX_ENVELOPE_SPAN_C:
            raise SystemExit("Template envelope span is too wide")
        if not args.serial.startswith("SIM"):
            raise SystemExit("Emulator serial must start with SIM")
    args.func(args)


if __name__ == "__main__":
    main()
