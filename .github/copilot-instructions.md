# AI coding assistant instructions

Read [AGENTS.md](../AGENTS.md) and
[docs/HIL_PIN_RUNBOOK.md](../docs/HIL_PIN_RUNBOOK.md).
For physical HIL test admission, request only the operator's 24-hour PIN.
Do not create/reset the PIN on behalf of the operator. Never bypass
temperature/identity constraints, STOP/reconciliation, device ownership
or evidence collection. Use a bounded watchdog for long tasks. The GUI
uses NiceGUI and the external Vötsch Python driver exclusively.
