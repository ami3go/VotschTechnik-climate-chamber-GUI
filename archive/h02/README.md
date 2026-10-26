# Archived H02 permit and watchdog stack

This directory preserves the former H02 signed-permit, witness, pinned-revision,
independent-watchdog and per-shift STOP-confirmation implementation for
historical reference only.

It was removed from the runtime when the product became lab-only. Nothing here
is imported, built, tested or supported. The active physical-profile path is
isolated lab mode (`CHAMBER_LAB_MODE=ISOLATED-LAB-UNATTENDED`) with the G06
runner, G07 journal, G04 STOP fencing and G08 authorization.

Archived material:

- `chamber_web/hil/`: permit admission, supervised runtime, supervision host,
  watchdog child and wire protocol.
- `scripts/`: permit signing, watchdog reset and development watchdog wrapper.
- `tests/`: H02 unit/integration tests, revision tests and permit-tool tests.
- `workflows/`: the branch-specific H02 CI workflow.
- `docs/`: the H02 verification plan.

Do not copy these modules back without reintroducing their dependencies,
security review and operating procedure.
