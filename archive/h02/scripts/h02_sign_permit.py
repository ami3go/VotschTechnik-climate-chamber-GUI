"""Create and sign an H02 supervised physical-profile permit (site approver tool).

The permit is the site's written approval for ONE profile on ONE chamber. This
tool only records a decision a person has made: it never invents limits or keys,
refuses placeholder values, and signs only after the signer reads the full
permit and types SIGN at an interactive terminal. The private key never leaves
the file the signer names; keep it off the server PC when practical.

    python -m scripts.h02_sign_permit keygen --private-key KEY --public-key-out PUB
    python -m scripts.h02_sign_permit template --out spec.json --chamber-id ID \\
        --serial SERIAL [--profile-id P --revision N]
    (edit spec.json: every REPLACE_ME and every limit is the signer's decision)
    python -m scripts.h02_sign_permit sign --spec spec.json --private-key KEY --out permit.json
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chamber_web.hil.commits import detect_driver_commit, detect_gui_commit  # noqa: E402
from chamber_web.hil.profile_admission import (  # noqa: E402
    AdmissionDenied, verify_signed_permit,
)

PLACEHOLDER = "REPLACE_ME"
# Proposed starting limits for a short, narrow first test. They are NOT approved
# values: the signer reviews each one before typing SIGN.
PROPOSED_WATCHDOG = {
    "schema_version": 1, "controller_command_timeout_s": 10.0,
    "readback_deadline_s": 5.0, "max_telemetry_gap_s": 5.0,
    "profile_step_deadline_s": 600.0, "whole_profile_deadline_s": 900.0,
    "recorder_heartbeat_s": 5.0, "process_heartbeat_s": 5.0,
    "supervisor_heartbeat_s": 5.0, "cleanup_timeout_s": 10.0,
    "stop_verification_timeout_s": 30.0,
}


def _canonical(data) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _write_private(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags, 0o600)  # never overwrite an existing key
    try:
        os.write(descriptor, payload)
    finally:
        os.close(descriptor)


def keygen(args) -> int:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(serialization.Encoding.Raw,
                                serialization.PrivateFormat.Raw,
                                serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.Raw,
                                           serialization.PublicFormat.Raw)
    _write_private(args.private_key, base64.b64encode(private) + b"\n")
    encoded = base64.b64encode(public).decode("ascii")
    if args.public_key_out:
        args.public_key_out.write_text(encoded + "\n", encoding="utf-8")
    print("Private key written (mode 0600):", args.private_key)
    print("Public key (set as CHAMBER_H02_TRUSTED_KEY):", encoded)
    return 0


def template(args) -> int:
    profile_hash = PLACEHOLDER
    if args.profile_id and args.revision:
        from chamber_web.pages.profiles import default_database_path
        from chamber_web.persistence.profiles import ProfileStore
        record = ProfileStore(default_database_path()).get_revision(
            args.chamber_id, args.profile_id, revision=args.revision)
        profile_hash = record.sha256
    now = datetime.now(timezone.utc).replace(microsecond=0)
    spec = {
        "schema_version": 1, "scope": "H02_SUPERVISED_PHYSICAL_PROFILE",
        "site_method": PLACEHOLDER, "approval_reference": PLACEHOLDER,
        "chamber_id": args.chamber_id, "serial_number": args.serial,
        "profile_id": args.profile_id or PLACEHOLDER,
        "profile_revision_sha256": profile_hash,
        "gui_commit": detect_gui_commit() or PLACEHOLDER,
        "driver_commit": detect_driver_commit() or PLACEHOLDER,
        "operator": PLACEHOLDER, "witness": PLACEHOLDER,
        "specimen_restrictions": PLACEHOLDER,
        "temperature_min_c": PLACEHOLDER, "temperature_max_c": PLACEHOLDER,
        "valid_from_utc": now.isoformat().replace("+00:00", "Z"),
        "valid_until_utc": (now + timedelta(hours=8)).isoformat().replace("+00:00", "Z"),
        "watchdog": dict(PROPOSED_WATCHDOG),
    }
    args.out.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    print("Template written:", args.out)
    print(f"Fill every {PLACEHOLDER}; review every limit; then run the sign command.")
    return 0


def _placeholders(value, path="") -> list[str]:
    if isinstance(value, dict):
        return [hit for key, item in value.items()
                for hit in _placeholders(item, f"{path}{key}.")]
    return [path.rstrip(".")] if isinstance(value, str) and PLACEHOLDER in value else []


def sign(args) -> int:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("Refusing: signing needs an interactive terminal (no pipes or automation).")
        return 2
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    missing = _placeholders(spec)
    if missing:
        print("Refusing: unfilled placeholders:", ", ".join(missing))
        return 2
    key = Ed25519PrivateKey.from_private_bytes(
        base64.b64decode(args.private_key.read_text(encoding="utf-8").strip(), validate=True))
    public = key.public_key().public_bytes(serialization.Encoding.Raw,
                                           serialization.PublicFormat.Raw)
    envelope = {"permit": spec,
                "signature_base64": base64.b64encode(key.sign(_canonical(spec))).decode()}
    try:  # same verifier the server uses, so a bad permit is caught before it is issued
        verify_signed_permit(envelope, trusted_site_public_key=public)
    except AdmissionDenied as exc:
        print("Refusing: permit would not be accepted by the server:", exc)
        return 2
    print("=" * 72)
    print("YOU ARE APPROVING A PHYSICAL CHAMBER RUN. Review every line:")
    print(json.dumps(spec, indent=2))
    print("Public key:", base64.b64encode(public).decode("ascii"))
    print("=" * 72)
    if input("Type SIGN to approve and write the permit: ").strip() != "SIGN":
        print("Not signed.")
        return 1
    args.out.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
    print("Signed permit written:", args.out)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    gen = commands.add_parser("keygen")
    gen.add_argument("--private-key", required=True, type=Path)
    gen.add_argument("--public-key-out", type=Path)
    tpl = commands.add_parser("template")
    tpl.add_argument("--out", required=True, type=Path)
    tpl.add_argument("--chamber-id", required=True)
    tpl.add_argument("--serial", required=True)
    tpl.add_argument("--profile-id")
    tpl.add_argument("--revision", type=int)
    sgn = commands.add_parser("sign")
    sgn.add_argument("--spec", required=True, type=Path)
    sgn.add_argument("--private-key", required=True, type=Path)
    sgn.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    return {"keygen": keygen, "template": template, "sign": sign}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
