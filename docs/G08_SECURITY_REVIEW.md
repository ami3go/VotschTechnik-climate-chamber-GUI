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

**Merge decision (2026-10-13): BLOCKED. Closure (2026-10-18):** [PR #29](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/29) merged 2026-10-15 as `2fdd143cb743fe52b30223f65ce7fe88cb4ff5e7` after green PR-head CI. G08-min PR #25 is merged. The independent verification of the reviewed final diff and all code-level BLOCKER/HIGH fixes was **NOT** obtained and remains OPEN; final operational LAN/physical release is independently NO-GO even after software CI.

## 2026-10-13 final-head re-review checkpoint

- Head before CI correction: `e8b54c0f3d0f1b8cfd132750615bbd8852cedb61`. On GitHub Actions run [38452378497](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38452378497), the Python 3.10 job failed and Python 3.12 job ended cancelled; **both** job logs show two failed G03-C NiceGUI UI tests at `User.open('/profiles')` or `User.open('/login')` with HTTP 403. The previous security tests and profile service tests passed.
- Root cause: G08 full Host validation permits loopback `127.0.0.1:8080` / `localhost:8080`, whereas NiceGUI's in-process `User` fixture defaults to the `testserver` authority. The middleware correctly rejects that untrusted hostname. Tests now configure the fixture's HTTP client to use the loopback authority rather than weakening Host validation. A negative ASGI test explicitly requires `testserver` to remain rejected in production middleware.
- Corrective commits: `bac2bde65c7bc78260440426a944eaad44a05217`, `286ef01ba32c7396b0b04f1bf3b8995d5d018ffd`, `d8968d6dd07ec60aef69ac8937749fed4cb7f055`. Final-head CI must be rerun and **completed**; in-flight or older-head workflows are not passing evidence.
- **Still OPEN HIGH:** audit tail-truncation not anchored outside SQLite; historical G08-min audit authenticity cannot be established retroactively; signed backup replay/rollback policy missing; Windows DACL/owner enforcement not implemented. These are material security issues, not documentation-only closure. Independent review was still absent after the 2026-10-15 software merge and remains **OPEN**.
- Independent human/security approval is still absent. `main` merge and LAN/physical deployment are NOT authorized.

## 2026-10-14 follow-up findings and CI integration

| Finding | Severity | Evidence and disposition |
|---|---|---|
| G08-R11 — NiceGUI G02-B fixture mismatch | CI failure; software test | Both Windows Python 3.10/3.12 jobs in [run 38457405604](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38457405604) failed at `tests/test_web_pages_ui.py::test_read_only_routes_and_repeat_browsers` on HTTP 403. Cause was NiceGUI's default `Host: testserver`. Fixed only in that test's loopback fixture; adverse Host rejection remains tested. Final-SHA CI must establish the fix. |
| G08-R12 — audit suffix deletion | HIGH, partly mitigated | Deleting the newest audit and audit_chain rows leaves a valid internal HMAC prefix. Added `sqlite_sequence` watermark checking and `test_audit_suffix_deletion_detected_before_reopen`. A DB attacker who also rewrites the allocation watermark can still evade local-only detection. Off-device sealed audit tips remain **OPEN**. |
| G08-R13 — signed backup rollback | HIGH, OPEN | Manifest HMAC verifies authenticity, not whether an older valid snapshot is acceptable. Explicit operator-authorized recovery freshness/anti-rollback policy and external escrow remain release gates. |
| G08-R14 — Windows NTFS key protection | HIGH, OPEN | POSIX file-mode validation is not an NTFS owner/DACL audit. Independently assess the launcher/service account, effective permissions, and host key protection before LAN use. |

Merged H01 #32 and cross-platform setup #33 were integrated through commit `cd59d5e`, with no G04 hardware activation. **Closure (2026-10-18): G05 #28, G07-A #27 and G08 #29 merged 2026-10-15 after green final-head CI; the independent security review and all code-level HIGH/BLOCKER release gates below remain OPEN.** **This is AI-assisted self-review, not independent external human approval.** Physical HIL, site LAN approval, W02 release certification and actual hardware enablement remain separately NO-GO.

### Additional HIGH data-loss/recovery defects — 2026-10-14

- **G08-R15 (HIGH; corrected in software, final CI pending):** removing the SQLite security database while leaving audit/backup keys could make startup create a brand-new empty identity store and permit an unintended first-admin bootstrap. Startup now refuses to create a new DB when persistent audit/backup keys survive; an explicit approved restore is required. Regression: `test_missing_security_db_cannot_rebootstrap_existing_authority`.
- **G08-R16 (HIGH; corrected in software, final CI pending):** deleting all HMAC chain and checkpoint rows while keeping the pre-existing audit key made the prior implementation falsely classify an established store as a legacy G08-min migration and reseal attacker-controlled rows. Initialization now refuses checkpoint-free databases when the key already exists. Regressions: `test_missing_checkpoint_and_chain_never_reseals_old_database` and the one-time legitimate G08-min migration test.
- **Residual risk:** deletion of all local data and keys or attacker control of the SQLite allocation watermark still requires externally anchored evidence, protected host ACLs and signed backup/rollback governance. These improvements do not provide independent attestation, and CI success does not authorize production LAN operation.

### 2026-10-14 concurrent first-start regression (HIGH availability, corrected code awaiting final CI)

Windows Python 3.12 [NiceGUI run 38618249624](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38618249624) identified a real two-starter race in the new tamper protection: one startup creates the audit signing key while another reads it before the first checkpoint commits and rejects it as missing. The key creation and HMAC checkpoint setup are now serialized with the same SQLite `BEGIN IMMEDIATE` write transaction. New `test_parallel_first_security_store_initialization` exercises six concurrent initializers, and the existing `test_concurrent_initial_bootstrap_single_winner` must remain green. No guard is disabled. Final-head Windows CI must verify the fix.

## 2026-11-21 CH-WP-09 fresh code-level audit and risk ledger

This checkpoint reviews the current `main` G08 implementation plus the focused
cookie-key hardening in PR #105. It is a software self-review, not an
independent assessment, LAN approval, Windows deployment qualification,
publisher approval, or physical HIL result. Line references are to the PR #105
head after synchronization with `main`; the final commit and exact-head CI are
recorded in the PR and issue evidence.

| ID / severity | File:line and failure mechanism | Code disposition and regression artifact | Owner / dependency / remaining verification |
|---|---|---|---|
| G08-R17 — persisted NiceGUI cookie key path substitution; **HIGH** | `chamber_web/security/nicegui.py:48-100`: the former path check followed by `Path.read_text()` allowed a final-component symlink swap and accepted nonregular or foreign-owned POSIX entries. | PR #105 uses `O_NOFOLLOW` and same-descriptor `fstat`/read on POSIX, rejects symlink/nonregular/foreign-owner/unsafe-mode state, and bounds the read. `tests/test_nicegui_cookie_secret.py:24-92` covers persistence, symlink, directory, oversize, FIFO, descriptor read, mode, and owner failures. | **Software fixed; exact-head Windows/Linux CI required.** Windows reparse points and NTFS ownership/DACLs are R14/R19 below, not implied by this POSIX fix. |
| G08-R18 — session fixation, stale socket/callback authority, and CSRF replay; **HIGH** | `chamber_web/security/nicegui.py:112-136,170-196,215-227` obtains tokens only from server-side user storage, clears storage on login/logout, issues fresh session/CSRF pairs, and reauthenticates every mutation callback. `chamber_web/security/auth.py:679-729,737-755,801-847` rejects revoked/expired sessions and revokes on logout, role change, or disable. | Storage-level fixation/replay is covered by `tests/test_security_full.py:80-97,116-136`; post-render logout denial by `tests/test_web_pages_ui.py:96-101`; concurrent role/session checks by `tests/test_security_core.py:130-216`. | **Code path covered. External gate remains:** real LAN browser cookie-ID rotation, Secure/HttpOnly/SameSite inspection, already-open WebSocket behavior, and cross-tab invalidation under the packaged server. Security reviewer + W02 clean Windows target. |
| G08-R3 — Host/Origin/CSRF/WebSocket bypass; **HIGH** | `chamber_web/security/http.py:46-126` rejects duplicate security headers, untrusted Host/peer, cross-site requests, and non-allowlisted origins for mutations/WS; `http.py:129-140` and `nicegui.py:215-227` still require live session, CSRF, and permission. `chamber_web/security/deployment.py:95-178` defaults to loopback and requires explicit LAN TLS/client ACL configuration. | `tests/test_security_full.py:314-409` covers loopback defaults, invalid LAN TLS, rebinding/peer rejection, forged test host, WS origin, and headers. `tests/test_security_core.py:295-372` covers exact Origin/Host, WS, forged POST, and explicit endpoint CSRF. | **Software controls and negative tests present.** Actual site DNS/proxy/firewall/PKI, certificate rotation, HTTPS/WSS browser tests, and approved CIDRs remain site/security gates. |
| G08-R5/R12/R15/R16 — audit/database deletion or alteration; **HIGH** | `chamber_web/security/audit_integrity.py:130-165` verifies sequence/HMAC/checkpoint and detects simple tail truncation with the allocation watermark; `chamber_web/security/auth.py:145-180` refuses a missing database when authority keys survive. A database attacker who can also rewrite the local watermark or delete all local authority material is outside the local proof boundary. | `tests/test_security_full.py:203-311` covers row tamper, suffix deletion, missing DB, migration, concurrent initialization, missing chain, retention, invalid DB, and missing key. Sensitive audit detail redaction is asserted at `tests/test_security_full.py:203-217`. | **Local code mitigations present; external blocker documented.** Security/site owner must provide protected ACLs, independent key escrow, and an off-device monotonic/sealed audit tip if that threat is in scope. |
| G08-R6/R13 — authentic but stale signed backup rollback; **HIGH** | `chamber_web/security/backup.py:119-194` verifies HMAC/hash/schema, stages only into an empty root, revokes sessions, deletes recovery tokens, and preserves the independent audit key. It intentionally has no trusted monotonic source that can decide whether an older valid backup is authorized. | Tamper/corruption/session-revocation paths are covered by `tests/test_security_full.py:183-201,302-311`. | **Explicit external/policy blocker:** operator-approved recovery freshness/rollback policy, escrow inventory, trusted timestamp or monotonic record, and disconnected Windows restore drill. Software must not invent this authority. |
| G08-R14/R19 — Windows key ACL, reparse, and service identity; **BLOCKER for LAN deployment** | `chamber_web/security/nicegui.py:71-91`, `backup.py:28-50`, and `deployment.py:152-176` do not establish effective NTFS owner/DACL or an atomic Windows reparse-point guarantee. POSIX mode/UID checks do not apply on Windows. | No weakening or simulated approval. PR #105's Windows tests may prove normal/fail-closed file behavior, not host ACL certification. | **External Windows/site blocker:** named service account, protected data root, effective DACL inheritance/owner inspection, reparse test on the installed filesystem, firewall/PKI review, logoff/reboot/power-loss lifecycle. |
| G08-R9 — publisher/signing trust; **HIGH release gate** | Offline verification accepts only a separately trusted digest/publisher policy, but this repository cannot create or approve the production publisher identity. | W02 software closure and negative-path CI are tracked under CH-WP-08. | **External signing/release blocker:** publisher key ceremony, attested provenance, independent SBOM/license review, trusted verifier provisioning, and R01 decision. |

The audit found no second GUI-side device protocol or alternate browser-to-device
command path. G08 authorization remains above the existing `VotschBackend`/G04
services. Physical HIL admission is a separate boundary and was neither used nor
tested here. Closing the CH-WP-09 software issue therefore records the reviewed
code and exact-head software evidence only; the owners and external gates in the
last column remain open and release status remains NO-GO.
