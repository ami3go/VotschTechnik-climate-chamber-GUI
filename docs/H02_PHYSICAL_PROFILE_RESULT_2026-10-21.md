# H02 supervised physical profile — 2026-10-21 result

## Verdict

**ENGINEERING H02 PASS. FORMAL INDEPENDENT/SITE ACCEPTANCE IS PENDING.**

This is the second supervised physical profile pass, run on 2026-10-21 against
the current clean repository head `74a816d9d9bbb7acbb901334ef457dbc416f7641`
under a newly signed permit. It supersedes the NO-GO status of the earlier
attempt 2 in [`H02_PHYSICAL_PROFILE_RESULT_2026-10-20.md`](H02_PHYSICAL_PROFILE_RESULT_2026-10-20.md)
for the exact revision and permit listed below. The 2026-10-20 engineering pass
remains valid for its own revision and permit.

The run was preceded by an audited STOP reconciliation of the durable device
lease, which had been left in the uncertain state by the earlier server
restart. The controller returned to `VERIFIED_STOPPED` before any profile
execution was admitted. The final authoritative readback was Vötsch VT 4011,
serial `58566207770010`, `GOOD` and `STOPPED`, measured 25.5 °C with a 25.0 °C
setpoint, controller generation 131. No watchdog restart latch was raised.

## Attempt — clean supervised pass

- Run: `5be68792-77f7-471b-946c-20558f1e6502`
- Exact tested GUI commit: `74a816d9d9bbb7acbb901334ef457dbc416f7641`
- Driver commit: `9323e3701f3befedcc23b45170a851fd327f0bcc`
- Permit approval reference: `H02-2026-10-21-01`
- Permit payload fingerprint: `79dc3041eb6d6976abde80e3e0aebd5cf66cea5fd21d9aaffd917898da204490`
- Signed permit file SHA-256: `17a94d295718a8b6951656b16c89b46eb20191823d4a1d509336b362849c0cc1`
- Profile: `41f4e0eb-a71e-4b93-99ea-7aa4fb80ddcd`, revision 1
- Profile revision SHA-256: `4afbdcdb9a5652dd9a7711bbf2608c63ce7172aca4b0e8ce4798c6ba9e9b5724`
- Operator account: `admin`; witness recorded in permit: `User0`
- Journal start: `2026-10-21T10:41:46.960653+00:00`
- Watchdog `RUN_ARM`: `2026-10-21T10:41:46.976496+00:00`, controller generation 130
- Terminal event: `2026-10-21T10:48:42.598952+00:00`
- Watchdog `RUN_DISARM`: `2026-10-21T10:48:43.565654+00:00`
- Result: `COMPLETED`; all five steps; 229 events; 200 samples
- Watchdog: matching `RUN_ARM`/`RUN_DISARM`, no `FAULT` for this run, no latch
- Final readback: `GOOD · STOPPED`, measured 25.5 °C, setpoint 25.0 °C

All five targets (25, 26, 27, 28, 25 °C) completed their 60-second dwells
inside the ±2 °C tolerance. The worst deviation during each step's final 30 s
was 0.76, 0.96, 1.23, 1.27 and 1.67 °C respectively. Measured temperature over
the whole run remained between 24.81 °C and 27.96 °C, inside the permit
envelope 20–30 °C, and all 200 telemetry samples were `GOOD`.

Journal manifest SHA-256:
`33c72b4d91b31db29d97d8f9561752a369e466b81264d9f934f4dbd7bcebcb51`.

The checksum-verified raw journal, watchdog logs, signed permit and public key
are indexed in
[`hil-evidence/h02-v4-2026-10-21/`](../hil-evidence/h02-v4-2026-10-21/README.md),
with the engineering addendum in
[`hil-evidence/H02_V4_PHYSICAL_PASS_2026-10-21.md`](../hil-evidence/H02_V4_PHYSICAL_PASS_2026-10-21.md).
The prepared human acceptance record remains unsigned:
[`H02_SITE_ACCEPTANCE_2026-10-21.md`](H02_SITE_ACCEPTANCE_2026-10-21.md).

## Pre-run reconciliation

The durable device lease carried `uncertain=1` from the earlier server restart,
so the controller reported `UNKNOWN · STOP/reconciliation required` even though
the chamber itself read `GOOD · STOPPED`. An audited **Admin reconcile STOP**
was performed before any profile execution was admitted: independent physical
device readback confirmed `STOPPED`, the fence was cleared, and the controller
returned to `VERIFIED_STOPPED` at controller generation 130 with no latch.
Audit trail: `chamber.reconcile_stop` `INTENT` then `SUCCESS`. The operator
lease was then claimed by the permit-named operator account and handed over to
the profile runner (`chamber.manual_to_profile` `SUCCESS`, `profile.run`
`AUTHORIZED`).

## Software regression

After the run, the exact tested tree passed the complete software test suite:
`564 passed, 9 skipped, 196 subtests passed` (hardware tests remain opt-in and
skipped by default). The evidence files were added afterwards; only untracked
evidence and documentation were present while the run was executed, which does
not invalidate the permit's clean-revision binding.

## Deviations and observations

- The 2026-10-20 attempt-2 watchdog handshake defect was already corrected in
  protocol v2 and did not recur; the completion path disarmed cleanly.
- During the step 5 descent, 30 samples transiently exceeded ±2 °C from the
  setpoint before settling. This is expected ramp behaviour, not a failure; the
  qualifying dwell window of each step stayed within tolerance.
- `physical_stop_procedure_confirmed` is currently derived from the presence of
  the physical HIL device rather than from an independent human confirmation
  (`chamber_web/hil/supervised_profile.py`). Reviewers should treat the
  stop-procedure attestation as an automated derivation, not a human act.

## Outstanding

Any further physical profile run requires its own currently valid signed permit
bound to its exact clean revision, with a real operator and named witness
present. This engineering pass does not replace independent/site signatures or
grant R01 production release. The 2026-10-20 site acceptance record is still
unsigned, and the H01 hardware acceptance checklist entries remain
`NOT PROVIDED`.
