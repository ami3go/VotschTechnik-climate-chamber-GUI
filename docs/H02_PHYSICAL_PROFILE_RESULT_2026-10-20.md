# H02 supervised physical profile — 2026-10-20 result

## Verdict

**NOT A CLEAN H02 PASS. Do not start another physical profile until the
corrected commit has its own signed permit and the restart latch has been
reviewed and cleared on site.**

The chamber was last observed through authoritative application telemetry as
Vötsch VT 4011, serial `58566207770010`, `GOOD` and `STOPPED`, measured 25.4 °C
with a 25.0 °C setpoint. The server was then stopped. Its watchdog restart latch
is deliberately left set, so physical profile admission remains fail-closed.

## Attempt 1 — watchdog stopped the run

- Run: `2bddf450-6ea8-43b4-96f8-8a6f33ee8c46`
- Terminal record: `UNKNOWN`
- Fault: `step budget moved backwards` at the step 1 → 2 transition
- Safety response: watchdog STOP requested and fresh STOPPED readback verified
- Root cause: the runner published the next step index before its new monotonic
  step deadline, allowing the watchdog to observe the new index with the old
  budget and then a backwards-moving replacement budget.

The runner now publishes the next step index and deadline atomically. The first
step deadline is also allocated before watchdog arming.

## Attempt 2 — profile completed, watchdog completion handshake failed

- Run: `873059ab-c830-44b6-ae02-95b6f5435917`
- Exact GUI commit: `0e170d72eb5ed11a398afb4b1636f3119033dc9b`
- Driver commit: `9323e3701f3befedcc23b45170a851fd327f0bcc`
- Permit SHA-256: `df932c6c7b7e3b504bdecf92529f56f9e205eae9fe5760cae259f2e959491e54`
- Profile: `41f4e0eb-a71e-4b93-99ea-7aa4fb80ddcd`, revision 1,
  SHA-256 `4afbdcdb9a5652dd9a7711bbf2608c63ce7172aca4b0e8ce4798c6ba9e9b5724`
- Operator: `admin`; witness recorded in permit: `User0`
- Started: `2026-10-20T15:49:57.926041+00:00`
- Ended: `2026-10-20T15:57:08.143556+00:00`
- Recorder result: `COMPLETED`, 232 events and 203 samples
- Recorder artifact hashes:
  - `snapshot.json`: `fb6269efffdfd2250c01e07a7da28430f5ee25fee89be25826c9b246e37c4aae`
  - `events.csv`: `6147cc9d30666f6671d15da7b2c83be2f11918ccadb65652486b98045f9bcb15`
  - `samples.csv`: `255e6f6ec26b8994df82675418003a7bf0c581cc4cce08d5c8a4e755062c5279`

All five targets (25, 26, 27, 28, 25 °C) completed their 60-second dwells and
G04 verified the final STOP. However, the watchdog interpreted G04's expected
completion STOP fence as `controller generation changed`, logged a fault and
consumed its one-shot STOP request. The chamber remained safe and the STOP was
verified, but a later run in that server process would not have had an unused
independent STOP request. Therefore the overall H02 acceptance result is not a
pass.

## Offline correction and remaining gate

The correction introduces watchdog protocol v2 with an explicit bounded
`STOPPING` state. It accepts only the one expected G04 generation increment,
continues telemetry/recorder/envelope checks, requires fresh GOOD/STOPPED
verification within the signed deadline, records clean disarm, and rearms its
one-shot request only across a verified STOP boundary. The child is also placed
in a separate signal group so terminal Ctrl-C can be handled as an authenticated
server shutdown rather than a fabricated watchdog loss.

Physical permit binding now additionally derives the installed GUI/driver
revisions at runtime and refuses tracked uncommitted GUI changes. Untracked HIL
evidence does not invalidate the checkout.

Before another physical attempt:

1. Commit and locally verify the correction.
2. Generate and interactively sign a new permit bound to that exact clean commit.
3. Confirm the chamber is physically stopped with the operator and named witness
   present, review the preserved watchdog evidence, and clear the restart latch.
4. Start the server and rerun the same immutable profile revision once. A pass
   requires `COMPLETED`, a clean `RUN_DISARM`, no watchdog `FAULT`, no restart
   latch, and a fresh final GOOD/STOPPED readback.
