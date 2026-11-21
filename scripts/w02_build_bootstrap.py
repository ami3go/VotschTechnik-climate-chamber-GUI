"""Bootstrap the reviewed W02 Windows build-tool wheelhouse using stdlib only.

This helper performs no dependency resolution.  It accepts only the exact
files.pythonhosted.org wheel URLs and SHA-256 values committed in the reviewed
manifest, stages every artifact, and publishes the wheelhouse only after the
complete inventory verifies.  The hydrated tools are then installed by pip
with ``--no-index --require-hashes``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import urlsplit
from urllib.request import urlopen

SHA256 = re.compile(r"^[0-9a-f]{64}$")
PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;]+)$")
WHEEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*\.whl$")


class BootstrapError(ValueError):
    """A reviewed build-closure defect; always fail closed."""


def normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def canonical_sha256(path: Path) -> str:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def input_pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        match = PIN.fullmatch(line)
        if not match:
            raise BootstrapError("build input is not exactly pinned: " + line)
        name, version = match.groups()
        key = normalise(name)
        if key in pins:
            raise BootstrapError("duplicate build input: " + name)
        pins[key] = version
    if not pins:
        raise BootstrapError("build input is empty")
    return pins


def lock_pins(path: Path) -> dict[tuple[str, str], str]:
    pins: dict[tuple[str, str], str] = {}
    pending: tuple[str, str] | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith("\\"):
            match = PIN.fullmatch(line[:-1].strip())
            if not match or pending is not None:
                raise BootstrapError("malformed build lock requirement")
            pending = (normalise(match.group(1)), match.group(2))
            continue
        if pending is None or not line.startswith("--hash=sha256:"):
            raise BootstrapError("malformed build lock hash")
        digest = line.removeprefix("--hash=sha256:")
        if not SHA256.fullmatch(digest) or pending in pins:
            raise BootstrapError("invalid or duplicate build lock entry")
        pins[pending] = digest
        pending = None
    if pending is not None or not pins:
        raise BootstrapError("incomplete or empty build lock")
    return pins


def reviewed_artifacts(requirements: Path, lock: Path, manifest: Path) -> list[dict[str, str]]:
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise BootstrapError("build manifest is unreadable") from exc
    if (not isinstance(payload, dict) or payload.get("schema") != 1
            or payload.get("target") != "win_amd64-cp312"
            or payload.get("platform") != ["win_amd64"]
            or payload.get("python_tag") != "cp312"
            or payload.get("requirements") != requirements.name
            or payload.get("requirements_sha256") != canonical_sha256(requirements)):
        raise BootstrapError("build manifest identity/input mismatch")
    inputs = input_pins(requirements)
    locked = lock_pins(lock)
    records = payload.get("artifacts")
    if not isinstance(records, list) or len(records) != len(locked):
        raise BootstrapError("build manifest and lock have different inventories")
    seen: set[tuple[str, str]] = set()
    filenames: set[str] = set()
    artifacts: list[dict[str, str]] = []
    for raw in records:
        if not isinstance(raw, dict):
            raise BootstrapError("invalid build artifact record")
        item = {key: raw.get(key) for key in ("name", "version", "filename", "sha256", "url")}
        if not all(isinstance(value, str) and value for value in item.values()):
            raise BootstrapError("incomplete build artifact record")
        key = (normalise(item["name"]), item["version"])
        filename = item["filename"]
        source = urlsplit(item["url"])
        if (key in seen or filename in filenames or locked.get(key) != item["sha256"]
                or not SHA256.fullmatch(item["sha256"])
                or not WHEEL.fullmatch(filename)
                or source.scheme != "https" or source.netloc != "files.pythonhosted.org"
                or not source.path.startswith("/packages/")
                or not source.path.endswith("/" + filename)
                or source.query or source.fragment or source.username):
            raise BootstrapError("untrusted or inconsistent build artifact")
        seen.add(key)
        filenames.add(filename)
        artifacts.append(item)
    if seen != set(locked):
        raise BootstrapError("build manifest and lock disagree")
    if {name: version for name, version in seen} != inputs:
        raise BootstrapError("build closure is not the exact pinned input set")
    return artifacts


def hydrate(requirements: Path, lock: Path, manifest: Path, wheelhouse: Path) -> None:
    artifacts = reviewed_artifacts(requirements, lock, manifest)
    if wheelhouse.exists():
        if not wheelhouse.is_dir() or any(wheelhouse.iterdir()):
            raise BootstrapError("build wheelhouse must begin absent or empty")
        wheelhouse.rmdir()
    wheelhouse.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=wheelhouse.name + ".pending-",
                                  dir=wheelhouse.parent))
    try:
        for item in artifacts:
            target = stage / item["filename"]
            digest = hashlib.sha256()
            with urlopen(item["url"], timeout=60) as response, target.open("xb") as output:
                if response.geturl() != item["url"]:
                    raise BootstrapError("reviewed build artifact redirected")
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    output.write(chunk)
            if digest.hexdigest() != item["sha256"]:
                raise BootstrapError("reviewed build artifact hash mismatch: " + target.name)
        if {path.name for path in stage.iterdir()} != {item["filename"] for item in artifacts}:
            raise BootstrapError("staged build wheelhouse inventory mismatch")
        os.replace(stage, wheelhouse)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--requirements", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    args = parser.parse_args()
    try:
        hydrate(args.requirements, args.lock, args.manifest, args.wheelhouse)
    except BootstrapError as error:
        parser.error(str(error))
    print("Reviewed W02 build wheelhouse hydrated without dependency resolution")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
