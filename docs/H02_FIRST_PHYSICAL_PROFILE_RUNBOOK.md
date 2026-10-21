# H02 — first supervised physical profile run (runbook)

**Status: EXECUTED — two engineering passes recorded.** Run `60e8f4da-ea08-4806-9c5c-1c2124f89eb0` (2026-10-20, GUI `a0ecf17`) and run `5be68792-77f7-471b-946c-20558f1e6502` (2026-10-21, GUI `74a816d`) both reached `COMPLETED` with a clean watchdog disarm and a final `GOOD · STOPPED` readback; evidence is indexed under `hil-evidence/`. Formal site/independent acceptance signatures are still **PENDING** — see [`H02_SITE_ACCEPTANCE_2026-10-21.md`](H02_SITE_ACCEPTANCE_2026-10-21.md) and [`H02_SITE_ACCEPTANCE_2026-10-20.md`](H02_SITE_ACCEPTANCE_2026-10-20.md).

This runbook still governs **every subsequent** supervised run. It needs the site approver, a named operator and a named witness physically at the chamber. It cannot be run unattended or by automation.

## Roles
- **Approver** — decides the limits and signs the permit (private key stays with them).
- **Operator** — signs in to the web GUI and starts the run.
- **Witness** — stands at the chamber next to the emergency stop for the whole run.

## 1. Prepare (approver, before the run)
1. Create a *short, narrow* profile in simulation (for example one 25 °C step of a few
   minutes, no digital outputs, no ramp-rate changes) and note its profile ID and revision.
2. `python -m scripts.h02_sign_permit keygen --private-key site.key --public-key-out site.pub`
   (once; keep `site.key` off the server PC).
3. `python -m scripts.h02_sign_permit template --out spec.json --chamber-id <ID> --serial <SERIAL> --profile-id <P> --revision <N>`
4. Edit `spec.json`: fill every `REPLACE_ME`, and review **every** limit, including the
   proposed watchdog values. Keep the temperature range inside the software envelope.
5. The permit is bound to the exact GUI and driver commits. Sign on the machine and
   checkout that will run the test; any later update of either requires a new permit
   (see §4 for the binding, expiry and renewal rules).
6. `python -m scripts.h02_sign_permit sign --spec spec.json --private-key site.key --out permit.json`
   — read the printed permit and type `SIGN` only if you approve it.

## 2. Configure (administrator)
Settings > Chamber Connection > *Supervised profile runs (H02)*: permit path, site public
key, witness name (exactly as in the permit). Save — the permit is verified on save —
then restart the server. The independent watchdog starts with the server.

## 3. Run (operator + witness present)
1. Confirm the chamber is stopped and inside the permitted range.
2. Admin tab: claim the operator lease. Profiles tab: run the permitted revision.
3. The witness watches the chamber. Press the chamber's own emergency stop on any doubt;
   the web STOP is not an emergency stop.
4. After the run: confirm the chamber is STOPPED, keep the run journal and
   `watchdog-*.jsonl` evidence, and record the result in the H02 report.

## 4. Renewal, expiry and revision binding

The signed permit is bound to **one exact clean GUI revision, one driver revision,
one profile revision digest, one operator account, one witness, one temperature
envelope and one validity window**. Nothing about it survives a change to any of
those.

**The permit binds the installed commit, not the branch.** `gui_commit` is compared
against the verified installed revision at server start
(`chamber_web/hil/supervised_profile.py:159`). Consequently:

- Any commit, amend or checkout after the permit was signed **invalidates it**. A new
  run against a moved `HEAD` needs a newly signed permit; the old one cannot be
  reused or re-signed.
- The commit must be clean. Untracked files are tolerated, modified tracked files are
  not.
- The permit must still be inside its window at the moment of every dispatch tick; it
  is revalidated before each tick, so an expiry stops further commands instead of
  letting a run continue.

**Expiry locks the application out, not just the run.** The saved chamber settings
keep pointing at the permit file, and the permit is verified while the server starts.
Once the window has closed, a restart raises `AdmissionDenied: H02 site permit
expired, premature or overlong` and the physical server no longer starts. Before an
expiry, either renew the permit, or set Settings > Chamber Connection back to
`simulator` and restart, so the software stays usable.

**Renewal sequence.**

1. `python -m scripts.h02_sign_permit template --out spec.json --chamber-id <ID> --serial <SERIAL> --profile-id <P> --revision <N>`
   — the template fills `profile_revision_sha256`, `gui_commit` and `driver_commit`
   from the **current** checkout, so always regenerate it on the machine and checkout
   that will run the test.
2. Fill every `REPLACE_ME` (site method, approval reference, operator, witness,
   specimen restrictions, temperature range) and review every limit, including the
   proposed watchdog values. The defaults are deliberately small; they must cover the
   profile's real reach time and dwell, or admission fails with "Planned G06
   per-step deadline exceeds site permit".
3. Set `valid_from_utc` / `valid_until_utc` to the intended run window. The verifier
   rejects a window longer than 14 days.
4. `python -m scripts.h02_sign_permit sign --spec spec.json --private-key site.key --out permit.json`
   — read the printed permit and type `SIGN` only if you approve it. The tool refuses
   unfilled placeholders, refuses to sign without an interactive terminal, and
   re-verifies the result with the same verifier the server uses.
5. Install the new permit, update Settings > Chamber Connection (permit path, site
   public key, witness), save, restart the server and confirm the dashboard shows
   `PHYSICAL HIL` rather than `SIMULATION`.

## Abort and recovery
A watchdog fault latches the host and refuses further starts until an on-site review
runs `python scripts/h02_watchdog_reset.py ... --confirm-clear`
(see [H02_WATCHDOG_OPERATIONS.md](H02_WATCHDOG_OPERATIONS.md)).
