"""W02 offline release integrity and lifecycle tools. Build host: Python 3.12.

An unsigned hash list is NOT an authenticated release. Sign the canonical index
with an out-of-band provisioned Ed25519 private key; pin its public key at the
offline site independently of the archive.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import shutil

EXCLUDED = {"w02-release.json", "w02-release.sig"}
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.]+)?$")
SHA = re.compile(r"^[a-f0-9]{64}$")


def canonical(payload: dict) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")


def inventory(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Release contains symlink")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in EXCLUDED:
            continue
        with path.open("rb") as stream:
            files[relative] = hashlib.file_digest(stream, "sha256").hexdigest()
    return files


def validate_entries(entries: dict) -> None:
    if not isinstance(entries, dict) or not entries:
        raise ValueError("Empty/invalid release inventory")
    folded = set()
    for name, digest in entries.items():
        p = Path(name) if isinstance(name, str) else Path("")
        if (not isinstance(name, str) or not name or "\\" in name or ":" in name
                or name.startswith("/") or any(x in {"", ".", ".."} for x in name.split("/"))
                or p.is_absolute() or not isinstance(digest, str) or not SHA.fullmatch(digest)):
            raise ValueError("Unsafe release manifest entry")
        normalized = name.casefold()
        if normalized in folded:
            raise ValueError("Windows case-insensitive path collision")
        folded.add(normalized)


def sign(root: Path, version: str, key: Path, *, source_sha: str) -> None:
    if not VERSION.fullmatch(version) or not SHA.fullmatch(source_sha):
        raise ValueError("Version/source revision invalid")
    if not (root / "build-manifest.json").is_file():
        raise ValueError("Existing W01 build-manifest.json is mandatory")
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    private = load_pem_private_key(key.read_bytes(), password=None)
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    if not isinstance(private, Ed25519PrivateKey):
        raise ValueError("Ed25519 signing key required")
    payload = {"schema": 2, "version": version, "source_sha256": source_sha,
               "hardware_enabled": False, "platform": "windows-x64",
               "files": inventory(root)}
    (root / "w02-release.json").write_bytes(canonical(payload))
    (root / "w02-release.sig").write_text(
        base64.b64encode(private.sign(canonical(payload))).decode("ascii") + "\n",
        encoding="ascii")


def verify(root: Path, public_key: Path) -> dict:
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    key = load_pem_public_key(public_key.read_bytes())
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("Ed25519 verification key required")
    raw = (root / "w02-release.json").read_bytes()
    payload = json.loads(raw)
    if (not isinstance(payload, dict) or canonical(payload) != raw
            or set(payload) != {"schema", "version", "source_sha256",
                                "hardware_enabled", "platform", "files"}
            or payload["schema"] != 2 or payload["hardware_enabled"] is not False
            or payload["platform"] != "windows-x64"
            or not isinstance(payload["version"], str)
            or not VERSION.fullmatch(payload["version"])
            or not isinstance(payload["source_sha256"], str)
            or not SHA.fullmatch(payload["source_sha256"])):
        raise ValueError("Malformed/noncanonical release")
    validate_entries(payload["files"])
    signature = base64.b64decode((root / "w02-release.sig").read_text(encoding="ascii").strip(), validate=True)
    key.verify(signature, raw)
    current = inventory(root)
    if current != payload["files"]:
        raise ValueError("Release integrity mismatch (missing/modified/unexpected files)")
    from scripts.windows_manifest import verify_manifest
    verify_manifest(root, sidecars=frozenset(EXCLUDED))
    return payload


def stage_update(installed: Path, candidate: Path, public_key: Path, backup: Path) -> None:
    """Prepare rollback without modifying running binaries or touching user data.

    Operator must stop service, validate backups, and approve separately before
    moving a staged release into place. No automatic/online updater is supplied.
    """
    new = verify(candidate, public_key)
    old = verify(installed, public_key)
    if new["version"] == old["version"]:
        raise ValueError("Refuse same-version replacement")
    if tuple(map(int, new["version"].split("-")[0].split("."))) <= tuple(
            map(int, old["version"].split("-")[0].split("."))):
        raise ValueError("Downgrade is forbidden")
    if backup.exists():
        raise ValueError("Backup destination already exists")
    if candidate.resolve() == installed.resolve():
        raise ValueError("Update must be staged separately")
    temp = backup.with_name(backup.name + ".pending")
    if temp.exists():
        raise ValueError("Interrupted staging detected: inspect manually")
    shutil.copytree(installed, temp, symlinks=False)
    try:
        verify(temp, public_key)
        temp.replace(backup)
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="W02 signed offline release controls")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--sign", action="store_true")
    actions.add_argument("--verify", action="store_true")
    actions.add_argument("--stage-update", action="store_true")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--public-key", type=Path)
    parser.add_argument("--private-key", type=Path)
    parser.add_argument("--version")
    parser.add_argument("--source-sha")
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    if args.sign:
        if not (args.private_key and args.version and args.source_sha):
            parser.error("Signing requires private key, version and source SHA")
        sign(args.bundle, args.version, args.private_key, source_sha=args.source_sha)
    elif args.verify:
        if not args.public_key:
            parser.error("Verification requires trusted public key")
        verify(args.bundle, args.public_key)
    else:
        if not (args.public_key and args.candidate and args.backup):
            parser.error("Update staging requires trusted public key, candidate and backup")
        stage_update(args.bundle, args.candidate, args.public_key, args.backup)
    print("W02 release operation validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
