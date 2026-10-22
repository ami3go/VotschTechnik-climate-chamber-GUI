# Climate Chamber — pre-production Windows bundle (NOT CERTIFIED)

This bundle contains the **full** Climate Chamber server: sign-in and roles,
STOP fencing, run recording/history, manual control, profile execution and the
optional supervised physical H02 path (signed permit, pinned revisions,
independent watchdog). It is a pre-production engineering build, not a
certified or released product. Site acceptance, W02 release signing and the
H01/H02 records remain outstanding where not explicitly signed.

The older `W01` bundle is different: it is simulated, loopback-only and has no
authentication/STOP/HIL gates. Do not use it for chamber operation.

## Install

1. Extract the ZIP. Keep the layout (`ClimateChamberLauncher.exe` at the top,
   `server\ClimateChamberServer.exe` below it).
2. Create the first administrator once, from a terminal in the bundle:
   `server\ClimateChamberServer.exe --bootstrap-admin`
   Credentials are written to `%USERPROFILE%\.chamber_web\security`.
3. Copy `chamber.env.example` to `chamber.env` next to the launcher and edit
   only the `CHAMBER_*` keys you need. A real process environment variable
   always wins over the file. `--check-config` validates it without starting.
4. Start with `ClimateChamberLauncher.exe`. The launcher attaches only after
   the HMAC readiness proof from the server it started, so a stale browser tab
   or a foreign process on the port is detected rather than trusted.
5. Optional unattended start (same user, at logon, restart on failure):
   `powershell -ExecutionPolicy Bypass -File install_preproduction_task.ps1 -StartNow`
   Remove it with `uninstall_preproduction_task.ps1`.

Logs and state: `%LOCALAPPDATA%\ClimateChamber\App\` (`app.log`, rotated at
10 MB; run journal, profiles and security data live under `.chamber_web`).

## Accounts and physical operation

- Create an `Operator` account in **Admin → Accounts**. Only `Administrator`
  and `Operator` may command the chamber; `Viewer` is read-only.
- **Manual control** on real hardware requires all `CHAMBER_HIL_*` values,
  including `CHAMBER_HIL_ACK=SUPERVISED-PHYSICAL-HIL`, a private non-loopback
  chamber IPv4 address and a matching serial/envelope.
- **Physical profile runs** additionally require a site-signed H02 permit
  (`CHAMBER_H02_PERMIT_FILE`, `CHAMBER_H02_TRUSTED_KEY`, `CHAMBER_H02_WITNESS`,
  `CHAMBER_GUI_COMMIT`, `CHAMBER_DRIVER_COMMIT`). The permit binds the exact
  GUI/driver revisions, the operator's account name, the witness, the profile
  checksum, temperature targets and the watchdog budgets. The frozen bundle
  carries an integrity-manifested `build-revision.json` so those revisions are
  readable without a git checkout.
- Before the first physical run in a shift, the operator presses **Confirm
  STOP Procedure** on the Profiles page. That act is audited
  (`profile.stop_procedure`), lasts 12 hours for that account, and is required
  in addition to the launch-time HIL acknowledgement. Web STOP is not an
  emergency stop; the chamber's own controls and emergency stop remain
  primary.

## Limits of this variant

- Physical profiles accept **temperature steps only** (chamber run ON, no
  digital outputs, compressed air/dryer changes or gradients) until H03 has a
  verified setter/readback/restore contract. Simulation and legacy demo
  profiles are not evidence for hardware.
- LAN access is refused unless `CHAMBER_NETWORK_MODE=lan` plus a valid TLS
  certificate matching `CHAMBER_PUBLIC_ORIGIN`, a private client allowlist and
  safe key permissions are configured. The default is loopback only.
- No Authenticode publisher signature and no certified release artefact is
  produced by this build.

## Security maintenance (offline, no HTTP endpoints)

Back up the security database with its signed manifest:

```
server\ClimateChamberServer.exe --backup-security D:\backup\security-2026-10-22.sqlite3
server\ClimateChamberServer.exe --verify-security D:\backup\security-2026-10-22.sqlite3
```

Backups refuse an existing destination. Set `CHAMBER_UNATTENDED_MAINTENANCE=1`
to allow a scheduled task to run backup/verify without a terminal; credential
bootstrap/recovery and restore staging always require a local console. The
backup-signing key stays in the security directory and must be escrowed
separately. Staged restore never overwrites a live database.

## Run from a source checkout (validation, not a release)

The same runtime starts outside a bundle, on Windows or Linux, for local
pre-production validation (state/logs under `%LOCALAPPDATA%` or
`$XDG_STATE_HOME`):

```
python -m chamber_web.desktop_runtime --check-config --config chamber.env
python -m chamber_web.desktop_runtime --self-test
python -m chamber_web.desktop_runtime --port 8090
```

The launcher (`python -m chamber_web.desktop_runtime` via
`scripts/preproduction_launcher.py`) spawns that server on non-Windows instead
of a bundled `.exe`. `--self-test` refuses a dirty git tree and verifies no
physical device can be opened.

## Build (Windows x64, Python 3.12, PowerShell 5.1+)

```
powershell -ExecutionPolicy Bypass -File scripts/build_windows_offline.ps1 `
  -Variant PreProduction -UseReviewedClosure -Version 0.2.0-pre -Clean
```

`-UseReviewedClosure` installs only the reviewed hash-locked wheelhouse. The
build writes a revision stamp from a clean tree, runs the frozen self-test
(including "no physical device opened"), then writes `build-manifest.json`,
`SHA256SUMS.txt`, SBOM and license inventory and re-verifies a fresh extraction.
