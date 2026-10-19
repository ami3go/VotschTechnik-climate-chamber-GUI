# W01-A: Windows launcher and offline packaging feasibility

**Status:** pre-release **SIMULATION ONLY**. This is a Windows x64 packaging
prototype, **not** the W02 certified offline distribution, G08 authenticated
multi-user service, H01 hardware validation or permission to operate a chamber.

## Build on an internet-connected Windows x64 host

Prerequisites: Python 3.12 x64, Git for the commit-pinned external Vötsch
driver, PowerShell 5.1+ and internet access **on the build host only**.
The build uses clean temporary virtual environments and PyInstaller 6.16.0.
Package inputs include `nicegui==3.18.0` from `requirements-web.txt`
and the immutable driver commit in `requirements-hardware.txt`.

~~~powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows_launcher.ps1 -Clean -Version 0.1.0-w01 -Configuration Portable
powershell -ExecutionPolicy Bypass -File scripts/build_windows_offline.ps1 -Clean -Version 0.1.0-w01 -Configuration Portable
~~~

Script A produces `dist/windows-launcher/ClimateChamberLauncher.exe` and
`launcher-build.json`. **The thin launcher is not a self-contained install**:
it requires a matching `server/ClimateChamberServer.exe` beside it, plus the
rest of the frozen server directory.

Script B produces `dist/ClimateChamber-Web-Windows-x64-0.1.0-w01-offline.zip`
and `.zip.sha256`. The ZIP contains a PyInstaller onedir frozen NiceGUI
server, the same launcher, bundled NiceGUI static files, registered
Fake/alternate-stub/Vötsch adapters, the pinned external Vötsch package,
`build-manifest.json`, SHA256SUMS.txt and this guide. The external driver is
included as a dependency **but physical connections remain rejected** by
`VotschBackend`. For a simulation-only diagnostic build, pass
`-SimulationOnly` to omit that package; such a ZIP is **not release-complete**.

Both scripts accept `-Python`, `-OutputDir`, `-Version`, `-Clean` and
`-Configuration Portable`. Their nonzero exits indicate failed dependency
installation, freeze, artifact verification, or self-test. No third-party
license to the Visteon logo has been presumed; no proprietary icon is shipped.

## Transfer and first run

Copy the offline ZIP and its adjacent `.sha256` file onto USB. Check the
checksum on the destination:

~~~powershell
(Get-FileHash -Algorithm SHA256 .\ClimateChamber-Web-Windows-x64-0.1.0-w01-offline.zip).Hash
Get-Content .\ClimateChamber-Web-Windows-x64-0.1.0-w01-offline.zip.sha256
Expand-Archive .\ClimateChamber-Web-Windows-x64-0.1.0-w01-offline.zip -DestinationPath .\ClimateChamber
.\ClimateChamber\ClimateChamber-Web-Windows-x64-0.1.0-w01-offline\ClimateChamberLauncher.exe
~~~

The hashes must match. Optionally create a **current-user Start Menu** shortcut
(no administrator privileges or system-wide service needed):

~~~powershell
$root = ".\\ClimateChamber\\ClimateChamber-Web-Windows-x64-0.1.0-w01-offline"
& "$root\\create_windows_shortcuts.ps1" -Launcher "$root\\ClimateChamberLauncher.exe"
~~~

Add `-Desktop` to request a desktop shortcut. Windows PowerShell must be
permitted to run this script under your local execution policy; the launcher
itself does not require PowerShell.

Keep the extracted `server` folder beside the
launcher. A default Windows browser (Edge or another installed browser)
is required; **no browser is bundled**. No Python, pip, uv, Node, Git or
administrator privilege is needed on the destination for this portable
simulated app. No installer or auto-update code runs on the destination.

The launcher attaches only to an HMAC-authenticated local W01 instance;
otherwise it starts the bundled server, waits for app-specific readiness
and opens `http://127.0.0.1:8080/`. `CHAMBER_PORT` may set a different
unprivileged port on BOTH launcher invocations; no host override is supported.
A foreign service on the port is an error. The per-user kernel lock
prevents two W01 servers under the same user profile; concurrent launches
reuse the existing instance. Logs are saved at
`%LOCALAPPDATA%\ClimateChamber\W01\server.log`; launcher errors show the
location. `--no-browser` starts/attaches without opening a browser;
`--check-only --no-browser` checks an existing instance.

