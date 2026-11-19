# H02 supervised physical profile — v4 pass

This addendum records the supervised physical run performed on 2026-10-21
against the current clean repository head. It supersedes the earlier NO-GO
status in `docs/H02_PHYSICAL_PROFILE_RESULT_2026-10-20.md` only for the exact
software revision and signed permit listed below. The evidence was committed
only after the run; the permit remains bound to its tested parent revision.

## Result

**PASS** — the profile reached `COMPLETED`, the controller was verified
`STOPPED`, watchdog supervision disarmed cleanly, no watchdog fault occurred
during this run, and no watchdog latch was raised.

## Bound identities

- Run ID: `5be68792-77f7-471b-946c-20558f1e6502`
- Chamber ID: `hil-votsch`
- Chamber: Vötsch VT 4011, serial `58566207770010`
- Operator account: `admin`
- Witness: `User0`
- Profile ID: `41f4e0eb-a71e-4b93-99ea-7aa4fb80ddcd`, revision 1
- Profile revision SHA-256: `4afbdcdb9a5652dd9a7711bbf2608c63ce7172aca4b0e8ce4798c6ba9e9b5724`
- GUI commit: `74a816d9d9bbb7acbb901334ef457dbc416f7641`
- Driver commit: `9323e3701f3befedcc23b45170a851fd327f0bcc`
- Permit approval reference: `H02-2026-10-21-01`
- Permit validity window: `2026-10-21T08:02:35Z` .. `2026-10-21T16:02:35Z`
- Permit payload fingerprint recorded by watchdog: `79dc3041eb6d6976abde80e3e0aebd5cf66cea5fd21d9aaffd917898da204490`
- Signed permit file SHA-256: `17a94d295718a8b6951656b16c89b46eb20191823d4a1d509336b362849c0cc1`

## Pre-run safety state

The durable device lease carried `uncertain=1` from the earlier server restart,
so the controller reported `UNKNOWN · STOP/reconciliation required` even though
the chamber itself read `GOOD · STOPPED`. An audited **Admin reconcile STOP**
was performed first: independent physical device readback confirmed `STOPPED`,
the fence was cleared, and the controller returned to `VERIFIED_STOPPED` at
controller generation 130 with no latch. Audit trail: `chamber.reconcile_stop`
`INTENT` then `SUCCESS`. The operator lease was then claimed by the permit-named
operator account and handed over to the profile runner
(`chamber.manual_to_profile` `SUCCESS`).

## Execution evidence

- Journal start: `2026-10-21T10:41:46.960653+00:00`
- Watchdog `RUN_ARM`: `2026-10-21T10:41:46.976496+00:00`, controller generation 130
- Journal terminal event: `2026-10-21T10:48:42.598952+00:00`
- Watchdog `RUN_DISARM`: `2026-10-21T10:48:43.565654+00:00`
- Terminal state: `COMPLETED`
- Steps completed: 5 of 5 (25, 26, 27, 28, 25 °C)
- Journal events: 229
- Telemetry samples: 200, all `GOOD`
- Journal manifest SHA-256: `33c72b4d91b31db29d97d8f9561752a369e466b81264d9f934f4dbd7bcebcb51`
- Exported `events.csv` SHA-256: `6c003a4c27c5934f9a965c7bb3d9a4716164e9ca16fbc820cc9279cbe0922ef0`
- Exported `samples.csv` SHA-256: `1392ebc3ca09740f787c9cbf6c662da3de42fed4957f1fdd8e546f867380810c`
- Exported `snapshot.json` SHA-256: `93109ca53c6ff23d45d7330853b3ce318729f334ff5bfe2d13dcca23281a9a0c`

Measured temperature over the whole run stayed between 24.81 °C and 27.96 °C,
inside the permit envelope 20–30 °C. Every step qualified inside its ±2 °C
tolerance; the worst deviation during each step's final 30 s was 0.76, 0.96,
1.23, 1.27 and 1.67 °C respectively.

The watchdog child log for the protocol-v2 process contains startup and
configuration events only; it contains no `FAULT` for this run. The persistent
watchdog latch file was absent during and after the run.

## Final physical state

The post-run dashboard reported:

- `PHYSICAL HIL · GOOD · STOPPED`
- model and serial verified
- chamber state `STOPPED`
- measured temperature 25.5 °C
- setpoint 25.0 °C
- profile completed 5/5
- controller `VERIFIED_STOPPED · connected · generation 131 · verified STOP`

Screenshots: `hil-evidence/v4-postrun-dashboard.png`,
`hil-evidence/v4-run-history.png`, `hil-evidence/v4-admin-lease-released.png`.

## Local verification

The server remained local at `http://127.0.0.1:8095`; no public internet access
was used for this run or for creating this addendum. After the run, the exact
tested tree passed the complete software test suite: `564 passed, 9 skipped,
196 subtests passed`. The recorded result is in
`docs/H02_PHYSICAL_PROFILE_RESULT_2026-10-21.md`.

Any further physical profile run still requires its own currently valid signed
permit bound to its exact clean revision, with a real operator and named
witness present. This engineering pass does not replace independent/site
signatures or grant R01 production release.
