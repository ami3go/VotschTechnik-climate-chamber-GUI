# H02 supervised physical profile — site acceptance record

**Status: AWAITING HUMAN SIGNATURES — NOT INDEPENDENTLY ACCEPTED.**

This record is prepared from the immutable technical evidence. It must not be
marked accepted by software or by the operator alone. The site authority and
an independent reviewer must inspect the evidence, record any deviations, and
sign below using their real names and dates.

## Tested scope

- Test date: 2026-10-20
- Chamber: Vötsch VT 4011, serial `58566207770010`
- Run ID: `60e8f4da-ea08-4806-9c5c-1c2124f89eb0`
- GUI revision: `a0ecf17414cc7d3f4847f15aabcb9cd0692396f4`
- Driver revision: `9323e3701f3befedcc23b45170a851fd327f0bcc`
- Profile ID: `41f4e0eb-a71e-4b93-99ea-7aa4fb80ddcd`
- Profile revision SHA-256: `4afbdcdb9a5652dd9a7711bbf2608c63ce7172aca4b0e8ce4798c6ba9e9b5724`
- Permit approval reference: `H02-2026-10-20-03`
- Permit temperature envelope: 20–30 °C
- Application account used as operator: `admin`
- Witness recorded in permit: `User0`
- Technical result: `COMPLETED`, clean watchdog `RUN_DISARM`, no v3 watchdog
  fault, no restart latch, final authoritative `GOOD · STOPPED` readback

Controlled evidence index:
[`hil-evidence/h02-v3-2026-10-20/README.md`](../hil-evidence/h02-v3-2026-10-20/README.md).

## Required human review

- [ ] Confirm the real operator's printed name corresponds to the account audit.
- [ ] Confirm the real witness's printed name corresponds to `User0` and that the
  witness was physically present with the local emergency stop accessible.
- [ ] Verify the signed permit, public key, exact revisions and profile digest.
- [ ] Verify all checksums in `SHA256SUMS` and review the raw G07 events/samples.
- [ ] Review both earlier failed attempts and their verified STOP responses.
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
