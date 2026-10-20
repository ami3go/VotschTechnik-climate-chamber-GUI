"""Best-effort identification of the exact GUI and driver revisions in use.

An H02 permit is bound to these commit IDs, so they are read from the actual
installation (git checkout and the driver's pip provenance) rather than typed.
Empty strings mean "unknown" and make the permit check fail closed.
"""
from __future__ import annotations

import json
import re
import subprocess
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

DRIVER_NAME = "VotschTechnikClimateChamber"
_COMMIT = re.compile(r"[0-9a-f]{40}")
_ROOT = Path(__file__).resolve().parents[2]


def detect_gui_commit() -> str:
    try:
        revision = subprocess.run(
            ["git", "-C", str(_ROOT), "rev-parse", "HEAD"], capture_output=True,
            text=True, timeout=5, check=False)
        tracked = subprocess.run(
            ["git", "-C", str(_ROOT), "status", "--porcelain=v1",
             "--untracked-files=no"], capture_output=True, text=True,
            timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    value = revision.stdout.strip().lower()
    clean = tracked.returncode == 0 and not tracked.stdout.strip()
    return value if revision.returncode == 0 and clean and _COMMIT.fullmatch(value) else ""


def detect_driver_commit() -> str:
    try:
        raw = distribution(DRIVER_NAME).read_text("direct_url.json")
        value = str(json.loads(raw or "").get("vcs_info", {}).get("commit_id", "")).lower()
    except (PackageNotFoundError, TypeError, ValueError, AttributeError):
        return ""
    return value if _COMMIT.fullmatch(value) else ""
