"""Offline, read-only check of the external chamber driver's installed identity.

Run with EXACTLY the Python interpreter used to start the NiceGUI server:
    .venv/bin/python scripts/verify_driver_install.py
    .venv\\Scripts\\python.exe scripts\\verify_driver_install.py

No network access and no chamber connections occur in this script.
"""
from __future__ import annotations

import argparse
from importlib import import_module
from importlib.metadata import PackageNotFoundError, distribution
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
DRIVER_NAME = "VotschTechnikClimateChamber"
_DRIVER_LINE = re.compile(
    r"^VotschTechnikClimateChamber\s*@\s*git\+https://github\.com/"
    r"ami3go/VotschTechnik-climate-chamber-Python\.git@([a-fA-F0-9]{40})\s*$",
    re.IGNORECASE,
)


def expected_driver_commit(requirements: Path) -> str:
    """The exact commit that the GUI is allowed to install and use."""
    lines = requirements.read_text(encoding="utf-8").splitlines()
    commits = [match.group(1).lower() for line in lines
               if (match := _DRIVER_LINE.fullmatch(line.strip())) is not None]
    if len(commits) != 1:
        raise RuntimeError(
            f"Expected exactly one commit-pinned external driver in {requirements}")
    return commits[0]


def verify_driver_install(*, requirements: Path | None = None) -> str:
    """Check import *and* the installed VCS revision without talking to hardware."""
    required = expected_driver_commit(requirements or ROOT / "requirements-hardware.txt")
    try:
        module = import_module(DRIVER_NAME + ".discovery")
        discover = getattr(module, "discover_chambers")
        if not callable(discover):
            raise RuntimeError("Driver discovery entry point is not callable")
    except (ImportError, AttributeError) as exc:
        raise RuntimeError(
            f"Driver discovery import failed under Python {sys.executable}: {exc}. "
            "Update the driver in this interpreter and restart the server.") from exc
    try:
        installed = distribution(DRIVER_NAME)
    except PackageNotFoundError as exc:
        raise RuntimeError(
            f"Driver package metadata is missing in Python {sys.executable}") from exc
    try:
        raw = installed.read_text("direct_url.json")
        commit = json.loads(raw or "").get("vcs_info", {}).get("commit_id", "").lower()
    except (TypeError, ValueError, AttributeError) as exc:
        raise RuntimeError("Installed driver's Git provenance metadata is invalid") from exc
    if commit != required:
        raise RuntimeError(
            "Installed driver revision mismatch: "
            f"expected {required}, found {commit or 'unknown'}. "
            "Reinstall requirements-hardware.txt into the server interpreter.")
    path = getattr(module, "__file__", "unknown")
    message = (f"Driver discovery OK: commit {required}; Python: {sys.executable}; "
               f"module: {path}")
    print(message, flush=True)
    return message


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requirements", type=Path, default=ROOT / "requirements-hardware.txt")
    args = parser.parse_args()
    try:
        verify_driver_install(requirements=args.requirements)
        return 0
    except (OSError, RuntimeError) as exc:
        print("Driver discovery validation FAILED: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
