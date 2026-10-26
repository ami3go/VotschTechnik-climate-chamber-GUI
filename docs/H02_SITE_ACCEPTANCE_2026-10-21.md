# H02 supervised physical profile — site acceptance record

**Status: AWAITING HUMAN SIGNATURES — NOT INDEPENDENTLY ACCEPTED.**

This record is prepared from the immutable technical evidence. It must not be
marked accepted by software or by the operator alone. The site authority and
an independent reviewer must inspect the evidence, record any deviations, and
sign below using their real names and dates.

## Tested scope

- Test date: 2026-10-21
- Chamber: Vötsch VT 4011, serial `58566207770010`
- Run ID: `5be68792-77f7-471b-946c-20558f1e6502`
- GUI revision: `74a816d9d9bbb7acbb901334ef457dbc416f7641`
- Driver revision: `9323e3701f3befedcc23b45170a851fd327f0bcc`
- Profile ID: `41f4e0eb-a71e-4b93-99ea-7aa4fb80ddcd`, revision 1
- Profile revision SHA-256: `4afbdcdb9a5652dd9a7711bbf2608c63ce7172aca4b0e8ce4798c6ba9e9b5724`
- Permit approval reference: `H02-2026-10-21-01`
- Permit temperature envelope: 20–30 °C
- Application account used as operator: `admin`
- Witness recorded in permit: `User0`
- Technical result: `COMPLETED`, clean watchdog `RUN_ARM`/`RUN_DISARM`, no
  watchdog fault for this run, no restart latch, final authoritative
  `GOOD · STOPPED` readback
- Pre-run condition: audited STOP reconciliation of the durable device lease
  (`chamber.reconcile_stop` `INTENT` → `SUCCESS`) before any execution

Controlled evidence index:
[`hil-evidence/h02-v4-2026-10-21/README.md`](../hil-evidence/h02-v4-2026-10-21/README.md).

## Required human review

- [ ] Confirm the real operator's printed name corresponds to the account audit.
- [ ] Confirm the real witness's printed name corresponds to `User0` and that the
  witness was physically present with the local emergency stop accessible.
- [ ] Verify the signed permit, public key, exact revisions and profile digest.
- [ ] Verify all checksums in `SHA256SUMS` and review the raw G07 events/samples.
- [ ] Confirm the audited STOP reconciliation preceded execution and that the
  controller returned to `VERIFIED_STOPPED` before the run was admitted.
- [ ] Review the transient excursion outside ±2 °C during the step 5 descent and
      the automated derivation of `physical_stop_procedure_confirmed` from device
      presence rather than from a human confirmation.
- [ ] Confirm the final chamber state and approved return-to-baseline condition.
- [ ] Record deviations, residual risks and the precise accepted operating scope.
- [ ] State whether this is engineering acceptance only or permits a controlled
  pilot. This record cannot grant production release by implication.

Deviations/residual risks/limitations:

______________________________________________________________________________

______________________________________________________________________________

Decision (select one): **ACCEPT / ACCEPT WITH LIMITATIONS / REJECT**

Real operator printed name: ____________________  Signature/date: ______________

Real witness printed name: _____________________  Signature/date: ______________

Independent reviewer name/organization: ______________________________________

Independent reviewer signature/date: _________________________________________

Site safety authority name/title: _____________________________________________

Site safety authority signature/date and GO/NO-GO: ____________________________

Accepted scope and expiry, if any: ____________________________________________

R01 production release remains **NO-GO** unless every separate release gate is
closed. Signing this limited H02 record does not certify W02 packaging, LAN
security, long-duration unattended use, fault injection, auxiliary outputs,
gradients, or production operation.
