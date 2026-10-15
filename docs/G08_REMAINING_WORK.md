# G08 — Remaining security and deployment work

**Snapshot:** 2026-10-13. This is the durable handoff and acceptance checklist for [G08 PR #29](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/29), not evidence of release approval.

**Implementation location:** `feat/g08-full-security` ([branch](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/tree/feat/g08-full-security)).
Do not duplicate the security implementation or create another identity/session authority. Continue the existing [G08-min PR #25](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/25) `SecurityStore` / `AuthorizedChamber` architecture (PR #25 **merged** on 2026-10-13).
The branch initially diverged substantially from `main`; independently verify reconciliation and the final diff before merge.

## Current implementation submitted for GitHub testing

PR #29 includes account lifecycle/recovery, application/transport security, audit integrity and retention, SQLite backup/staged restore, Windows launcher policy, offline update verifier, and adversarial tests. See [security threat model and operations](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/blob/feat/g08-full-security/docs/G08_FULL_SECURITY.md) and [self-review](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/blob/feat/g08-full-security/docs/G08_SECURITY_REVIEW.md). These are **implementation claims**, not validated production assurances.

## Required before merging G08 software to main

- [x] Prerequisite G08-min #25 merged to `main`.
- [ ] Reconcile the **existing** PR #29 head with current `main`, including changes from G02/G03/G04/G05/G06/G07 and the merged authentication code; resolve conflicts intentionally, not with blanket `ours`/`theirs`.
- [ ] Retarget PR #29 to `main`; inspect the complete final diff, resulting security interfaces, reviews, and changed-file ownership. Preserve single-chamber mock-only behavior, G04 STOP fencing, G06 runner and G07 recording boundaries.
- [ ] Conduct independent security/architecture review; fix every code-level BLOCKER/HIGH finding. Specifically validate session fixation and cookie identifier rotation, WebSocket authorization during logout/role change, backend command path authorization and pre-dispatch audit durability.
- [ ] Run adversarial unit/integration tests for expiry, fixation/replay, CSRF, Host/Origin, WebSocket cross-origin, brute force, throttling, viewer escalation, role revocation/concurrent sessions, recovery token misuse, audit tampering, backup/restore/schema failures, insecure LAN configuration and invalid certificates.
- [ ] Run final-source-commit Windows Python 3.10/3.12 NiceGUI/security workflow and W01 frozen/offline packaging workflow. Record **the tested head SHA, workflow run URLs, and results**; do not cite earlier or unrelated green builds as final-head evidence.
- [ ] Review dependencies/secrets, secure failure logging and data directory permissions; add explicit negative tests that unsigned/incomplete offline bundles are rejected.
- [ ] Only when final-head CI and independent review pass, mark PR ready and merge via the repository's normal protections. Update `docs/DEVELOPMENT_SEQUENCE.md` and `docs/READINESS_FINDINGS.md` with actual commit and evidence rather than projected closure.

## Security and operational release blockers (even after software merge)

- [ ] **LAN NO-GO:** site-signed network and security policy, exact permitted hosts/origins, HTTPS/WSS with PKI validation and certificate rotation, firewall/client allowlist, Windows NTFS owner/DACL review for credentials/keys, real-browser CSRF/Host/DNS-rebinding/WebSocket tests and session-cookie verification.
- [ ] **Audit and recovery:** independent signing key escrow, protected and capacity-limited evidence retention, off-device tamper-evident export where required, operator-approved password/recovery procedure and tested backup restore with no reinstated active sessions.
- [ ] **Windows service lifecycle (W02):** supervised Windows startup/shutdown, service identity and rights, logoff/restart/sleep/power-loss handling, crash-uncertainty reconciliation, no automatic run restart; verify in clean Win10/11 x64 offline VMs.
- [ ] **Offline supply chain:** signed release artifacts and pinned publisher trust, independent digests, full transitive dependency lock/hashes/SBOM and vulnerability review, integrity-check/rollback drills, clean-machine freeze and installation acceptance.
- [ ] **Physical chamber NO-GO:** signed [P00 site decision contracts](P00_DECISION_CONTRACTS.md), certified model/firmware envelope and STOP/fault policy, H01 actual device HIL and G05/G06/G07 integration tests. Keep the real Vötsch adapter and all physical writes disabled until separately approved.

## Non-negotiable control rules

- One active physical device at most; no new fleet UI or second hardware controller.
- Browser/API mutations require live authenticated, authorized, CSRF/Origin-checked and audited server-side permission. UI hiding alone is insufficient.
- **Authorized STOP** may bypass the *operator lease*, but never authentication, authorization, audit or existing G04 fencing. A web STOP is not an emergency stop or a claim of verified physical STOP.
- No automatic replay or resumption following restart, outage, unknown device state or command timeout; require fresh verified readback and explicit reconciliation.
- GUI services never issue vendor protocol commands: the vendor-specific adapter must rely exclusively on the external Vötsch Python driver. Do not change the driver in G08.

**Release status:** software G08 candidate / review and CI pending; production LAN and real hardware operation **NOT APPROVED**.

## Verified integration follow-up — 2026-10-14

- [x] Existing G08 PR #29 synchronized with `main` `4be73ed` by an explicit two-parent reconciliation commit `cd59d5e`; GitHub reported 0 commits behind and clean mergeability after reconciliation.
- [x] Retained H01 #32, cross-platform setup #33, G03-C/G04/G06 and G08-min #25; did not fabricate acceptance of still-open G05 #28 or G07-A #27.
- [x] Repaired the missing G02-B NiceGUI loopback test-client setting responsible for the Windows 3.10/3.12 HTTP 403 in [run 38457405604](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38457405604), without relaxing application Host validation.
- [x] Added an adversarial regression detecting audit tail-row and HMAC-row deletion through SQLite's allocation watermark.
- [ ] Obtain passing **final-commit** Windows 3.10/3.12 NiceGUI/security, H01 web/GUI and W01 frozen CI.
- [ ] Independent security review and closure of HIGH code-level findings: off-device audit anchoring, signed-backup rollback protection, LAN/Windows credential ACLs, actual cookie/WS revocation/fixation behavior.
- [ ] Obtain required external approval, then merge PR #29. Do not mistake this AI-assisted assessment for the approval.
- [ ] W02 offline Win10/11 certification, trusted service lifecycle and actual LAN/physical HIL/site authorization — release gates remain **NO-GO**.

The newly added SQLite tail check is a **partial hardening**, not a closure of the HIGH audit anchor requirement. Web STOP remains an audited ordinary control command, not an emergency stop. Physical Vötsch connectivity stays disabled.

### Recovery/tamper regression follow-up

The existing G08 security authority now rejects (a) a missing SQLite identity DB with surviving audit/backup keys and (b) removal of an established HMAC checkpoint while its key remains. Positive G08-min legacy migration and negative tampering/reboot tests are included. Check final-head Windows CI on both supported Python versions before marking these software defects resolved. Complete loss of both database **and** trust keys is not recoverable or attestable without operator-controlled off-device key escrow and monotonic external evidence.

- [ ] Confirm the fix for the concurrent-first-start Windows regression from [run 38618249624](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38618249624): key plus audit-checkpoint setup is serialized via SQLite; six-worker and original simultaneous-bootstrap regressions must both pass on final head. This is a startup availability fix, not relaxed audit verification.
