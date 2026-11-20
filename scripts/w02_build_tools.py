"""Offline, fail-closed SHA-256 verification of the W02 build-tool wheelhouse.

This preflight cannot certify wheel publisher provenance or resolve dependencies.
The subsequent pip --no-index --require-hashes install must also succeed.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re

LOCK_LINE = re.compile(
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)=="
    r"(?P<version>[0-9][A-Za-z0-9.!+_-]*)"
    r"\s+--hash=sha256:(?P<digest>[a-f0-9]{64})"
)


def normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def wheel_identity(filename: str) -> tuple[str, str]:
    if not filename.endswith(".whl"):
        raise ValueError(f"Non-wheel artifact: {filename}")
    fields = filename[:-4].split("-")
    if len(fields) not in (5, 6) or not all(fields):
        raise ValueError(f"Invalid wheel filename: {filename}")
    return normalized(fields[0]), fields[1]


def verify_build_wheelhouse(
    lock: Path, wheelhouse: Path, *, required: tuple[str, ...] = ()
) -> int:
    """Refuse extra, missing, duplicate, unpinned, symlinked or damaged wheels."""
    if lock.is_symlink() or not lock.is_file():
        raise ValueError("Build lock must be a regular nonsymlinked file")
    if wheelhouse.is_symlink() or not wheelhouse.is_dir():
        raise ValueError("Build wheelhouse must be a real directory")
    expected: dict[tuple[str, str], str] = {}
    for line in lock.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = LOCK_LINE.fullmatch(line)
        if not match:
            raise ValueError("Build lock requires exact version and SHA-256 per line")
        identity = normalized(match["name"]), match["version"]
        if any(name == identity[0] for name, _ in expected):
            raise ValueError("Duplicate build distribution in lock")
        expected[identity] = match["digest"]
    if not expected:
        raise ValueError("Build lock is empty")
    for requirement in required:
        if "==" in requirement:
            name, version = requirement.split("==", 1)
            if (normalized(name), version) not in expected:
                raise ValueError(f"Build lock lacks required version: {requirement}")
        elif normalized(requirement) not in {n for n, _ in expected}:
            raise ValueError(f"Build lock lacks required distributions: {requirement}")
    seen: set[tuple[str, str]] = set()
    for artifact in wheelhouse.iterdir():
        if artifact.is_symlink() or not artifact.is_file():
            raise ValueError("Build wheelhouse contains symlink/non-file entry")
        identity = wheel_identity(artifact.name)
        if identity in seen:
            raise ValueError("Duplicate wheel for build distribution")
        seen.add(identity)
        if identity not in expected:
            raise ValueError(f"Unexpected build wheel: {artifact.name}")
        sha = hashlib.sha256()
        with artifact.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                sha.update(chunk)
        if sha.hexdigest() != expected[identity]:
            raise ValueError(f"Build wheel SHA-256 mismatch: {artifact.name}")
    if seen != set(expected):
        raise ValueError(f"Missing build wheels: {sorted(set(expected) - seen)}")
    return len(expected)


def main() -> int:
    parser = argparse.ArgumentParser(description="W02 build wheelhouse preflight")
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--require", action="append", default=[])
    args = parser.parse_args()
    count = verify_build_wheelhouse(
        args.lock, args.wheelhouse, required=tuple(args.require))
    print(f"Verified {count} SHA-256-locked build wheels; no extras")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
