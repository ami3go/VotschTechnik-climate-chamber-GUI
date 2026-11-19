# Claude / AI agent instructions

Follow [AGENTS.md](AGENTS.md) and the authoritative
[HIL PIN runbook](docs/HIL_PIN_RUNBOOK.md).

For automated physical HIL **tests**, request only the operator-issued
24-hour PIN; use `bash scripts/hil_pin.sh run -- ...` to authenticate and
serialize bench access. Never issue/reset your own PIN or bypass the gate.
Keep the external Python driver as the GUI's sole instrument transport.

Use a watchdog and hard execution deadline for any long task. On physical
hardware the watchdog must request a controlled STOP and verify fresh
STOPPED readback, not simply kill the controlling process. Record exact
tests/commit and distinguish software PASS from physical HIL PASS.
