# H01-OPER-01 / H01-OPER-02 — real hardware qualification and operational pilot

**Current state (2026-11-21):** Software development only. **Physical HIL is NOT RUN on this new implementation head**; operational deployment / R01 release is **NO-GO**. Track hardware evidence in [#112](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/112) and code/CI in [#113](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/113).

## Current reviewed boundaries

- NiceGUI uses `ChamberManager -> VotschBackend -> VotschTechnikClimateChamber` exclusively; no vendor protocol or sockets in the GUI.
- The pinned driver source is `ami3go/VotschTechnik-climate-chamber-Python@d22dc05687cac4c5cdef440fb52b05965ed3d146` in `requirements-hardware.txt`.
- Prior [2026-10-21 engineering H02 PASS](H02_PHYSICAL_PROFILE_RESULT_2026-10-21.md) is for GUI `74a816d` / driver `9323e37` on VT4011; it does **not** qualify this branch, the driver update, a full-range chamber, or unattended operation. Formal site signatures are still missing in [H02 acceptance](H02_SITE_ACCEPTANCE_2026-10-21.md).
- The software envelope `-40…130°C` in `chamber_web/hil/physical.py` is a fixed guard, **not** a certified equipment range. An administrator must set a narrower specimen- and chamber-approved envelope.
- Only site-verified manual temperature, Start and verified STOP are candidates for the first low-risk live sequence. Digital outputs and compressed-air/dryer commands are **still blocked** for physical profile dispatch; Operational Mode does not remove those restrictions.
- The G04 serialized worker cannot preempt a manufacturer-driver call that is already executing. A browser STOP is **not** an emergency stop.

## H01 — operator-attended exact-head qualification

1. The responsible operator checks the actual chamber nameplate **model, serial, firmware/options**, rated temperature range, test-system type, installed interlocks, calibration and OEM STOP/alarm documentation. Record the host/driver exact SHAs; approve a specimen-safe envelope and temperature excursion. Document the separate local emergency stop, site response to transport failure and fire/power loss. Do not infer this from a simulator.
2. Pin the GUI and maintained driver, verify installation with `python setup_environment.py --check-driver` and `python scripts/verify_driver_install.py`. Install or activate the admin account and confirm saved chamber IP/serial. Start in `localhost` mode (or approved TLS LAN); **do not** start hardware test programs without operator PIN.
3. The human operator issues an 8-digit 24h test PIN using `bash scripts/hil_pin.sh setup` and only gives it to a supervised test command on an isolated bench. **The existing `hil_lab_acceptance.py` harness uses the explicit engineering `CHAMBER_LAB_MODE=ISOLATED-LAB-UNATTENDED` configuration**, along with the complete site-approved `CHAMBER_HIL_*` environment; it is not a substitute for Operational Mode, and must not be combined with `CHAMBER_OPERATIONAL_MODE`. This harness has its own bounded application-level deadline and requires a human supervising the real chamber. Run read-only readiness and STOPPED/identity verification, writing evidence to a local directory:
   ```bash
   export CHAMBER_LAB_MODE=ISOLATED-LAB-UNATTENDED  # HIL harness only, NOT product operation
   bash scripts/hil_pin.sh run -- python scripts/hil_lab_acceptance.py \
     --plan-only --evidence hil-evidence/h01-current-plan
   ```
   Treat an unsuccessful read, serial mismatch, or stale RUNNING/UNKNOWN/FAULT readback as an immediate **NO-GO** for subsequent writes.
4. Only under the signed local site test scope and with real emergency-stop access, run a bounded gentle setpoint excursion with a documented manual STOP/return-to-baseline:
   ```bash
   bash scripts/hil_pin.sh run -- python scripts/hil_lab_acceptance.py \
     --phases identity,manual --targets 25 --edge-inset 2 \
     --deadline-hours 1 --evidence hil-evidence/h01-current-manual
   ```
   Confirm the selected target and phase arguments are valid for the installed chamber and real site policy **before executing**. Do not assume that 25°C is universally safe. The script can generate a plan before a physical run.
5. Record independent GOOD/STOPPED and serial readback before/after each physical command, measured/setpoint traces, G04 generation, watchdog/deadline behavior, raw run journal, gradient snapshot, final setpoint and chamber state. No report is PASS unless the chamber is visibly safe and site evidence is complete.
6. Independently approve any later full-range or fault-injection tests. **Never use a blind process-kill watchdog for an energized chamber.** Any transport loss, missed deadline, stuck worker or non-verified STOP means UNKNOWN and local operator intervention.

## H01 acceptance ledger (to be populated with real evidence, not CI)

| Gate | Evidence required | Current |
|---|---|---|
| Model/serial/firmware and approved limits | Named chamber, OEM manual clauses, site inspection | **NOT PROVIDED** |
| Current GUI + external driver exact revisions | Clean commit, import check, on-device identity readback | **NOT RUN** |
| Device GOOD/STOPPED after connect | Real readback with bounded age, no STOP latch | **NOT RUN** |
| Authorized manual setpoint / Start / STOP | Raw commands, trace and final GOOD/STOPPED | **NOT RUN** |
| Lost-link, restart, blocked-worker and alarm behaviour | Separately authorized physical fault test + operator recovery | **NOT RUN** |
| Independent site acceptance | Reviewed evidence + signed decision | **PENDING** |

## H01-OPER-02 — software-controlled Operational Mode

- An administrator selects **Settings → Chamber configuration → Enable supervised Operational Mode**, enters a validated private chamber IP, serial and bounded temperature envelope, re-authenticates with their password and saves. **Restart** the server; current mode never flips through a browser request.
- In configuration-based deployment, the server injects `CHAMBER_OPERATIONAL_MODE=SUPERVISED-OPERATION`. For direct scripted launches, the same variable may be set with complete `CHAMBER_HIL_*` authorization. Do not combine Operational Mode with `CHAMBER_LAB_MODE` or `CHAMBER_H02_*`.
- **Operational Mode prohibits `CHAMBER_NETWORK_MODE=lab`**, since that is plain HTTP. Use `localhost`, or the already reviewed TLS `lan` mode with certificate, exact origin, narrow CIDR allowlist and explicit physical LAN admission.
- The independent H02-C watchdog process is started before profile operations; its missing heartbeat, restart latch, fault or failed arm **refuses a new start**. The server binds each run to its unique ID and trusted G04 generation, checks fresh telemetry, journal availability, step/whole deadlines, and sends STOP + verifies STOPPED when the parent process remains capable of contacting hardware.
- This is **not** a physically independent emergency stop. The watchdog requires the application host and G04/driver to reach the equipment; a killed host, OS failure, stuck synchronous driver call or lost network may leave the chamber running. Certification of unattended use requires a separate device/interlock/site response.
- Current physical operational profiles intentionally still support temperature `chamber_run=ON` steps with no auxiliary/digital outputs and no unqualified gradient mutation. Profile setpoints must fit the administrator's approved equipment envelope. Historical Isolated Lab mode remains a separate, explicitly less-protected engineering option.
- A locally issued PIN is for agent-operated physical **test tooling**, not ordinary authenticated GUI operation. PIN bypass, simulator identity spoofing, foreign-lease takeover of RUNNING state, or auto-reconciliation of FAULT are prohibited.

## Offline qualification before HIL

Use a bounded test watchdog and report exact-head outcomes, never just `pytest` launched:

```bash
python scripts/h02_watchdog_command.py \
  --timeout-s 900 --idle-timeout-s 300 --cleanup-s 10 \
  --log-dir test-evidence/h01-operational \
  -- python -m unittest tests.test_lab_mode tests.test_chamber_settings tests.test_profile_execution_service -v
```

Required regressions: invalid or simultaneous operating modes, simulator denial, admin-password save, environment override, missing/failed watchdog, confirmed arm before first hardware dispatch, G04 STOP/identity fences, and HTTPS/localhost admission. Include Windows Python 3.10/3.12 and Linux CI. No hardware I/O in offline tests.

**Acceptance:** software merge after exact-head CI + independent technical review; H01 current-chamber HIL after physical evidence; site/production GO after independent signed safety and G08/W02/R01 release checks. None may be inferred from the others.
