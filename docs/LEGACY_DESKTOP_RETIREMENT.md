# Legacy standalone desktop GUI cleanup

**Scope:** Repository source-tree housekeeping, not hardware acceptance or a release cutover.

The maintained GUI is the NiceGUI application in `chamber_web/`, started with root `main.py`. Modern runtime and maintenance scripts in `scripts/` (Windows browser launcher/server, offline packaging and verification, HIL soak, and credential reset) and `setup_environment.py` are retained.

## Removed from the active tree

- Root Tkinter entry point `VotschTechnikClimateChamber-GUI-2.py`, its PyInstaller `.spec`, and its desktop-only `version.py`.
- Obsolete Tkinter/GTK/Qt prototypes in `Archive/`.
- Tracked PyInstaller products under `build/VotschTechnikClimateChamber-GUI-2/` and `dist/VotschTechnikClimateChamber-GUI-2.exe`.
- Desktop-only tab screenshots (`pictures/main-tab.png`, `pictures/settings_tab.png`, `pictures/log-tab.png`) and obsolete tracked IDE files under `.idea/`.

The hardware photograph and other neutral project assets are retained. Generated artifacts and personal IDE settings are excluded by `.gitignore`. This is a normal Git deletion: the historical files and executable are still recoverable from earlier commits; the Git history was **not rewritten**.

## Compatibility, safety, and verification

- Modern Python, NiceGUI and Windows offline server/launcher entry points are unchanged.
- No application-level chamber communication code was moved into the GUI. Physical device I/O must continue to use the pinned external Vötsch Python driver through `chamber_web/adapters/votsch.py`.
- HIL safety approval, release evidence, and R01 cutover remain separate requirements. In particular, removing old repository files does not decommission field-deployed legacy installations or grant approval to use physical chamber control.
- `tests/test_repository_layout.py` prevents accidental reintroduction of the retired entry points and checked-in build outputs while checking that maintained launchers remain present.

For legacy behavior/audit context, use [the migration plan](WEB_GUI_MIGRATION_PLAN.md) and the repository's Git history. For active deployment use [the NiceGUI setup guide](../README_WEB.md) or [Windows offline packaging](../README_OFFLINE_WINDOWS.md).
