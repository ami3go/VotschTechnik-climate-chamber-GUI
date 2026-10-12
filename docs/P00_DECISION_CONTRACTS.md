# P00 — Deterministic implementation contracts and outstanding site decisions

Status: **engineering contract proposed 2026-10-12; SITE/HIL APPROVAL PENDING**. This document closes ambiguous *software semantics* but does not grant physical operation. The current application is demo-only, and no hardware command is authorized by this text.

## Operator STOP, safety and ownership

- Web STOP is a command intent, **never an emergency stop**. Expose STOP_REQUESTED immediately; only fresh, GOOD authoritative hardware readback of non-running status permits VERIFIED_STOPPED. Lost command acknowledgement or lost readback is UNKNOWN/FAULT, with explicit local intervention, never success.
- STOP intent atomically advances the `chamber_id` fencing generation, rejects later queued writes from earlier generations and retains authorization for OPERATOR/ADMIN independent of their lease. An in-flight blocking command may finish before STOP; do not claim preemption. No automatic replay after disconnect.
- Site authority MUST sign per-model/firmware response policy for operator STOP, reach failure, power outage, measured-temperature limit breach, alarm, disk-full/recording failure, network loss and shutdown. Until then, real writes stay disabled; no generic automatic ramp-to-ambient/power-off behavior is approved.
- Approved per-operation time budgets and safe retries require model-specific testing. Software deadline expiration NEVER establishes physical STOP. After uncertainty, lock out new starts/setpoints until local verification and explicit reconciliation.
- Every physical mutation (including localhost HIL) requires authenticated server-side OPERATOR/ADMIN authorization, CSRF/origin protection, `chamber_id` binding and an audited action. Do not implement a unauthenticated local-control exception.

## Temperature, ramps and per-step state

- Certified temperature/gradient ranges and engineering units must come from a site-approved model/firmware capabilities record plus driver readback, not demo values or the driver's hard-coded numeric ranges. All values finite; inputs revalidated immediately before dispatch.
- Null ramp_up/ramp_down in a profile means `RESTORE_VERIFIED_BASELINE` for that direction, not `INHERIT_PREVIOUS_STEP`. Before running any profile that explicitly changes a gradient, capture both current hardware gradients and match them to a site-approved baseline; if either cannot be read back, reject the profile. On subsequent null step, restore baseline if different, verify readback **before** setpoint transition.
- A profile with only null ramps issues **zero** gradient writes, but must still meet the approved baseline/operating policy. Non-null ramps cannot be used without HIL certification of units, direction, bounds, readback, restore and STOP behavior.
- Gradient restore after abort/STOP is best effort under signed site policy; loss of readback is UNKNOWN/FAULT and requires local intervention. Snapshot baseline, resolved per-step values, attempted writes, readback and restoration outcome in immutable run evidence.
- Tests: changed up-ramp in step 1 and null in step 2 restores initial measured baseline; communication lost during restoration aborts progression; a device without verified ramp capability rejects any non-null ramp before START.

## Observed sample/time semantics (candidate v1 policy; virtual-clock tested)

- Default nominal poll interval: 2 s. Sample is eligible only if `GOOD`, monotonic observation age <=5 s, hardware identity matches current `chamber_id`, and its measurement is finite and within inclusive target ± tolerance. Maximum interval to credit observation continuity is **5 s**; longer gaps invalidate stabilization and stop dwell credit.
- If `stabilize_s == 0`, first eligible in-band observation qualifies. If `stabilize_s > 0`, need at least two distinct eligible observations spanning at least `stabilize_s` with all intervening sample gaps <=5 s and no observed excursions. A gap, ERROR/STALE sample, out-of-band observation, or PAUSE resets stabilization qualification when resuming.
- If `dwell_s == 0`, transition can occur immediately after stabilization; never infer stabilization from issuing the setpoint. Otherwise credit **only intervals bracketed by eligible observations**, each <=5 s; pause or an excursion yields no credit for that interval. For now, an excursion resets accumulated dwell to zero (not merely suspends it).
- Use monotonic deadlines for reach, stabilize, dwell, whole step and whole run. Reach begins after confirmed setpoint dispatch. Absolute step/run watchdogs never pause. At equality to deadline a sample may succeed if observed timestamp <= deadline; later samples fail. If a failure/FAULT was latched earlier, it takes precedence over equal-timestamp success. Clamp scheduler jitter; do not grant artificial dwell for skipped ticks.
- Every stage has an explicit finite maximum configured/validated at creation and again at run start, including zero-duration stages. Virtual-clock tests must exercise exact boundaries, clock adjustments, sparse observations, pause and same-time abort/measurement.

