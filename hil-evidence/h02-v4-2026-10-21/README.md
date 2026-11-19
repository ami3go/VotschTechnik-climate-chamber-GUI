# H02 v4 controlled evidence package

This directory is the repository copy of the successful supervised physical
profile run `5be68792-77f7-471b-946c-20558f1e6502` on 2026-10-21. It was
captured locally from the application-owned journal, watchdog state directory,
and H02 authorization directory after the run.

## Integrity and provenance

- Chamber: Vötsch VT 4011, serial `58566207770010`
- Tested GUI revision: `74a816d9d9bbb7acbb901334ef457dbc416f7641`
- Driver revision: `9323e3701f3befedcc23b45170a851fd327f0bcc`
- Profile revision SHA-256: `4afbdcdb9a5652dd9a7711bbf2608c63ce7172aca4b0e8ce4798c6ba9e9b5724`
- Permit approval reference: `H02-2026-10-21-01`
- Terminal state: `COMPLETED`; 229 journal events; 200 samples
- Journal artifacts were checked with `RunStore.verify_artifacts` before copy.
- `SHA256SUMS` records every preserved raw artifact.
- The watchdog restart-latch file was absent during and after this run.

Run artifacts in `run/` are the application's checksum-verified materialized
G07 record. `authorization/` contains the signed run permit and its public
verification key. The site private key is intentionally excluded and remains
under the approver's local control.

The `watchdog/` files are the persistent raw process records and therefore
retain earlier sessions as well. Events for this run are identified by its run
ID and its matching `RUN_ARM`/`RUN_DISARM` pair. `watchdog-latch-cleared.json`
records the latch clearance performed on 2026-10-20 and is included only to
show the complete watchdog state directory; no latch was raised in this run.

Verify this package from this directory with:

```sh
sha256sum -c SHA256SUMS
```

The technical result is recorded in
`../H02_V4_PHYSICAL_PASS_2026-10-21.md`. Formal independent/site acceptance is
separate and remains unsigned until the named people complete
`docs/H02_SITE_ACCEPTANCE_2026-10-21.md`.
