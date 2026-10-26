"""Best-effort identification of the exact GUI and driver revisions in use.

Build/release provenance uses these commit IDs, so they are read from the actual
installation (git checkout and the driver's pip provenance) rather than typed.
A frozen bundle has no git checkout and a hash-locked wheelhouse loses the
driver's ``direct_url.json``; such builds carry an integrity-manifested
``build-revision.json`` stamp instead. Empty strings mean "unknown" and make
the permit check fail closed.
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
_STAMP = Path(__file__).with_name("build-revision.json")
MAX_STAMP_BYTES = 4096


def _stamp() -> dict[str, str]:
    """Read a frozen-bundle revision stamp; any doubt yields no pin."""
    try:
        if _STAMP.is_symlink() or _STAMP.stat().st_size > MAX_STAMP_BYTES:
            return {}
        payload = json.loads(_STAMP.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict) or payload.get("dirty") is not False:
        return {}
    result = {}
    for key in ("gui_commit", "driver_commit"):
        value = payload.get(key, "")
        if isinstance(value, str) and _COMMIT.fullmatch(value.lower()):
            result[key] = value.lower()
    return result


def _git_commit() -> str:
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


def detect_gui_commit() -> str:
    return _git_commit() or _stamp().get("gui_commit", "")


def detect_driver_commit() -> str:
    try:
        raw = distribution(DRIVER_NAME).read_text("direct_url.json")
        value = str(json.loads(raw or "").get("vcs_info", {}).get("commit_id", "")).lower()
    except (PackageNotFoundError, TypeError, ValueError, AttributeError):
        return _stamp().get("driver_commit", "")
    if _COMMIT.fullmatch(value):
        return value
    return _stamp().get("driver_commit", "")
