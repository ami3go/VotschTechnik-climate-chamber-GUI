# G08 focused security and architecture review

Review scope: code in `feat/g08-full-security` initially stacked above
[G08-min PR #25](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/25),
including identity/store, NiceGUI ASGI middleware, recovery, backups,
audit chain, Windows offline launcher and mock-only command ownership.
**This is an AI-assisted self-review, NOT an external penetration test or
independent human signoff.** Physical chambers were never connected.

## Findings and remediations on the branch

| Finding | Severity | Evidence / mitigation | Disposition |
|---|---|---|---|
| G08-R1 — Windows SQLite backup file kept open; readonly file flush | HIGH | Windows CI Python 3.10 initially failed 2 backup tests with `Bad file descriptor` and `WinError 32`. Fixed in `chamber_web/security/backup.py` by explicit `closing(sqlite3.connect(...))` on *all* snapshot/integrity/restore paths and `r+b` backup fsync. | Fixed in code; **final-SHA Windows CI pending** |
| G08-R2 — Login KDF CPU/RAM spike + unbounded guessed-user failure rows | HIGH (availability) | Cap concurrent scrypt checks to 2, do not write per-account failure records for unknown usernames, bound peer rows at 4096, enforce throttling inside SQLite serialized transaction. No viewer/hardware bypass introduced. | Code mitigation; stress/security verification pending |
| G08-R3 — Invalid/ambiguous Host and LAN origin | HIGH | Every HTTP/WS request now requires allowlisted canonical Host, matching browser Origin for writes/WS; reject Host with path/query, duplicate headers, unsafe bind address, malformed origin or public client CIDRs, and missing TLS. | Code mitigation; actual HTTPS/WSS client and DNS-rebind tests pending |
| G08-R4 — Security policy drift between bootstrap CLI and running server | MEDIUM | `SecurityStore.from_environment()` is used by NiceGUI and local recovery/bootstrap CLIs; constructor still supports deterministic test overrides. Invalid deployment/security policy fails startup. | Code mitigation; automated policy tests added |
| G08-R5 — Audit database modification and storage growth | HIGH (forensic evidence) | HMAC chain across security events, versioned database, bounded retention with checkpoint anchor, missing-key/startup integrity refusal, sanitized free-form diagnostics. | Code mitigation; **DB and key compromised together remains forgeable** |
| G08-R6 — Backup restore replay of active sessions / recovery tokens | HIGH | Manifest HMAC, separate key, SQLite integrity validation, never in-place overwrite, restore into new empty root and revoke sessions/recovery tokens; audit key escrow. | Code mitigation; final-SHA Windows restore tests pending |
| G08-R7 — Browser-fixed NiceGUI user-storage cookie | HIGH (session hardening) | Login generates a fresh 256-bit server-side session token and fresh CSRF token, old tokens may remain only as independent sessions, role changes revoke; signed, HttpOnly, SameSite cookies with TLS Secure on LAN. | **OPEN release blocker**: actual cookie-ID rotation / fixation test in a real LAN browser, socket session continuity and cross-tab invalidation |
| G08-R8 — Windows logoff, forced shutdown and service recovery | BLOCKER (operational deployment) | W01 is intentionally simulated and per-user portable; no automatic resumption and no claim of physical STOP. P00 demands confirmed fresh readback and explicit reconciliation on restart. | **OPEN for W02**: trusted Windows service supervisor/OS account, logoff/reboot/sleep recovery, site-approved commanded-stop strategy |
| G08-R9 — Offline update trust root | HIGH (supply chain) | Added PowerShell offline verifier requiring external digest and pinned Authenticode publisher certificate, complete ZIP manifest file hashes, no execution/install. W01 unsigned simulator is intentionally rejected. | **OPEN for W02**: signed release artifacts, full transitive locked wheels, SBOM, offline Win10/11 VM release acceptance |
| G08-R10 — Inadequate host key ACL/firewall/PKI review | BLOCKER (LAN deployment) | Code checks POSIX key permissions and SSL certificate dates/hostname; protected-path and client CIDR requirements documented. | **OPEN**: Windows NTFS owner/DACL validation, firewall isolation, trusted CA/cert rotation, HTTPS/WSS penetration testing |

## Integration invariants

1. Exactly one single-device G04 manager/controller. G08 does not import
   manufacturer driver protocols or enable real Vötsch adapter connections.
2. Existing `AuthorizedChamber` remains the only browser-origin control
   boundary; G08 does not introduce an alternative G04 mutation API.
   ADMIN/OPERATOR STOP remains independent of the current G04 lease but
   requires authenticated CSRF-authorized action and durable intent audit.
3. G06 profile runner and G07 execution recorder remain distinct owners;
   G08 guards their external commands but does not own profile execution
   state or run journals.
4. HTTP Origin/Host/peer ACL is defense-in-depth, not identity; every
   privileged callback still requires live server-side session and role
   enforcement. Disable the LAN mode when no site PKI and firewall approvals.
5. Signed site P00 safety limits, H01 chamber-in-loop STOP/FAULT readback,
   G05/G06/G07 integration, W02 packaging/service certification and
   production approval remain blocked.

## Required acceptance evidence

- A standalone security reviewer and final-head Windows 3.10/3.12 CI.
- W01 frozen Windows ZIP/launcher packaging, install/version smoke and
  G08 verifier negative test on same final commit.
- Actual LAN browser tests for TLS validation, Cookies Secure+HttpOnly+
  SameSite, Session fixation, CSRF, WebSocket Origin, rebinding, duplicate
  Host, logout and immediately revoked role.
- Windows service-mode logoff/restart/power-fail reconciliation and offline
  restore/upgrade rollback drills; site-admin ACL/firewall inspection.
- Out-of-band approved signed bundle provenance with SBOM/transitive wheel
  hashes. No physical write until P00 site-signed and H01 HIL.

**Merge decision: BLOCKED.** G08-min PR #25 is merged. PR #29 remains draft
and has been reconciled against main for CI. Do not merge until a reviewed
final diff, clean final-source CI and all code-level BLOCKER/HIGH fixes are
independently verified. Final operational LAN/physical release is independently
NO-GO even after software CI.

## 2026-10-13 final-head re-review checkpoint

- Head before CI correction: `e8b54c0f3d0f1b8cfd132750615bbd8852cedb61`. On GitHub Actions run [38452378497](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38452378497), the Python 3.10 job failed and Python 3.12 job ended cancelled; **both** job logs show two failed G03-C NiceGUI UI tests at `User.open('/profiles')` or `User.open('/login')` with HTTP 403. The previous security tests and profile service tests passed.
- Root cause: G08 full Host validation permits loopback `127.0.0.1:8080` / `localhost:8080`, whereas NiceGUI's in-process `User` fixture defaults to the `testserver` authority. The middleware correctly rejects that untrusted hostname. Tests now configure the fixture's HTTP client to use the loopback authority rather than weakening Host validation. A negative ASGI test explicitly requires `testserver` to remain rejected in production middleware.
- Corrective commits: `bac2bde65c7bc78260440426a944eaad44a05217`, `286ef01ba32c7396b0b04f1bf3b8995d5d018ffd`, `d8968d6dd07ec60aef69ac8937749fed4cb7f055`. Final-head CI must be rerun and **completed**; in-flight or older-head workflows are not passing evidence.
- **Still OPEN HIGH:** audit tail-truncation not anchored outside SQLite; historical G08-min audit authenticity cannot be established retroactively; signed backup replay/rollback policy missing; Windows DACL/owner enforcement not implemented. These are material security issues, not documentation-only closure. Review independently before merge.
- Independent human/security approval is still absent. `main` merge and LAN/physical deployment are NOT authorized.

## 2026-10-14 follow-up findings and CI integration

| Finding | Severity | Evidence and disposition |
|---|---|---|
| G08-R11 — NiceGUI G02-B fixture mismatch | CI failure; software test | Both Windows Python 3.10/3.12 jobs in [run 38457405604](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38457405604) failed at `tests/test_web_pages_ui.py::test_read_only_routes_and_repeat_browsers` on HTTP 403. Cause was NiceGUI's default `Host: testserver`. Fixed only in that test's loopback fixture; adverse Host rejection remains tested. Final-SHA CI must establish the fix. |
| G08-R12 — audit suffix deletion | HIGH, partly mitigated | Deleting the newest audit and audit_chain rows leaves a valid internal HMAC prefix. Added `sqlite_sequence` watermark checking and `test_audit_suffix_deletion_detected_before_reopen`. A DB attacker who also rewrites the allocation watermark can still evade local-only detection. Off-device sealed audit tips remain **OPEN**. |
| G08-R13 — signed backup rollback | HIGH, OPEN | Manifest HMAC verifies authenticity, not whether an older valid snapshot is acceptable. Explicit operator-authorized recovery freshness/anti-rollback policy and external escrow remain release gates. |
| G08-R14 — Windows NTFS key protection | HIGH, OPEN | POSIX file-mode validation is not an NTFS owner/DACL audit. Independently assess the launcher/service account, effective permissions, and host key protection before LAN use. |

Merged H01 #32 and cross-platform setup #33 were integrated through commit `cd59d5e`, with no G04 hardware activation. G05 #28 and G07-A #27 remain draft/open. **This is AI-assisted self-review, not independent external human approval.** PR #29 must remain unmerged until final-head CI, independent security review, and all code-level HIGH/BLOCKER gates are resolved. Physical HIL, site LAN approval, W02 release certification and actual hardware enablement remain separately NO-GO.

### Additional HIGH data-loss/recovery defects — 2026-10-14

- **G08-R15 (HIGH; corrected in software, final CI pending):** removing the SQLite security database while leaving audit/backup keys could make startup create a brand-new empty identity store and permit an unintended first-admin bootstrap. Startup now refuses to create a new DB when persistent audit/backup keys survive; an explicit approved restore is required. Regression: `test_missing_security_db_cannot_rebootstrap_existing_authority`.
- **G08-R16 (HIGH; corrected in software, final CI pending):** deleting all HMAC chain and checkpoint rows while keeping the pre-existing audit key made the prior implementation falsely classify an established store as a legacy G08-min migration and reseal attacker-controlled rows. Initialization now refuses checkpoint-free databases when the key already exists. Regressions: `test_missing_checkpoint_and_chain_never_reseals_old_database` and the one-time legitimate G08-min migration test.
- **Residual risk:** deletion of all local data and keys or attacker control of the SQLite allocation watermark still requires externally anchored evidence, protected host ACLs and signed backup/rollback governance. These improvements do not provide independent attestation, and CI success does not authorize production LAN operation.