**Browser closure does not terminate the running portable server.** To
stop this simulated build, terminate `ClimateChamberServer.exe` via Task
Manager or PowerShell. It is NOT a Windows Service; logoff, reboot, app
crash and host power loss stop it without guaranteed continuity. Never
treat this process lifecycle as a hardware STOP. The W01 runtime uses
per-user `%LOCALAPPDATA%` for its lock, instance token and logs. Persistent
profiles/settings and migrations will be handled by later G03/G07/W02
releases; the demo's in-browser profile edits are not durable.

## Verification available in W01-A

Windows GitHub Actions builds both scripts, validates a nonprivileged shortcut, tests the frozen server's
`--self-test --require-module VotschTechnikClimateChamber`, extracts and verifies hashes, checks
Fake/alternate backend registry imports, loads the bundled pinned Vötsch driver via its vendor adapter without opening any socket, invokes the launcher twice and
confirms the PID is unchanged, confirms a foreign listener is refused and
checks loopback UI availability. This proves a connected Windows-runner
prototype, **not** a clean disconnected VM. A passing unit test does not
certify offline network independence, physical controls or released software.

## First-run credentials

The first NiceGUI launch provisions `admin` / `admin` and default PIN `12345678` only if no administrator exists. General profile uses the password; PIN sign-in requires switching to Isolated LAN. Change the username/password through Admin > Administrator Credentials and the PIN through Admin > Security Profiles. Existing credentials are never reset on startup; LAN use is warned about while factory credentials are present. See [Factory Credentials](docs/FACTORY_CREDENTIALS.md).

## Administrator password / PIN reset

From a trusted **local interactive** PowerShell terminal in the extracted
distribution, run `server/ClimateChamberServer.exe --reset-credentials`.
The script requires no previous password, PIN or recovery token; type
`RESET` at the server computer to confirm. It restores the factory
administrator username, password and PIN, selects General password login,
and revokes all existing sessions. Other user and run data are preserved.
It does **not** stop chamber hardware. Change defaults before LAN use.
See [credential-reset procedures](docs/CREDENTIAL_RESET.md) in the source
repository. Never delete the security database/keys to bypass login.

## Required before W02 or real hardware

- Generate a fully hash-locked, reviewed **transitive** wheel closure with
  all redistribution licenses, PyInstaller hook/DLL audit and SBOM.
  W01 records installed versions/hashes of files but is NOT a reproducible
  hash-locked supply-chain build; dependency selection may vary by date.
- Perform browser-level offline asset/CDN/websocket/download audit with
  internet egress blocked; test clean Windows 10/11 x64 VM with no Python,
  build tools or existing app. Win10/11 baseline, browsers and branding
  approvals require owner verification.
- Replace this portable bootstrap with approved service supervision,
  same-user/local instance ACL threat model, signed shutdown/STOP policy,
  authenticated first-admin enrollment, authorization and session handling
  (G08); local unauthenticated demo must never reach physical I/O.
- Finish G02/G03/G04/G06/G07 features, external data backup and migration,
  upgrade/downgrade compatibility, run persistence and crash-recovery, with
  offline upgrade/rollback testing; the demo cannot execute durable profiles.
- Only the external Vötsch driver, through the vendor-specific adapter, may
  communicate with physical Vötsch equipment. Site policy, G08-min and
  hardware-in-the-loop (H01) are prerequisites, and remain unsatisfied.

Architecture: one configured chamber and one server/owner per per-user
deployment; alternate manufacturer stub used only in **sequential tests**.
There is no fleet selector, multi-controller process or physical I/O
path in this W01 build.

## G08-min first-administrator setup (standalone offline build)

From a LOCAL interactive PowerShell console (not a browser or automation),
run `server\\ClimateChamberServer.exe --bootstrap-admin` **once** before
using the web launcher. Enter a unique administrator username and password
at hidden prompts. No Python interpreter, online account, preinstalled
credentials or network access is required. The command refuses noninteractive
use and refuses any repeat bootstrap. The W01 bundle remains SIMULATION ONLY;
no physical device operations are enabled. The administrator store and
persistent session-cookie signing key reside under
`%USERPROFILE%\\.chamber_web\\security` unless overridden via
`CHAMBER_SECURITY_DIR`. Ensure this directory has restrictive NTFS ACLs;
Windows ACL certification, account recovery, backups and LAN/TLS are full
G08/W02 work. See [G08-min security contract](docs/G08_MIN_SECURITY.md)
(in source checkout; not yet certified as part of W01 offline bundle).
