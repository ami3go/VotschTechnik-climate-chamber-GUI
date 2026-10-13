# G08 focused security and architecture review

Review scope: code in `feat/g08-full-security` stacked above
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

**Merge decision: BLOCKED.** G08-min PR #25 is open. This branch's PR #29
is deliberately stacked/draft and must not be merged to main until prerequisite
merge, a reviewed rebase, clean final-source CI and all code-level BLOCKER/HIGH
issues are fixed. Final operational LAN/physical release is independently
NO-GO even after software CI.
