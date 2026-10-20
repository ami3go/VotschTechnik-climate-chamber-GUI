# H02 — first supervised physical profile run (runbook)

**Status: PREPARED, NOT EXECUTED.** Nothing in this repository has run a profile on
the real chamber. This runbook needs the site approver, a named operator and a named
witness physically at the chamber. It cannot be run unattended or by automation.

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
   checkout that will run the test; any later update of either requires a new permit.
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

## Abort and recovery
A watchdog fault latches the host and refuses further starts until an on-site review
runs `python scripts/h02_watchdog_reset.py ... --confirm-clear`
(see [H02_WATCHDOG_OPERATIONS.md](H02_WATCHDOG_OPERATIONS.md)).
