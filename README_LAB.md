# Isolated-lab mode: full-range chamber operation without the permit workflow

For a **closed lab network** (server, laptop and chamber only). It replaces
the supervised H02 workflow (signed permit, witness, pinned revisions,
per-shift STOP confirmation, watchdog process) with a single launch-time
switch, so profiles run unattended across the full temperature range.
Administrators can enable it in **Settings → Physical profile runs**; the
saved setting is applied at the next server start. The environment variable
below remains available for scripted launches.

This is not a certified safety configuration. The chamber's own temperature
limits, over-temperature protection and emergency stop are the primary safety
layer. Set the chamber's own limiter to suit the specimen before an unattended run.

## What stays enforced

- `CHAMBER_HIL_*`: private chamber IPv4, serial pin (re-checked on every
  read) and the software temperature envelope. Setpoints outside the envelope
  are never written.
- Sign-in and roles: only Administrator/Operator can control the chamber or run profiles.
- One controller owns the chamber. STOP is verified by readback, and any lost
  connection, stale or invalid telemetry, identity change, or missed step/run
  deadline stops the run.
- The run journal (history, logs, samples). A broken journal refuses starts.
- After a server restart the controller reports `UNKNOWN` until STOP is
  reverified. In lab mode the first **Run** performs that independent fresh
  `GOOD`/`STOPPED` read and clears the restart fence; a FAULT or a chamber that
  is actually running is never cleared automatically.

## Configure

Add to the environment or `chamber.env`:

```
CHAMBER_HIL_ADDRESS=192.168.0.11
CHAMBER_HIL_EXPECTED_SERIAL=58566207770010
CHAMBER_HIL_TEMP_MIN_C=-40
CHAMBER_HIL_TEMP_MAX_C=130
CHAMBER_HIL_ACK=SUPERVISED-PHYSICAL-HIL
CHAMBER_LAB_MODE=ISOLATED-LAB-UNATTENDED
# Optional:
# CHAMBER_LAB_MEASURED_MARGIN_C=5   # allowed air overshoot past the envelope (0..10, default 5)
# CHAMBER_LAB_GRADIENTS=on          # profile ramp columns write chamber gradients (default on)
```

If you configure the connection and lab mode in Settings instead, leave
`CHAMBER_HIL_*` unset: explicit environment variables take precedence over the
saved settings. Do not set `CHAMBER_H02_*` together with lab mode; the server
refuses to start.

To use the UI from the laptop over plain HTTP, add the `lab` network mode:

```
CHAMBER_NETWORK_MODE=lab
CHAMBER_BIND_HOST=192.168.10.5          # the server's lab address -> http://192.168.10.5:8090
# or bind all interfaces and name the address the laptop opens:
# CHAMBER_BIND_HOST=0.0.0.0
# CHAMBER_PUBLIC_ORIGIN=http://192.168.10.5:8090
# CHAMBER_ALLOWED_CLIENT_CIDRS=192.168.10.0/24   # default: all private networks
```

Start with `python main.py` or `python -m chamber_web.desktop_runtime --port 8090`.
The page title shows **PHYSICAL (isolated lab mode)**. Change the factory
administrator credentials and create an Operator account under Admin.

## Behaviour on the real chamber

- **Profiles** run on the chamber with no confirmation step. They may use the
  `ramp_up_c_per_min` / `ramp_down_c_per_min` columns. The chamber accepts
  0.01–5 °C/min up and 0.01–3.5 °C/min down. Each write is verified by
  readback, and the new gradient **stays set on the chamber** after the run.
- **Reach timeouts** must cover the setpoint ramp: the chamber moves its setpoint
  readback at its gradient (VT 4011: 5 °C/min up, 3 °C/min down by default).
  A step whose timeout is too short is refused before the chamber moves, with
  the minimum required. Example: 23 → 130 °C at 5 °C/min needs ≥ 1284 s plus
  time for the air to settle.
- **Manual setpoints** across a large range return as soon as the readback is
  verified ramping toward the target: "Setpoint accepted; chamber readback
  ramping toward 130 °C at 5 °C/min (about 22 min)". The dashboard shows the
  rest of the ramp.
- **Measured overshoot** at an envelope edge (e.g. −41 °C while holding −40 °C)
  is tolerated up to `CHAMBER_LAB_MEASURED_MARGIN_C`.
- The run stops the chamber when the server shuts down. If the server process
  dies, the chamber keeps its last setpoint; nothing in software can stop it then.

## Unattended full-range HIL acceptance

`scripts/hil_lab_acceptance.py` exercises the server's own control stack on
the chamber without a browser or an operator. Phases:

- identity and telemetry checks
- envelope and lease guards
- manual long-ramp control
- profile cancel mid-ramp
- full-range profile max → min → start
- declared-gradient profile with slope check
- server boot in lab mode

Each phase ends with a verified STOP. At the end the chamber is stopped and its
original setpoint and gradients are restored over an independent connection.

```
# 1. Validate the script and the stack without hardware (≈ 10 min)
python scripts/hil_lab_acceptance.py --simulate --evidence /tmp/lab-sim

# 2. Read-only plan and time estimate against the chamber (nothing moves)
python scripts/hil_lab_acceptance.py --plan-only --evidence hil-evidence/lab-plan

# 3. Full run (VT 4011, -40..130 °C, 10 min dwell: roughly 3-4 h)
nohup python scripts/hil_lab_acceptance.py --evidence hil-evidence/lab-$(date +%F) &
```

Useful options:

- `--phases identity,profile` runs a subset of phases.
- `--targets max,min,start` sets the profile targets: °C values, or `max`/`min`/`start`.
- `--edge-inset 2` stays 2 °C inside the envelope edges.
- `--dwell 600 --tolerance 1.5 --settle 2400` set the hold time, the band
  around the target, and the allowance on top of the setpoint ramp.
- `--gradient 1.0` sets the declared gradient for the gradient phase.
- `--deadline-hours N` sets a hard limit for the whole run.

Start from a **stopped** chamber. Ctrl-C/SIGTERM cancels and cleans up. A dropped SSH
session (SIGHUP) does not stop the run. Evidence directory: `timeline.jsonl`,
`samples.jsonl`, `runs/` (journal), `summary.json`, `summary.md`. Exit code 0
only if every phase passed.
