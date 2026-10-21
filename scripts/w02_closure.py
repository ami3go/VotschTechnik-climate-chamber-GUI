"""W02 air-gap dependency closure: hash-locked, platform-pinned, offline-installable.

An unsigned hash list is not an authenticated release (see
``scripts/w02_release.py``). This module is the other half of that story: it
produces and verifies the *complete* transitive dependency closure of the
frozen Windows runtime, pinned by SHA-256, so that the target can be installed
with no index access and no runtime download.

Design rules that follow from the W02 release ledger
(``docs/W02_OFFLINE_RELEASE.md``):

* The closure is resolved **natively on the target platform**. Cross-platform
  marker evaluation (``pip --platform``) evaluates environment markers against
  the *build* interpreter, which silently produces a wrong closure on Windows
  (for example a Linux-only ``uvloop`` dependency). A wrong closure is worse
  than no closure, so the tool refuses to resolve for a foreign platform.
* Every artifact is a wheel. An sdist would require a compiler on the target
  and cannot be hash-verified after a build, so sdists are refused.
* Every artifact is pinned by SHA-256. A closure entry without a hash is
  refused: an unhashed entry is exactly the gap this package exists to close.
* The closure file is pip ``--require-hashes`` compatible so the *same* file
  proves the offline installation.
* The runtime SBOM is derived from the **closure**, never from the build
  environment. A build host contains build-only tools (PyInstaller, pip,
  setuptools) that are not shipped, and a SBOM of those is not a runtime
  inventory.

This is build-host tooling. It never connects to a chamber, never enables
physical I/O and never certifies a release: the disconnected clean-Windows
acceptance, the site publisher key and the independent review remain OPEN
(Stage 2 S2-04 and the W02 release ledger).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

SCHEMA = 1
LOCK_NAME = "requirements-w02-runtime.lock"
MANIFEST_NAME = "w02-closure-manifest.json"

#: Supported closure targets. A target is ``(key, platform tag, python tag)``.
TARGETS: dict[str, tuple[tuple[str, ...], str]] = {
    "win_amd64-cp312": (("win_amd64",), "cp312"),
    "win_amd64-cp310": (("win_amd64",), "cp310"),
}

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+!_-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
# pip wheel filename: name-version(-build)?-pytag-abitag-platformtag.whl
_WHEEL = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)-(?P<version>[A-Za-z0-9][A-Za-z0-9.+!_]*)"
    r"(-(?P<build>[0-9][A-Za-z0-9._]*))?"
    r"-(?P<python>[A-Za-z0-9_.]+)-(?P<abi>[A-Za-z0-9_.]+)-(?P<platform>[A-Za-z0-9_.]+)\.whl$"
)


class ClosureError(ValueError):
    """A closure defect that must fail closed, never be warned about."""


@dataclass(frozen=True)
class Artifact:
    """One pinned wheel in the closure."""

    name: str
    version: str
    filename: str
    sha256: str
    url: str
    requires_python: str
    license: str

    @property
    def requirement(self) -> str:
        return f"{self.name}=={self.version}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _normalise(name: str) -> str:
    """PEP 503 normalization, used only to compare names."""
    return re.sub(r"[-_.]+", "-", name).lower()


# --------------------------------------------------------------------------
# Lock file
# --------------------------------------------------------------------------

def render_lock(artifacts: list[Artifact], *, target: str, python_version: str,
                requirements_sha256: str) -> str:
    """Render a pip ``--require-hashes`` compatible, fully pinned closure."""
    lines = [
        "# W02 frozen runtime dependency closure - generated, do not hand-edit.",
        "#",
        "# Install offline with:",
        "#   pip install --no-index --find-links <wheelhouse> --require-hashes \\",
        "#       --target <target-dir> -r " + LOCK_NAME,
        "#",
        f"# target: {target}  python: {python_version}",
        f"# requirements sha256: {requirements_sha256}",
        "# Every entry is a wheel pinned by SHA-256. Build on the target platform.",
        "",
    ]
    for artifact in sorted(artifacts, key=lambda item: _normalise(item.name)):
        lines.append(f"{artifact.requirement} \\")
        lines.append(f"    --hash=sha256:{artifact.sha256}")
    return "\n".join(lines) + "\n"


def parse_lock(text: str) -> list[tuple[str, str, str]]:
    """Parse the closure file into ``(name, version, sha256)`` triples.

    Strict by design: an unpinned requirement, a missing hash, a duplicate
    entry or an unexpected token is a refusal, not a warning.
    """
    entries: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    pending: tuple[str, str] | None = None
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if pending is not None:
            match = re.fullmatch(r"--hash=sha256:([0-9a-f]{64})", line)
            if match is None:
                raise ClosureError(f"line {number}: malformed hash line")
            entries.append((pending[0], pending[1], match.group(1)))
            pending = None
            continue
        match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9.+!_]*)"
                             r"(?:\s*\\\s*)?", line)
        if match is None:
            raise ClosureError(f"line {number}: requirement is not pinned with '=='")
        name, version = match.group(1), match.group(2)
        if not _NAME.match(name):
            raise ClosureError(f"line {number}: invalid distribution name")
        if not _VERSION.match(version):
            raise ClosureError(f"line {number}: invalid version")
        key = _normalise(name)
        if key in seen:
            raise ClosureError(f"line {number}: duplicate distribution {name}")
        seen.add(key)
        pending = (name, version)
    if pending is not None:
        raise ClosureError("closure entry without a hash: " + pending[0])
    if not entries:
        raise ClosureError("closure file is empty")
    return entries


# --------------------------------------------------------------------------
# Wheel handling
# --------------------------------------------------------------------------

def wheel_metadata(path: Path) -> dict[str, str]:
    """Read the core metadata of a wheel without installing it."""
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist()
                 if name.endswith(".dist-info/METADATA")]
        if len(names) != 1:
            raise ClosureError("wheel has no unique .dist-info/METADATA: " + path.name)
        with archive.open(names[0]) as handle:
            payload = handle.read().decode("utf-8", "replace")
    fields: dict[str, str] = {}
    for line in payload.splitlines():
        if not line.strip():
            break  # headers end at the first blank line
        if ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip().lower()] = value.strip()
    return fields


def wheel_license(path: Path) -> str:
    """Best-effort declared license, from the wheel metadata or classifiers."""
    fields = wheel_metadata(path)
    declared = fields.get("license", "").strip()
    if declared and declared.lower() != "unknown":
        return declared
    for line in fields.get("classifier", "").splitlines():
        if line.lower().startswith("license ::"):
            return line.split("::")[-1].strip()
    return "NOASSERTION"


def parse_wheel_filename(filename: str) -> tuple[str, str, str, str, str]:
    """Return ``(name, version, python tag, abi tag, platform tag)``."""
    match = _WHEEL.match(filename)
    if match is None:
        raise ClosureError("not a wheel filename: " + filename)
    return (match.group("name"), match.group("version"), match.group("python"),
            match.group("abi"), match.group("platform"))


def _platform_component_allowed(component: str, allowed: tuple[str, ...]) -> bool:
    """A platform tag may be compound (``manylinux1_x86_64.manylinux_2_28``).

    Every component must be acceptable for the target, so a Linux artifact can
    never satisfy a Windows closure.
    """
    for tag in allowed:
        if component == tag or component.startswith(tag):
            return True
    return False


def _cp_tag(tag: str) -> tuple[int, int] | None:
    """``cp312`` -> ``(3, 12)``; ``None`` for a non-CPython tag."""
    match = re.fullmatch(r"cp(\d)(\d+)", tag)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def check_wheel_platform(filename: str, *, platform_tags: tuple[str, ...],
                         python_tag: str) -> None:
    """Refuse a wheel that does not belong to the pinned target.

    A pure-Python wheel (``py3-none-any``) is platform independent and belongs
    to every target; it is accepted with its own tag rules. Any other wheel
    must match the pinned interpreter and platform, so a Linux or a
    different-Python artifact can never enter the closure. The stable ABI
    (``abi3``) is accepted for an interpreter at or above the wheel's floor,
    because that is exactly what the stable ABI guarantees.
    """
    _, _, wheel_python, wheel_abi, wheel_platform = parse_wheel_filename(filename)
    if wheel_platform == "any":
        if wheel_abi != "none":
            raise ClosureError(
                f"{filename}: pure-Python wheel must use the 'none' ABI tag")
        if wheel_python not in ("py3", "py2.py3"):
            raise ClosureError(
                f"{filename}: unsupported pure-Python tag {wheel_python}")
        return
    components = wheel_platform.split(".")
    if not all(_platform_component_allowed(part, platform_tags)
               for part in components):
        raise ClosureError(
            f"{filename}: platform tag {wheel_platform!r} is not one of "
            + ", ".join(repr(tag) for tag in platform_tags))
    if wheel_abi == python_tag:
        if wheel_python != python_tag:
            raise ClosureError(
                f"{filename}: python tag {wheel_python} does not match "
                f"the pinned {python_tag}")
        return
    if wheel_abi == "abi3":
        floor = _cp_tag(wheel_python)
        target = _cp_tag(python_tag)
        if floor is None or target is None or floor > target:
            raise ClosureError(
                f"{filename}: stable-ABI wheel requires CPython "
                f"{wheel_python} or newer, not {python_tag}")
        return
    raise ClosureError(
        f"{filename}: python/abi tags {wheel_python}-{wheel_abi} "
        f"are not {python_tag}")


# --------------------------------------------------------------------------
# Wheelhouse verification
# --------------------------------------------------------------------------

def verify_wheelhouse(entries: list[tuple[str, str, str]], wheelhouse: Path, *,
                       platform_tags: tuple[str, ...], python_tag: str) -> None:
    """Fail closed unless the wheelhouse is exactly the locked closure.

    Detects a damaged wheel (hash mismatch), a missing wheel and an extra
    file. An extra file is a refusal, not a warning: an unverified artifact in
    the closure directory is exactly what an air-gap install must not accept.
    """
    if not wheelhouse.is_dir():
        raise ClosureError("wheelhouse directory is missing: " + str(wheelhouse))
    digests: dict[str, str] = {}
    wheels: dict[tuple[str, str], str] = {}
    unexpected: list[str] = []
    for path in sorted(wheelhouse.iterdir()):
        if not path.is_file():
            continue
        if not path.name.endswith(".whl"):
            unexpected.append(path.name)
            continue
        check_wheel_platform(path.name, platform_tags=platform_tags,
                             python_tag=python_tag)
        name, version, _, _, _ = parse_wheel_filename(path.name)
        key = (_normalise(name), version)
        if key in wheels:
            raise ClosureError(
                "duplicate artifact for " + name + "==" + version + ": "
                + wheels[key] + " and " + path.name)
        wheels[key] = path.name
        digests[path.name] = sha256_file(path)
    missing: list[str] = []
    damaged: list[str] = []
    matched: set[str] = set()
    for name, version, digest in entries:
        filename = wheels.get((_normalise(name), version))
        if filename is None:
            missing.append(name + "==" + version)
            continue
        matched.add(filename)
        if digests[filename] != digest:
            damaged.append(filename)
    extra = sorted(set(wheels.values()) - matched) + unexpected
    if missing or extra or damaged:
        raise ClosureError(
            "wheelhouse does not match the closure: "
            f"missing={missing} unexpected={extra} damaged={damaged}")


def verify_manifest(artifacts: list[Artifact], manifest_path: Path) -> None:
    """Check a closure manifest against the artifacts it claims to describe."""
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("schema") != SCHEMA:
        raise ClosureError("unsupported closure manifest schema")
    recorded = payload.get("artifacts")
    if not isinstance(recorded, list) or not recorded:
        raise ClosureError("closure manifest has no artifacts")
    claimed = {item["filename"]: item for item in recorded}
    for artifact in artifacts:
        item = claimed.get(artifact.filename)
        if item is None:
            raise ClosureError("closure manifest omits " + artifact.filename)
        if item.get("sha256") != artifact.sha256:
            raise ClosureError("closure manifest hash mismatch: " + artifact.filename)
        if _normalise(str(item.get("name", ""))) != _normalise(artifact.name):
            raise ClosureError("closure manifest name mismatch: " + artifact.filename)


# --------------------------------------------------------------------------
# Runtime SBOM and license inventory
# --------------------------------------------------------------------------

def render_sbom(artifacts: list[Artifact], *, version: str, target: str,
                python_version: str) -> dict:
    """CycloneDX 1.5 inventory of the *runtime closure*.

    The scope property says so explicitly: this is the locked runtime closure
    of the frozen application, not the build host's environment.
    """
    components = []
    for artifact in sorted(artifacts, key=lambda item: _normalise(item.name)):
        component = {
            "type": "library",
            "name": artifact.name,
            "version": artifact.version,
            "bom-ref": f"w02-runtime:{_normalise(artifact.name)}:{artifact.version}",
            "purl": f"pkg:pypi/{_normalise(artifact.name)}@{artifact.version}",
            "hashes": [{"alg": "SHA-256", "content": artifact.sha256}],
        }
        if artifact.license and artifact.license != "NOASSERTION":
            component["licenses"] = [{"license": {"name": artifact.license}}]
        if artifact.requires_python:
            component["properties"] = [
                {"name": "w02:requires-python", "value": artifact.requires_python}]
        components.append(component)
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "ClimateChamber-Web-Windows-x64",
                "version": version,
            },
            "properties": [
                {"name": "w02:inventory-scope",
                 "value": "locked-runtime-closure"},
                {"name": "w02:target", "value": target},
                {"name": "w02:python", "value": python_version},
            ],
        },
        "components": components,
    }


def render_license_rows(artifacts: list[Artifact]) -> list[tuple[str, str, str, str]]:
    """License inventory of the runtime closure.

    ``approval`` stays ``REVIEW_REQUIRED`` for every row. This tool cannot
    approve a license for redistribution; only a qualified reviewer and the
    site release register can do that.
    """
    rows = []
    for artifact in sorted(artifacts, key=lambda item: _normalise(item.name)):
        rows.append((artifact.name, artifact.version, artifact.license or "NOASSERTION",
                     "REVIEW_REQUIRED"))
    return rows


# --------------------------------------------------------------------------
# Build (connected build host only)
# --------------------------------------------------------------------------

def _pip_run(arguments: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pip", *arguments],
        cwd=str(cwd) if cwd else None, capture_output=True, text=True, check=False,
    )


def resolve_closure(requirements: Path, *, python_version: str) -> list[dict]:
    """Resolve the runtime closure with pip and return the install report.

    Runs natively on the target interpreter: pip evaluates environment markers
    against the running interpreter, so a foreign-platform resolution would
    silently produce the wrong closure.
    """
    with tempfile.TemporaryDirectory(prefix="w02-closure-") as scratch:
        report = Path(scratch) / "resolution.json"
        completed = _pip_run([
            "install", "--dry-run", "--ignore-installed", "--report", str(report),
            "--only-binary=:all:", "--no-cache-dir", "-r", str(requirements),
        ])
        if completed.returncode != 0 or not report.exists():
            raise ClosureError(
                "pip could not resolve the runtime closure: "
                + (completed.stderr.strip()[-2000:] or "no report produced"))
        return json.loads(report.read_text(encoding="utf-8")).get("install", [])


def download_artifacts(report: list[dict], wheelhouse: Path, *,
                        platform_tags: tuple[str, ...], python_tag: str) -> list[Artifact]:
    """Download every resolved wheel into the wheelhouse and verify it."""
    wheelhouse.mkdir(parents=True, exist_ok=True)
    artifacts: list[Artifact] = []
    for item in sorted(report, key=lambda entry: _normalise(entry["metadata"]["name"])):
        url = item["download_info"]["url"]
        expected = item["download_info"].get("archive_info", {}).get("hashes", {})
        digest = expected.get("sha256", "")
        if not _SHA256.match(digest):
            raise ClosureError("resolved artifact has no sha256: " + url)
        filename = url.split("/")[-1].split("#")[0]
        if not filename.endswith(".whl"):
            raise ClosureError("resolved artifact is not a wheel: " + filename)
        check_wheel_platform(filename, platform_tags=platform_tags,
                             python_tag=python_tag)
        target = wheelhouse / filename
        completed = _pip_run(["download", "--no-deps", "--no-cache-dir",
                               "--dest", str(wheelhouse), url])
        if completed.returncode != 0 or not target.exists():
            raise ClosureError("could not download " + url + ": "
                               + completed.stderr.strip()[-1000:])
        actual = sha256_file(target)
        if actual != digest:
            target.unlink(missing_ok=True)
            raise ClosureError("downloaded artifact hash mismatch: " + filename)
        fields = wheel_metadata(target)
        artifacts.append(Artifact(
            name=str(fields.get("name", "")),
            version=str(fields.get("version", "")),
            filename=filename,
            sha256=actual,
            url=url,
            requires_python=str(fields.get("requires-python", "")),
            license=wheel_license(target),
        ))
    return artifacts


def install_offline(wheelhouse: Path, lock: Path, target: Path) -> None:
    """Prove the closure installs with no index access at all.

    ``--no-index`` forbids the package index, ``--find-links`` restricts the
    source to the verified wheelhouse and ``--require-hashes`` makes pip
    reject any artifact whose SHA-256 does not match the lock. A missing or
    damaged wheel therefore fails the installation instead of silently
    reaching the network.
    """
    environment = dict(os.environ)
    environment.update({
        "PIP_NO_INDEX": "1",
        "PIP_NO_INPUT": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_RETRIES": "0",
        "PIP_TIMEOUT": "5",
    })
    completed = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-index",
         "--find-links", str(wheelhouse), "--require-hashes",
         "--no-cache-dir", "--target", str(target), "-r", str(lock)],
        capture_output=True, text=True, check=False, env=environment,
    )
    if completed.returncode != 0:
        raise ClosureError("offline installation failed: "
                           + completed.stderr.strip()[-2000:])


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------

def _write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="resolve and download the closure")
    build.add_argument("--requirements", type=Path, required=True)
    build.add_argument("--wheelhouse", type=Path, required=True)
    build.add_argument("--lock", type=Path, default=Path(LOCK_NAME))
    build.add_argument("--manifest", type=Path, default=Path(MANIFEST_NAME))
    build.add_argument("--target", default="win_amd64-cp312")
    build.add_argument("--version", default="0.0.0")

    verify = sub.add_parser("verify", help="verify a wheelhouse against a lock")
    verify.add_argument("--wheelhouse", type=Path, required=True)
    verify.add_argument("--lock", type=Path, required=True)
    verify.add_argument("--manifest", type=Path)
    verify.add_argument("--target", default="win_amd64-cp312")

    install = sub.add_parser("install", help="prove an offline installation")
    install.add_argument("--wheelhouse", type=Path, required=True)
    install.add_argument("--lock", type=Path, required=True)
    install.add_argument("--target-dir", type=Path, required=True)

    sbom = sub.add_parser("sbom", help="emit the runtime SBOM and licenses")
    sbom.add_argument("--lock", type=Path, required=True)
    sbom.add_argument("--manifest", type=Path, required=True)
    sbom.add_argument("--sbom-out", type=Path, required=True)
    sbom.add_argument("--licenses-out", type=Path, required=True)
    sbom.add_argument("--version", default="0.0.0")
    sbom.add_argument("--target", default="win_amd64-cp312")

    args = parser.parse_args(argv)

    if args.command == "build":
        if args.target not in TARGETS:
            raise ClosureError("unsupported target: " + args.target)
        platform_tags, python_tag = TARGETS[args.target]
        # The wheelhouse holds artifacts only. The lock and the manifest
        # describe the closure and must not be mixed into it, or the closure
        # verification could never match the directory exactly.
        wheelhouse = args.wheelhouse.resolve()
        for described in (args.lock, args.manifest):
            resolved = described.resolve()
            if resolved == wheelhouse or wheelhouse in resolved.parents:
                raise ClosureError(
                    "the closure lock and manifest must not be written inside "
                    "the wheelhouse: " + str(described))
        native = sys.platform == "win32" and "win_amd64" in platform_tags
        if not native:
            raise ClosureError(
                "the closure must be resolved natively on the target platform; "
                f"this host is {sys.platform}, not win_amd64")
        report = resolve_closure(args.requirements,
                                  python_version=python_tag)
        artifacts = download_artifacts(report, args.wheelhouse,
                                       platform_tags=platform_tags,
                                       python_tag=python_tag)
        if not artifacts:
            raise ClosureError("resolved closure is empty")
        requirements_hash = sha256_file(args.requirements)
        _write(args.lock, render_lock(artifacts, target=args.target,
                                      python_version=python_tag,
                                      requirements_sha256=requirements_hash))
        manifest = {
            "schema": SCHEMA,
            "target": args.target,
            "platform": list(platform_tags),
            "python_tag": python_tag,
            "release_version": args.version,
            "requirements": args.requirements.name,
            "requirements_sha256": requirements_hash,
            "artifacts": [
                {"name": item.name, "version": item.version,
                 "filename": item.filename, "sha256": item.sha256,
                 "url": item.url, "requires_python": item.requires_python,
                 "license": item.license}
                for item in artifacts],
        }
        _write(args.manifest, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        print(f"Closure built: {len(artifacts)} wheels -> {args.wheelhouse}")
        return 0

    if args.command == "verify":
        if args.target not in TARGETS:
            raise ClosureError("unsupported target: " + args.target)
        platform_tags, python_tag = TARGETS[args.target]
        entries = parse_lock(args.lock.read_text(encoding="utf-8"))
        verify_wheelhouse(entries, args.wheelhouse, platform_tags=platform_tags,
                          python_tag=python_tag)
        if args.manifest:
            payload = json.loads(args.manifest.read_text(encoding="utf-8"))
            artifacts = [Artifact(
                name=str(item["name"]), version=str(item["version"]),
                filename=str(item["filename"]), sha256=str(item["sha256"]),
                url=str(item.get("url", "")), requires_python=str(item.get("requires_python", "")),
                license=str(item.get("license", ""))) for item in payload["artifacts"]]
            verify_manifest(artifacts, args.manifest)
        print(f"Closure verified against {args.lock}")
        return 0

    if args.command == "install":
        args.target_dir.mkdir(parents=True, exist_ok=True)
        install_offline(args.wheelhouse, args.lock, args.target_dir)
        print("Offline installation succeeded with --no-index --require-hashes")
        return 0

    if args.command == "sbom":
        payload = json.loads(args.manifest.read_text(encoding="utf-8"))
        artifacts = [Artifact(
            name=str(item["name"]), version=str(item["version"]),
            filename=str(item["filename"]), sha256=str(item["sha256"]),
            url=str(item.get("url", "")), requires_python=str(item.get("requires_python", "")),
            license=str(item.get("license", ""))) for item in payload["artifacts"]]
        verify_manifest(artifacts, args.manifest)
        entries = parse_lock(args.lock.read_text(encoding="utf-8"))
        locked = {(name, version): digest for name, version, digest in entries}
        for artifact in artifacts:
            if locked.get((artifact.name, artifact.version)) != artifact.sha256:
                raise ClosureError("lock and manifest disagree: " + artifact.filename)
        document = render_sbom(artifacts, version=args.version, target=args.target,
                               python_version=str(payload.get("python_tag", "")))
        _write(args.sbom_out, json.dumps(document, indent=2, sort_keys=True) + "\n")
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(("distribution", "version", "declared_license", "approval"))
        writer.writerows(render_license_rows(artifacts))
        _write(args.licenses_out, buffer.getvalue())
        print(f"Runtime SBOM written for {len(artifacts)} locked distributions")
        return 0

    raise ClosureError("unknown command")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ClosureError as error:
        print("W02 closure error:", error, file=sys.stderr)
        raise SystemExit(2) from error
