"""Guard the NiceGUI-only source tree against tracked desktop artifacts."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_legacy_desktop_gui_is_not_shipped() -> None:
    """Only reject files tracked in Git; developers may keep local IDE/build files."""
    retired_paths = {
        "VotschTechnikClimateChamber-GUI-2.py",
        "VotschTechnikClimateChamber-GUI-2.spec",
        "version.py",
        "dist/VotschTechnikClimateChamber-GUI-2.exe",
        "pictures/main-tab.png",
        "pictures/settings_tab.png",
        "pictures/log-tab.png",
    }
    retired_prefixes = (
        "Archive/",
        "build/VotschTechnikClimateChamber-GUI-2/",
        ".idea/",
    )
    if (ROOT / ".git").exists():
        tracked = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-z"],
            capture_output=True,
            check=True,
            timeout=10,
        ).stdout.decode("utf-8").split("\0")
        for path in tracked:
            assert path not in retired_paths
            assert not path.startswith(retired_prefixes), f"Tracked desktop artifact: {path}"
    else:
        # Source exports do not contain Git metadata.
        for path in retired_paths:
            assert not (ROOT / path).exists(), f"Desktop artifact in export: {path}"


def test_nicegui_entrypoints_and_operational_scripts_are_retained() -> None:
    launcher = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "from chamber_web.main import run" in launcher
    assert "tkinter" not in launcher

    maintained = (
        "chamber_web/main.py",
        "chamber_web/desktop_runtime.py",
        "chamber_web/maintenance.py",
        "chamber_web/adapters/votsch.py",
        "scripts/build_windows_launcher.ps1",
        "scripts/build_windows_offline.ps1",
        "scripts/windows_server.py",
        "scripts/windows_launcher.py",
        "scripts/windows_app_server.py",
        "scripts/windows_app_launcher.py",
        "scripts/build_revision.py",
        "scripts/install_preproduction_task.ps1",
        "scripts/uninstall_preproduction_task.ps1",
        "scripts/reset_credentials.py",
        "scripts/hil_soak.py",
        "setup_environment.py",
    )
    for name in maintained:
        assert (ROOT / name).is_file(), f"Maintained NiceGUI component missing: {name}"
