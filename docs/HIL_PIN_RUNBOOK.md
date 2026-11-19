# Physical HIL — one operator PIN (authoritative agent runbook)

**Applies to:** automated physical test tooling in this repository (pytest
`tests/hardware/`, full-range acceptance, soak when launched through the PIN
wrapper, and the pytest-owned NiceGUI server). **Does not** certify a chamber,
replace its physical safety devices, or remove any separately applicable
production/pilot release restrictions.

## Operator: issue, rotate, revoke

Run on the **computer physically controlling the bench**, as the same OS user
that runs the test. These commands need an interactive operator terminal:

```bash
bash scripts/hil_pin.sh setup    # issue one random 8-digit PIN, valid 24 h
bash scripts/hil_pin.sh status   # show validity/expiry, never reveal PIN
bash scripts/hil_pin.sh reset    # rotate immediately; old PIN stops admitting tests
bash scripts/hil_pin.sh revoke   # disable new tests
```

The script asks the operator to type `AUTHORIZE` after checking that the
bench is free, the chamber is STOPPED, its serial/temperature envelope are
correct, and a physical emergency-stop procedure is accessible. The PIN
appears **once** in the terminal; convey it only to the agent requesting HIL
access. Do not put it into a PR, issue, chat log, test artifact or committed
`chamber.env`. Issuance does **not** prove that a person will remain present.

The state lives at
`~/.local/state/votsch-climate-chamber/hil-pin.json` (0700 directory, 0600
file); it holds a randomly salted scrypt digest and the exact 24-hour UTC
expiry, not the PIN. Missing/malformed/unsafe files, wrong PIN and expiry
fail closed. This is **local operator acknowledgement**, not a defense
against an agent with unrestricted access to the operator's OS account.
Restrict that account and never grant the agent permission to issue/reset
PINs unattended.

## Agent: minimum HIL admission procedure

1. Do all software-only simulation, review, lint, unit tests and profile
   validation **without** a PIN. Never turn simulation into physical access
   to make a test pass.
2. Ask the operator only for the current **HIL PIN**. Do not demand a
   signature, witness name, site private key, permit JSON, manual approval
   package or a second software code for *these test tools*.
3. Verify that configured `CHAMBER_HIL_ADDRESS`, `EXPECTED_SERIAL`,
   `TEMP_MIN_C`, `TEMP_MAX_C`, `ACK` and the selected profile are
   appropriate. These are **device configuration/safety bounds**, not
   additional authentication factors.
4. Start from independently confirmed `GOOD / STOPPED`. Maintain the
   single-owner G04 bench lock, fresh identity/telemetry, finite temperature
   limits, durable logs, bounded step/run deadlines, and final verified STOP.
   A PIN never overrides a latched FAULT, UNKNOWN or hardware interlock.
5. Use `bash scripts/hil_pin.sh run -- COMMAND...` and enter the PIN at
   the hidden prompt. This holds a non-blocking exclusive POSIX `flock`
   while the command runs. Treat a busy lock as NO-GO; never bypass it.
6. Preserve evidence with GUI/driver revision, chamber identity, temperature
   bounds, test selection, UTC timestamps, observed STOP and any fault.
   **Never record the PIN**. On exit, check the actual chamber, not merely
   a process exit code. An unverified STOP is **NO-GO**.
7. For long tests: set a finite test-internal deadline, liveness checks,
   and graceful STOP/restore logic. For long *software-only* work, use
   `scripts/h02_watchdog_command.py` with bounded timeout and logs. Do not
   apply a blind process-kill watchdog to an energized chamber: a killed
   process may leave the chamber running.

## Example invocations

```bash
# Device configuration, not additional PINs:
export CHAMBER_HIL_ADDRESS=192.168.0.11
export CHAMBER_HIL_EXPECTED_SERIAL=YOUR_CHAMBER_SERIAL
export CHAMBER_HIL_TEMP_MIN_C=20
export CHAMBER_HIL_TEMP_MAX_C=30
export CHAMBER_HIL_ACK=SUPERVISED-PHYSICAL-HIL

# Operator enters the PIN at the prompt. Actual tests are deliberately opt-in.
bash scripts/hil_pin.sh run -- env CHAMBER_HIL_RUN_TESTS=1 \
  python -m pytest -v tests/hardware

# Soak: run only under the PIN wrapper; finite internal watchdog/deadline.
bash scripts/hil_pin.sh run -- python scripts/hil_soak.py \
  --evidence hil-evidence/soak --deadline 2400

# Full-range lab acceptance: use a site-appropriate bounded envelope.
export CHAMBER_LAB_MODE=ISOLATED-LAB-UNATTENDED
bash scripts/hil_pin.sh run -- python scripts/hil_lab_acceptance.py \
  --plan-only --evidence hil-evidence/plan
bash scripts/hil_pin.sh run -- python scripts/hil_lab_acceptance.py \
  --evidence hil-evidence/acceptance --deadline-hours 6
```

Simulation remains PIN-free:

```bash
python -m pytest -q tests/test_hil_pin.py
python scripts/hil_lab_acceptance.py --simulate --evidence /tmp/hil-sim
```

`run` prompts for the PIN without shell echo and verifies it **before
launching** the child. The child also gets `CHAMBER_HIL_PIN` so physical
pytest, the acceptance script and its NiceGUI test subprocess can validate
independently. Keep process environments private; do not enable `set -x`,
`env` dumps or verbose secret tracing. To run unattended commands, a
privileged operator can supply the PIN through a private environment only
after explicit handoff; this is less resistant to leakage.

## Limits / scope of migration

- **New-test admission:** PIN instead of the old agent-facing
  signed-permit/witness workflow. H02 signing artifacts and historical
  evidence remain in Git for audit traceability. The legacy H02
  **production-supervised profile runtime still implements signed permits**;
  this PR does not pretend to have replaced its internal admission model.
- Isolated lab mode is an existing separate configuration that can run
  physical profiles without this test PIN gate. Agents **must not** start or
  use that mode as an alternative to the PIN wrapper during HIL work.
- `scripts/hil_soak.py` independently checks the PIN before configuring or
  connecting to a physical chamber, even when invoked directly. The Bash
  wrapper remains mandatory for agent HIL operations because it additionally
  holds the POSIX bench lock for the entire test command. A bare valid PIN is
  not a substitute for serialized ownership or an independently verified STOP.
- The Bash/flock runner targets POSIX hosts. A Windows-native operator/PIN
  runner and equivalent cross-process lock must be qualified separately before
  claiming Windows hardware-test admission; software-only Windows CI stays PIN-free.
- PIN expiry or rotation blocks **new** admission. It does not prove that
  an already-running physical process has stopped. Verify chamber state
  and end runs gracefully; use local physical controls on any doubt.
- A Bash PIN alone cannot confirm physical presence, free hardware, or
  correct specimen safety. Those checks belong to the operator and to the
  live hardware's independent safety mechanisms.
