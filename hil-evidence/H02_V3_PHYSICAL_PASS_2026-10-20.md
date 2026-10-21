# H02 supervised physical profile — v3 pass

This addendum records the final physical retest. It supersedes the earlier
NO-GO status in `docs/H02_PHYSICAL_PROFILE_RESULT_2026-10-20.md` for the exact
software revision and signed permit listed below. The evidence was committed
only after the run; the permit remains bound to its tested parent revision.

## Result

**PASS** — the profile reached `COMPLETED`, the controller was verified
`STOPPED`, watchdog supervision disarmed cleanly, no watchdog fault occurred
during this run, and no watchdog latch remained.

## Bound identities

- Run ID: `60e8f4da-ea08-4806-9c5c-1c2124f89eb0`
- Chamber ID: `hil-votsch`
- Chamber: Vötsch VT 4011, serial `58566207770010`
- Operator: `admin`
- Witness: `User0`
- Profile ID: `41f4e0eb-a71e-4b93-99ea-7aa4fb80ddcd`
- Profile revision SHA-256: `4afbdcdb9a5652dd9a7711bbf2608c63ce7172aca4b0e8ce4798c6ba9e9b5724`
- GUI commit: `a0ecf17414cc7d3f4847f15aabcb9cd0692396f4`
- Driver commit: `9323e3701f3befedcc23b45170a851fd327f0bcc`
- Permit payload fingerprint recorded by watchdog: `7cba454715083bc20e5ed4e31753ad34c797267fe41c54efac9bb61206ee5912`
- Signed permit file SHA-256: `fff53e4a6c6c431604526c7481472f961ef9eddb3f67b77a48b659df1ac8a7e5`

## Execution evidence

- Journal start: `2026-10-20T16:28:08.180837+00:00`
- Watchdog `RUN_ARM`: `2026-10-20T16:28:08.196377+00:00`, controller generation 127
- Journal terminal event: `2026-10-20T16:35:02.023442+00:00`
- Watchdog `RUN_DISARM`: `2026-10-20T16:35:02.632234+00:00`
- Terminal state: `COMPLETED`
- Steps completed: 5 of 5
- Journal events: 227
- Telemetry samples: 198
- Journal manifest SHA-256: `7a06908561d7ef9566708b96bbf1b9c1b18e4c0506f0fe9ee5bf3bbb22a9fddd`
- Exported `events.csv` SHA-256: `cb61157825f2925b29e0cb213abb441942482fe00d066e8b5b0f5bcdfc9d748e`
- Exported `samples.csv` SHA-256: `fa0404035f82c238d3d1c3d5405ad81ab95bb475da913d080905a106dc09c2e0`
- Exported `snapshot.json` SHA-256: `1622df214c7f648a8450a32deb88cbfeb9d0f37f5ee1f05c8088748a6e8b9e08`

The watchdog child log for the protocol-v2 process contains startup and
configuration events only; it contains no `FAULT` for this run. The two fault
records elsewhere in the persistent log belong to the earlier, superseded
attempts. The persistent watchdog latch file was absent after the run.

## Final physical state

The post-run dashboard reported:

- `PHYSICAL HIL · GOOD · STOPPED`
- model and serial verified
- chamber state `STOPPED`
- measured temperature 25.5 °C
- setpoint 25.0 °C
- profile completed 5/5

Screenshot: `hil-evidence/profile-v3-postrun-dashboard.png`

## Local verification

The committed tree passed the complete software test suite before this run:
`562 passed, 9 skipped, 196 subtests passed`. The server remains local at
`http://127.0.0.1:8095`; no public internet access was used for this retest or
for creating this addendum.