## Legacy profile conversion contract

- Detect historical six-column `target,ramp,tolerance,dwell,description,enabled` separately from canonical ten-column schema. Strict headers, maximum rows/bytes, finite numeric values and atomic failure are mandatory.
- Legacy `ramp` means **simulation slope**; map target/tolerance/dwell/notes/enabled to v1 fields, default stabilize_s=0 and reach_timeout_s to a separately validated operator configuration. Set both hardware gradient fields null. Do not infer hardware slope, and do not auto-start imported profiles.
- Preserve original CSV bytes, legacy ramp values and migration provenance in the versioned canonical archive (e.g. `legacy_import.csv` plus checksums/metadata). A stand-alone new-format CSV cannot preserve all legacy semantics; warn that conversion/export is lossy and provide a full ZIP or original download.
- Canonical machine CSV preserves text including formula-prefixed values; spreadsheet-safe CSV is a separate opt-in escape export that does not promise byte-identical round trips. Reject ZIP traversal, duplicate entries, unsafe expansion, and schema versions not explicitly supported.

## Crash-recoverable recording/journal contract

SQLite and filesystem changes are NOT mutually atomic. A single authoritative process owns append and reconciliation; SQLite journals metadata, and per-run filenames are server-generated under `data/chambers/<chamber_id>/runs/<uuid>/`.

1. `PREPARED`: atomically create immutable run snapshot and staged CSV headers/manifest, fsync files/parent directory, commit SQLite PREPARED referencing exact paths/checksums. No device command issued.
2. `START_INTENT`: transactionally commit immutable command intent, `chamber_id`, binding generation, run ID and timestamp before dispatch. Any crash from this point onward makes command effect uncertain.
3. `RUNNING`: only after hardware START and live readback; append monotonically increasing `sample_index`, with wall UTC and monotonic elapsed and QUALITY; persist events and flush within **5 seconds maximum exposure** (subject to signed recording failure policy).
4. `FINALIZING`: record intent and stop/fault evidence, fsync and atomically rename completed CSV/manifest, then transition SQLite to an immutable terminal state `COMPLETED/ABORTED/FAULT/INTERRUPTED`. Never produce a completed manifest after an unverified physical STOP.
5. On startup, reconcile SQLite and files by run UUID/chamber ID/sequence and checksum. `PREPARED` with no command intent may be cancelled as INTERRUPTED. Any `START_INTENT`, `RUNNING` or `FINALIZING` without verified terminal state becomes INTERRUPTED/UNKNOWN and requires operator verification. **Never auto-resume, auto-start or silently mark stopped.**

Fault-injection tests must kill the process before/after every DB commit, rename, fsync and START. They must check no fabricated samples, no duplicate indexes, correct immutable metadata, conservative uncertainty and recovery on ENOSPC. Full-disk and I/O errors latch FAULT and defer physical mitigation to site-signed policy. A 5 s buffered-data exposure target is not a guarantee under power failure; certify flush/durability separately.

## Pending safety signoff ledger (not approved)

| Decision requiring external evidence | State / gate |
|---|---|
| VT4011 exact hardware model/firmware/serial and maintained manual revision | PENDING SITE |
| Certified min/max temperature and allowed ramp units/capabilities | PENDING SITE + HIL |
| STOP/fault/alarm/outage responses; recovery authority and bounded latencies | PENDING SITE + HIL |
| Gradient hardware baseline, restoration behavior and monitoring accuracy | PENDING SITE + HIL |
| Physical service/shutdown and unattended operation conditions | PENDING SITE + HIL |
| Authorized branding/assets and Windows offline supported baseline | PENDING OWNER / W02 |

Do not change status to approved without recorded evidence, approver and revision. Until then keep all hardware writes and hardware gradients disabled.
