"""Create and validate an integrity manifest for the W01 Windows offline bundle.

This helper runs on the build machine; the target does not need Python.
W01 records installed dependencies but does not yet claim a hashed wheel lock.
"""
from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path
import sys


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def files_under(folder: Path) -> dict[str, str]:
    result = {}
    for path in sorted(folder.rglob("*")):
        if path.is_symlink():
            raise ValueError("Symlink in offline bundle: " + str(path))
        if path.is_file():
            name = path.relative_to(folder).as_posix()
            if name not in {"build-manifest.json", "SHA256SUMS.txt"}:
                result[name] = sha256(path)
    return result


def check_assets(entries: dict[str, str]) -> None:
    if "ClimateChamberLauncher.exe" not in entries:
        raise ValueError("Launcher executable missing")
    if "server/ClimateChamberServer.exe" not in entries:
        raise ValueError("Server executable missing")
    if not any("nicegui" in path.lower().split("/") for path in entries):
        raise ValueError("No bundled NiceGUI assets")
    if not any(path.endswith("chamber_web/assets/style.css") for path in entries):
        raise ValueError("Demo CSS missing")


def write_manifest(bundle: Path, *, version: str, include_driver: bool,
                   requirements_web: Path, requirements_driver: Path) -> None:
    entries = files_under(bundle)
    check_assets(entries)
    installed = sorted(
        ({"name": dist.metadata.get("Name", ""), "version": dist.version,
          "license": dist.metadata.get("License", "")}
         for dist in metadata.distributions()),
        key=lambda item: item["name"].casefold(),
    )
    names = {item["name"].lower().replace("_", "-") for item in installed}
    if "nicegui" not in names or "pyinstaller" not in names:
        raise ValueError("Required build dependencies not installed")
    if include_driver and "votschtechnikclimatechamber" not in names:
        raise ValueError("Pinned Vötsch driver missing from build environment")
    manifest = {
        "schema": 1,
        "version": version,
        "distribution": "W01-A SIMULATION ONLY - NOT HARDWARE CERTIFIED",
        "architecture": "Windows-x64",
        "python": sys.version.split()[0],
        "driver_included": include_driver,
        "requirements_web_sha256": sha256(requirements_web),
        "requirements_hardware_sha256": sha256(requirements_driver),
        "installed_packages": installed,
        "files": entries,
    }
    (bundle / "build-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (bundle / "SHA256SUMS.txt").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in sorted(entries.items())),
        encoding="utf-8",
    )
    verify_manifest(bundle)


def verify_manifest(bundle: Path) -> None:
    manifest = json.loads((bundle / "build-manifest.json").read_text(encoding="utf-8"))
    expected = manifest["files"]
    if not isinstance(expected, dict):
        raise ValueError("Invalid manifest files")
    for name in expected:
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name:
            raise ValueError("Unsafe manifest path: " + name)
    actual = files_under(bundle)
    if actual != expected:
        removed = sorted(set(expected) - set(actual))
        added = sorted(set(actual) - set(expected))
        changed = sorted(k for k in set(actual) & set(expected) if actual[k] != expected[k])
        raise ValueError(f"Integrity mismatch: missing={removed} unexpected={added} changed={changed}")
    check_assets(actual)
    lines = "".join(f"{digest}  {name}\n" for name, digest in sorted(actual.items()))
    if (bundle / "SHA256SUMS.txt").read_text(encoding="utf-8") != lines:
        raise ValueError("SHA256SUMS.txt disagrees with manifest")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--version", default="0.0.0")
    parser.add_argument("--include-driver", action="store_true")
    parser.add_argument("--requirements-web", type=Path)
    parser.add_argument("--requirements-hardware", type=Path)
    args = parser.parse_args()
    if args.create:
        if not args.requirements_web or not args.requirements_hardware:
            parser.error("--create requires both requirements files")
        write_manifest(args.bundle, version=args.version,
                       include_driver=args.include_driver,
                       requirements_web=args.requirements_web,
                       requirements_driver=args.requirements_hardware)
    elif args.verify:
        verify_manifest(args.bundle)
    else:
        parser.error("Choose --create or --verify")
    print("Bundle manifest verified:", args.bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
