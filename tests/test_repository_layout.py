"""Guard the NiceGUI-only source tree against old desktop artifacts."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_legacy_desktop_gui_is_not_shipped() -> None:
    retired = (
        "VotschTechnikClimateChamber-GUI-2.py",
        "VotschTechnikClimateChamber-GUI-2.spec",
        "version.py",
        "Archive",
        "build/VotschTechnikClimateChamber-GUI-2",
        "dist/VotschTechnikClimateChamber-GUI-2.exe",
        ".idea",
        "pictures/main-tab.png",
        "pictures/settings_tab.png",
        "pictures/log-tab.png",
    )
    for name in retired:
        assert not (ROOT / name).exists(), f"Retired desktop artifact returned: {name}"


def test_nicegui_entrypoints_and_operational_scripts_are_retained() -> None:
    launcher = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "from chamber_web.main import run" in launcher
    assert "tkinter" not in launcher

    maintained = (
        "chamber_web/main.py",
        "chamber_web/adapters/votsch.py",
        "scripts/build_windows_launcher.ps1",
        "scripts/build_windows_offline.ps1",
        "scripts/windows_server.py",
        "scripts/windows_launcher.py",
        "scripts/reset_credentials.py",
        "scripts/hil_soak.py",
        "setup_environment.py",
    )
    for name in maintained:
        assert (ROOT / name).is_file(), f"Maintained NiceGUI component missing: {name}"
