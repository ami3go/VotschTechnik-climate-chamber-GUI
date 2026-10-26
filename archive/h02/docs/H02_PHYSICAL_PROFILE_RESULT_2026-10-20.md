# H02 supervised physical profile — 2026-10-20 result

## Verdict

**ENGINEERING H02 PASS. FORMAL INDEPENDENT/SITE ACCEPTANCE IS PENDING.**

The first two attempts below exposed fail-closed watchdog defects and did not
pass. After correction, clean-revision binding, a new signed permit, witnessed
restart-latch review and a fresh STOPPED reconciliation, attempt 3 satisfied
the defined acceptance criteria. The final chamber readback was Vötsch VT 4011,
serial `58566207770010`, `GOOD` and `STOPPED`, measured 25.5 °C with a 25.0 °C
setpoint. No watchdog restart latch remained.

## Attempt 3 — clean supervised pass

- Run: `60e8f4da-ea08-4806-9c5c-1c2124f89eb0`
- Exact tested GUI commit: `a0ecf17414cc7d3f4847f15aabcb9cd0692396f4`
- Driver commit: `9323e3701f3befedcc23b45170a851fd327f0bcc`
- Permit payload fingerprint: `7cba454715083bc20e5ed4e31753ad34c797267fe41c54efac9bb61206ee5912`
- Profile revision SHA-256: `4afbdcdb9a5652dd9a7711bbf2608c63ce7172aca4b0e8ce4798c6ba9e9b5724`
- Operator account: `admin`; witness recorded in permit: `User0`
- Started: `2026-10-20T16:28:08.180837+00:00`
- Terminal event: `2026-10-20T16:35:02.023442+00:00`
- Result: `COMPLETED`; all five steps; 227 events; 198 samples
- Watchdog: matching `RUN_ARM`/`RUN_DISARM`, no attempt-3 `FAULT`, no latch
- Final readback: `GOOD · STOPPED`, measured 25.5 °C, setpoint 25.0 °C

The checksum-verified raw journal, watchdog logs, signed permit and public key
are indexed in
[`hil-evidence/h02-v3-2026-10-20/`](../../../hil-evidence/h02-v3-2026-10-20/README.md).
The prepared human acceptance record remains unsigned:
[`H02_SITE_ACCEPTANCE_2026-10-20.md`](H02_SITE_ACCEPTANCE_2026-10-20.md).

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

## Offline correction and successful retest

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

Those four retest prerequisites were completed for attempt 3. The run reached
`COMPLETED`, recorded a clean `RUN_DISARM`, had no v3 watchdog `FAULT` or restart
latch, and ended with fresh `GOOD · STOPPED` readback. Any future physical run
still requires its own currently valid permit bound to the exact clean revision,
with a real operator and named witness present. This engineering pass does not
replace independent/site signatures or grant R01 production release.
