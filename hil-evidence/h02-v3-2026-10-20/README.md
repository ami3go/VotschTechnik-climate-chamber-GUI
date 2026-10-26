# H02 v3 controlled evidence package

This directory is the repository copy of the successful supervised physical
profile run `60e8f4da-ea08-4806-9c5c-1c2124f89eb0` on 2026-10-20. It was
captured locally from the application-owned journal, watchdog state directory,
and H02 authorization directory after the run.

## Integrity and provenance

- Chamber: Vötsch VT 4011, serial `58566207770010`
- Tested GUI revision: `a0ecf17414cc7d3f4847f15aabcb9cd0692396f4`
- Driver revision: `9323e3701f3befedcc23b45170a851fd327f0bcc`
- Profile revision SHA-256: `4afbdcdb9a5652dd9a7711bbf2608c63ce7172aca4b0e8ce4798c6ba9e9b5724`
- Terminal state: `COMPLETED`; 227 journal events; 198 samples
- Journal artifacts were checked with `RunStore.verify_artifacts` before copy.
- `SHA256SUMS` records every preserved raw artifact.
- The watchdog restart-latch file was absent after the successful run.

Run artifacts in `run/` are the application's checksum-verified materialized
G07 record. `authorization/` contains the signed run permit and its public
verification key. The site private key is intentionally excluded and remains
under the approver's local control.

The `watchdog/` files are full raw process records and therefore also retain
the two earlier failed attempts. Events for the successful run are identified
by its run ID and its matching `RUN_ARM`/`RUN_DISARM` pair. Those earlier fault
records are not faults from the v3 run.

Verify this package from this directory with:

```sh
sha256sum -c SHA256SUMS
```

The technical result is recorded in
`../H02_V3_PHYSICAL_PASS_2026-10-20.md`. Formal independent/site acceptance is
separate and remains unsigned until the named people complete
`docs/H02_SITE_ACCEPTANCE_2026-10-20.md`.
