"""Create and validate an integrity manifest for the W01 Windows offline bundle.

This helper runs on the build machine; the target does not need Python.
W01 records installed dependencies but does not yet claim a hashed wheel lock.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
from importlib import metadata
import json
import stat
from pathlib import Path
import sys


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def unsafe_reparse(path: Path) -> bool:
    """Treat Windows junctions and all reparse points as unsafe, including on 3.10.

    Path.is_junction() is only available in newer Python versions. lstat's
    FILE_ATTRIBUTE_REPARSE_POINT bit works on supported Windows interpreters.
    """
    if path.is_symlink():
        return True
    attrs = getattr(path.lstat(), "st_file_attributes", 0)
    if attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
        return True
    return getattr(path, "is_junction", lambda: False)()


def files_under(folder: Path, *, sidecars: frozenset[str] = frozenset()) -> dict[str, str]:
    if unsafe_reparse(folder):
        raise ValueError("Reparse point in offline bundle root: " + str(folder))
    result = {}
    for path in sorted(folder.rglob("*")):
        if unsafe_reparse(path):
            raise ValueError("Reparse point in offline bundle: " + str(path))
        if path.is_file():
            name = path.relative_to(folder).as_posix()
            if name not in {"build-manifest.json", "SHA256SUMS.txt"} | sidecars:
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


def write_supply_chain_reports(bundle: Path, *, installed: list[dict[str, str]],
                               version: str, include_driver: bool,
                               web_sha256: str, driver_sha256: str,
                               closure: dict | None = None) -> None:
    """Emit deterministic CycloneDX, license, and build reports.

    With a reviewed closure (``closure``), the reports describe the **runtime
    closure** - exactly the artifacts the frozen bundle installs. Without one
    they describe the BUILD environment, which contains build-only tools that
    are not shipped. The scope property says which of the two it is, so the
    two can never be confused. No package is approved for redistribution by
    this function either way.
    """
    if closure is None:
        components = []
        for item in installed:
            name, revision = item["name"], item["version"]
            component = {"type": "library", "name": name, "version": revision,
                         "bom-ref": f"build-python:{name.casefold()}:{revision}"}
            if item["license"]:
                component["licenses"] = [{"license": {"name": item["license"]}}]
            components.append(component)
        scope = "unapproved-build-environment-not-runtime-closure"
        license_rows = [(item["name"], item["version"], item["license"],
                         "REVIEW_REQUIRED") for item in installed]
        closure_state = "UNVERIFIED"
        closure_digest = ""
    else:
        components = []
        for item in closure["artifacts"]:
            component = {"type": "library", "name": item["name"],
                         "version": item["version"],
                         "bom-ref": (f"w02-runtime:"
                                     f"{item['name'].casefold()}:{item['version']}"),
                         "hashes": [{"alg": "SHA-256", "content": item["sha256"]}]}
            if item.get("license"):
                component["licenses"] = [{"license": {"name": item["license"]}}]
            components.append(component)
        scope = "locked-runtime-closure"
        license_rows = [(item["name"], item["version"],
                         item.get("license") or "NOASSERTION", "REVIEW_REQUIRED")
                        for item in closure["artifacts"]]
        closure_state = "VERIFIED-HASH-LOCKED"
        closure_digest = closure.get("lock_sha256", "")
    sbom = {
        "bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1,
        "metadata": {"component": {"type": "application",
                                   "name": "ClimateChamber-Web-Windows-x64",
                                   "version": version},
                     "properties": [{"name": "w02:inventory-scope",
                                     "value": scope}]},
        "components": components,
    }
    (bundle / "sbom.cdx.json").write_text(
        json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (bundle / "THIRD_PARTY_LICENSES.csv").open("w", encoding="utf-8", newline="") as handle:
        report = csv.writer(handle)
        report.writerow(("distribution", "version", "declared_license", "approval"))
        report.writerows(license_rows)
    provenance = {
        "schema": 1, "build_kind": "W01-A mock-only connected-host feasibility",
        "release_version": version, "platform": "Windows-x64",
        "python": sys.version.split()[0], "include_external_driver": include_driver,
        "requirements_web_sha256": web_sha256,
        "requirements_hardware_sha256": driver_sha256,
        "dependency_closure": closure_state,
        "dependency_closure_sha256": closure_digest,
        "source_commit": "UNATTESTED",
        "publisher_signature": "NOT_ISSUED",
    }
    (bundle / "build-provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_manifest(bundle: Path, *, version: str, include_driver: bool,
                   requirements_web: Path, requirements_driver: Path,
                   closure_manifest: Path | None = None,
                   closure_lock: Path | None = None) -> None:
    installed = sorted(
        ({"name": dist.metadata.get("Name", ""), "version": dist.version,
          "license": dist.metadata.get("License", "")}
         for dist in metadata.distributions()),
        key=lambda item: item["name"].casefold(),
    )
    web_hash = sha256(requirements_web)
    driver_hash = sha256(requirements_driver)
    closure = None
    if closure_manifest is not None:
        payload = json.loads(closure_manifest.read_text(encoding="utf-8"))
        artifacts = payload.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            raise ValueError("The closure manifest has no artifacts")
        closure = {"artifacts": artifacts,
                   "lock_sha256": sha256(closure_lock) if closure_lock else ""}
    write_supply_chain_reports(bundle, installed=installed, version=version,
                               include_driver=include_driver,
                               web_sha256=web_hash, driver_sha256=driver_hash,
                               closure=closure)
    entries = files_under(bundle)
    check_assets(entries)
    names = {item["name"].lower().replace("_", "-") for item in installed}
    if "nicegui" not in names or "pyinstaller" not in names:
        raise ValueError("Required build dependencies not installed")
    if include_driver and "votschtechnikclimatechamber" not in names:
        raise ValueError("Pinned Votsch driver missing from build environment")
    manifest = {
        "schema": 1,
        "version": version,
        "distribution": "W01-A SIMULATION ONLY - NOT HARDWARE CERTIFIED",
        "architecture": "Windows-x64",
        "python": sys.version.split()[0],
        "driver_included": include_driver,
        "requirements_web_sha256": web_hash,
        "requirements_hardware_sha256": driver_hash,
        "dependency_closure": ("VERIFIED-HASH-LOCKED" if closure else "UNVERIFIED"),
        "dependency_closure_sha256": (closure["lock_sha256"] if closure else ""),
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


def verify_manifest(bundle: Path, *, sidecars: frozenset[str] = frozenset()) -> None:
    manifest = json.loads((bundle / "build-manifest.json").read_text(encoding="utf-8"))
    expected = manifest["files"]
    if not isinstance(expected, dict):
        raise ValueError("Invalid manifest files")
    for name in expected:
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name:
            raise ValueError("Unsafe manifest path: " + name)
    actual = files_under(bundle, sidecars=sidecars)
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
    parser.add_argument("--closure-manifest", type=Path,
                        help="the reviewed runtime closure manifest; when given, "
                             "the SBOM and license inventory describe the "
                             "closure instead of the build environment")
    parser.add_argument("--closure-lock", type=Path,
                        help="the reviewed closure lock file whose digest is "
                             "recorded with the closure")
    args = parser.parse_args()
    if args.create:
        if not args.requirements_web or not args.requirements_hardware:
            parser.error("--create requires both requirements files")
        write_manifest(args.bundle, version=args.version,
                       include_driver=args.include_driver,
                       requirements_web=args.requirements_web,
                       requirements_driver=args.requirements_hardware,
                       closure_manifest=args.closure_manifest,
                       closure_lock=args.closure_lock)
    elif args.verify:
        verify_manifest(args.bundle)
    else:
        parser.error("Choose --create or --verify")
    print("Bundle manifest verified:", args.bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
