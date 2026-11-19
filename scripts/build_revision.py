"""Write or check the frozen-bundle revision stamp used by H02 admission.

A git checkout identifies its GUI revision directly. A frozen bundle has no
``.git`` and a hash-locked wheelhouse may not carry the driver's
``direct_url.json``, so the build records both pinned revisions in
``chamber_web/build-revision.json``. That stamp travels inside the bundle and
is covered by SHA256SUMS.txt / build-manifest.json.

The stamp is only written from a CLEAN tracked working tree (or with explicit
``--gui-commit`` for source archives); a dirty build must not claim a revision.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

COMMIT = re.compile(r"[0-9a-f]{40}")
REPO = Path(__file__).resolve().parents[1]
STAMP = REPO / "chamber_web" / "build-revision.json"
HARDWARE = REPO / "requirements-hardware.txt"


def _git(*arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO), *arguments], capture_output=True,
            text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SystemExit("git is required to stamp a build revision: " + str(exc))
    if result.returncode != 0:
        raise SystemExit("git command failed: " + " ".join(arguments))
    return result.stdout.strip()


def gui_commit(explicit: str = "") -> str:
    if explicit:
        value = explicit.strip().lower()
        if not COMMIT.fullmatch(value):
            raise SystemExit("--gui-commit must be a full 40-character commit SHA")
        return value
    if not (REPO / ".git").exists():
        raise SystemExit("No .git checkout: pass --gui-commit for a source archive")
    value = _git("rev-parse", "HEAD").lower()
    if not COMMIT.fullmatch(value):
        raise SystemExit("Could not resolve a full GUI commit SHA")
    if _git("status", "--porcelain=v1", "--untracked-files=no"):
        raise SystemExit(
            "Refusing to stamp a dirty working tree; commit tracked changes first")
    return value


def driver_commit(explicit: str = "") -> str:
    if explicit:
        value = explicit.strip().lower()
        if not COMMIT.fullmatch(value):
            raise SystemExit("--driver-commit must be a full 40-character commit SHA")
        return value
    try:
        text = HARDWARE.read_text(encoding="utf-8")
    except OSError:
        return ""
    for line in text.splitlines():
        match = re.search(r"@([0-9a-fA-F]{40})", line)
        if match:
            return match.group(1).lower()
    return ""


def write(path: Path, gui: str, driver: str) -> None:
    payload = {
        "schema": 1,
        "gui_commit": gui,
        "driver_commit": driver,
        "dirty": False,
        "source": "build_revision.py",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    print("Revision stamp written:", path)
    print("  gui_commit:", gui)
    print("  driver_commit:", driver or "(none)")


def check(path: Path) -> int:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit("Revision stamp missing or invalid: " + str(exc))
    if payload.get("dirty") is not False:
        raise SystemExit("Revision stamp marks the build dirty")
    for key in ("gui_commit", "driver_commit"):
        value = payload.get(key, "")
        if key == "driver_commit" and not value:
            continue
        if not isinstance(value, str) or not COMMIT.fullmatch(value):
            raise SystemExit("Revision stamp has an invalid " + key)
    print("Revision stamp OK:", path)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=STAMP)
    parser.add_argument("--gui-commit", default="")
    parser.add_argument("--driver-commit", default="")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        return check(args.out)
    write(args.out, gui_commit(args.gui_commit), driver_commit(args.driver_commit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
