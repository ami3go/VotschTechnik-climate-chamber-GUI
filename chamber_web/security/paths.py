"""Harden local paths before NiceGUI initializes its persistent user storage."""
from __future__ import annotations

import os
from pathlib import Path


def security_directory() -> Path:
    return Path(os.environ.get(
        "CHAMBER_SECURITY_DIR", str(Path.home() / ".chamber_web" / "security")
    )).expanduser().resolve()


def configure_nicegui_storage() -> Path:
    """Never persist opaque authenticated sessions in cwd/.nicegui or a repo.

    Called BEFORE creating NiceGUI pages; supports already imported nicegui in
    simulated tests. A private directory protects storage even when NiceGUI
    writes individual files with a permissive process umask.
    """
    root = security_directory()
    root.mkdir(parents=True, exist_ok=True)
    directory = root / "nicegui_storage"
    directory.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        root.chmod(0o700)
        directory.chmod(0o700)
    os.environ["NICEGUI_STORAGE_PATH"] = str(directory)
    from nicegui.storage import Storage

    Storage.path = directory
    return directory
