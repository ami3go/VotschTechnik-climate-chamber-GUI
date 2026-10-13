# G08 — Full security architecture, threat model and operations

**Status (2026-10-13): CANDIDATE / stacked on [G08-min PR #25](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/25). Not merged or approved for production LAN or physical hardware.**

Full G08 **extends** the existing `SecurityStore`, NiceGUI sign-in and
`AuthorizedChamber`; there is no replacement authentication mechanism.
This branch starts at G08-min PR #25 HEAD, not at current main. Its PR MUST
remain stacked/draft until #25 is independently reviewed, merged and rebased.
Neither a green simulated CI nor a signed package releases hardware.

## Trust boundaries and threat model

| Boundary | Attack / fault | Implemented defense | Residual risk |
|---|---|---|---|
| Browser ↔ NiceGUI | Forged Host, DNS rebinding, CSRF, cross-site WebSocket | All HTTP GET/POST/WS requests require exact allowlisted Host; mutation/WS require same-origin; duplicate security headers and foreign Fetch Metadata denied. App callbacks revalidate SQLite session and CSRF. | Socket.IO authentication occurs in event guard, not at a standalone cryptographic handshake. Review NiceGUI transport/session cookies with browser tests. |
| LAN ↔ host | Unintended listener, plaintext, unauthorized subnets | Default 127.0.0.1 only; explicit `lan` mode needs TLS cert/key, valid date/hostname, fixed HTTPS origin, allowlisted peer CIDRs and HTTPS-only session cookie. No X-Forwarded-For trust. | No mTLS and no site firewall enforcement; OS ACL/firewall, CA trust and a dedicated penetration test are still required. |
| Authentication | Guessed/replayed/stolen credentials, account lockout DoS | Salted scrypt, configurable minimum, transactionally revalidated role and sessions, per-account lockout and peer-aware attempt throttling; logout/rotation/revocation. | Pre-auth browser session fixation, live open WS after revocation, brute-force concurrency and client-IP spoofing behind a proxy need external verification; reverse proxy deployment is not approved. |
| Operator → G04 | Viewer or stale owner tries write; STOP blocked by foreign operator | Server-only `AuthorizedChamber`, audited INTENT before device method dispatch, role and token ownership guards; STOP requires auth/STOP permission but NOT owner token. | An already-running authorized command cannot be undone by a later role revocation; STOP readback requires HIL. |
| Security database | Crash, corruption, forged log, uncontrolled growth | SQLite synchronous=FULL, local private files, versioned schema, HMAC audit chain, bounded retained rows, online snapshot with HMAC manifest and integrity check. | Host admin possessing HMAC key can rewrite evidence; tail truncation is not independently attested. External signed archive/remote WORM storage required for production audit assurances. |
| Host / update package | Impersonated installer, malicious dependencies, logoff/reboot | W01 signed-hash manifest feasibility and single-user kernel lock; no automatic updater; simulated server only. | W02 signed artifact chain, ACL inspection, package attestations, Win10/11 clean-VM and service supervision needed. |

**Asset classification:** administrator password hash, session digests, CSRF
digests, audit signing key, backup signing key, signed-cookie secret, operator
evidence and user credentials are sensitive. Never expose security DB, signing
keys, recovery tokens or logs via a web-download endpoint. Driver protocols
and physical STOP circuitry remain outside this software trust model.

## Secure deployment modes

### Localhost (default / W01 frozen simulator)

`CHAMBER_NETWORK_MODE=localhost` (default), `CHAMBER_BIND_HOST=127.0.0.1`,
`CHAMBER_PORT=8080` (or explicit port). Exact allowed browser origins are
`http://127.0.0.1:PORT` and `http://localhost:PORT`. Binding to
`0.0.0.0`, a LAN IP, providing a LAN origin or LAN certificates while in
localhost mode **fails startup**; allowed-origin overrides can only restrict
the loopback defaults. Loopback requests still require valid authentication
for protected resources and mutations; no anonymous localhost controller
exception is allowed. W01 frozen launcher unconditionally refuses LAN mode.
Web STOP is NOT an emergency stop.

### LAN (code path for controlled evaluation only — NO-GO)

Set these variables explicitly, for example in a protected service
configuration (substitute your real host/certificate and narrower client CIDR):

```powershell
$env:CHAMBER_NETWORK_MODE = "lan"
$env:CHAMBER_BIND_HOST = "192.168.1.50"
$env:CHAMBER_PORT = "8443"
$env:CHAMBER_PUBLIC_ORIGIN = "https://chamber.example.internal:8443"
$env:CHAMBER_ALLOWED_CLIENT_CIDRS = "192.168.1.20/32,192.168.1.21/32"
$env:CHAMBER_TLS_CERT = "C:\ProgramData\ClimateChamber\cert.pem"
$env:CHAMBER_TLS_KEY = "C:\ProgramData\ClimateChamber\key.pem"
```

Only private IPs, or an explicit wildcard bind with a nontrivial peer
allowlist, are accepted. Client IPs come from the transport socket, not
HTTP proxy headers. The certificate must match the HTTPS hostname, be
currently valid, and load with its key; clients must independently trust its
issuing authority. Cookie `Secure` is enabled with `SameSite=strict`,
no-store, nosniff, X-Frame-Options, frame-ancestors and HSTS response
headers. Do not expose this service to the internet or use a TLS-terminating
proxy without new trust/proxy/Origin review.

**LAN is not ready for operational use:** site-owned certificate distribution
and revocation, controlled firewall/client ACL, Windows TLS-key NTFS ACL,
trusted-client browser tests, HTTPS/WSS session tests, security review and
operator approval remain outstanding. Physical hardware still cannot connect.

## Identity and offline recovery

First administrator: `python -m chamber_web.security.bootstrap` or
`ClimateChamberServer.exe --bootstrap-admin` in an interactive **local
terminal**. No default password, no HTTP bootstrap. All roles remain
ADMIN/OPERATOR/VIEWER and all sensitive controller mutations pass the
existing G08-min guards.

While signed in as an administrator, issue an offline one-use recovery
credential via `python -m chamber_web.security.bootstrap
--issue-recovery-token` or the equivalent frozen EXE switch.
It prompts for the current administrator password. Store the printed token
**in separate physical escrow**; only a salted-independent SHA-256 digest
of a cryptographically random high-entropy token is in SQLite. Reissuing
invalidates prior tokens. Default expiry is 30 days (API max 365 days).
Consume using `--recover-admin` at a trusted local terminal; this resets
the named **enabled ADMIN** only, consumes every outstanding recovery token,
revokes all its active sessions, clears that user's lockout and audits the
action. A disabled/non-admin account cannot be elevated by a token. The CLI
refuses redirected stdin and redacts failures. Do not add an HTTP recovery
handler.

The shared `SecurityStore` exposes `change_password`,
`revoke_sessions`, `issue_recovery_token` and
`recover_admin_offline` alongside G08-min `create_user`, `change_role`
and `disable_user`. Password changes and role changes revoke all sessions,
including old concurrent browser sessions. Browser event callbacks MUST
check current permission and CSRF on each call. Logged-out or revoked
tokens cannot be replayed; client UI should reload on revocation.

`SecurityStore` policy defaults: 12–1024 UTF-8 password bytes; 5 failures
and 15-minute lockout; 30-minute idle/8-hour absolute session lifetime.
Constructor overrides allow stronger minimums, fewer permitted failures,
custom lockout intervals and per-IP throttling. Client identity must come
from the socket peer; never from arbitrary HTTP client headers. Configuration
must be reviewed and validated before startup.

## Database backup, upgrade and rollback

Keep `CHAMBER_SECURITY_DIR` in a local ACL-protected user/service-owned
directory, never the repository or shared network folder. Create backups
on local protected media through the server executable:

```powershell
.\server\ClimateChamberServer.exe --backup-security C:\SecuredBackup\security.sqlite3
.\server\ClimateChamberServer.exe --verify-security C:\SecuredBackup\security.sqlite3
```

Backup is a SQLite online snapshot plus an HMAC-signed sibling
`security.sqlite3.manifest.json` (digest, size, schema and timestamp).
A separately stored 256-bit `backup_signing_key` authenticates it.
**Escrow `backup_signing_key` and `audit_hmac_key` separately from the
DB snapshot**, with restricted OS permissions. Missing keys mean recovery
cannot be authenticated; never generate replacements to legitimize an old
backup. Verify on an isolated host before relying on a backup.

With the service stopped, stage a verified backup in a **new empty** directory:

```powershell
.\server\ClimateChamberServer.exe --stage-restore-security C:\SecuredBackup\security.sqlite3 --restore-directory C:\ClimateChamber-Recovery
```

All restored sessions are revoked and recovery tokens destroyed. The
source audit key is carried into the staged directory (requires separately
escrowed source key). Never overwrite the live DB or switch
`CHAMBER_SECURITY_DIR` while a server process runs. First test with a
single mock-only process and perform audited sign-in/re-enrollment; revalidate
all NiceGUI cookie keys. A schema `PRAGMA user_version` change from legacy
0 to 1 is accepted; unknown future schema versions refuse startup. Rollback
is an **offline restore to a new data root**, not an in-place downgrade.
Restore from a trusted independently verified snapshot and preserve the
original root for forensic investigation.

Audit is an HMAC-linked retained prefix-truncatable ledger (100–1,000,000
row configuration, default 10,000). Historical G08-min events are sealed
once on migration. Missing audit key, missing/reordered/modified evidence
blocks startup. `verify_audit_integrity()` checks retained rows explicitly.
Retention truncation and cryptographic key escrow still require a site policy,
separate append-only exports and Windows NTFS ACL verification.

## Controlled Windows lifecycle and offline supply chain

W01 portable process is **not a Windows Service**. Its process lock prevents
a duplicate owner, and its browser closure does not stop the server, but
Windows logoff/reboot/power loss *does*. Restart must NEVER assume the
previous chamber is stopped or resume a profile. G04/G06/G07 must reconcile
any real run as UNKNOWN until fresh verified status and authorized STOP
reconciliation. Host shutdown, disk-full and network loss policy still
requires **signed P00 site decisions** and HIL fault injection. W02 must
implement supervised process startup/shutdown, secure OS account, independent
readiness, service recovery conditions and durable run reconciliation.

W01 `windows_manifest.py` verifies a **content hash** for extracted files,
not authenticated software publisher identity. Do not treat the bundle's
co-distributed SHA256SUMS or a successful extraction as sufficient to trust an
offline update. Production updates require an out-of-band approved hash and
verified signed publisher/Authenticode or equivalent signed release manifest;
inventory/pin the full transitive wheel closure, scan vulnerabilities,
test rollback on disconnected Win10/11 x64, preserve data directory and
reject unsigned/mismatched builds. **Automatic updates are prohibited.**

## Security test gates

Run `python -m unittest discover -s tests -p "test_security_*.py" -v`,
Windows 3.10/3.12 NiceGUI CI and the W01 Windows frozen packaging workflow on
the **final PR head**. Adversarial suites cover credential misuse/expiry,
replay/CSRF, role/session revocation, login lockouts, invalid TLS, Host/
Origin/WebSocket requests, audit tampering, backup migration/restore.
The Windows clean-disconnected-VM, interactive actual browser LAN attack
matrix and site-signed HIL are **separate release blockers**.

### Merge/release decision

Do NOT merge G08 before PR #25 is merged and reviewed. Review G08's exact
final diff including the security-critical credential/audit/middleware code;
fix all BLOCKER/HIGH findings, require green Windows CI and packaging CI at
the final SHA, then retarget G08 onto main. No hardware integration or
real Vötsch operations are enabled by this PR. Operational LAN signoff
requires an independent security reviewer, site admin/owner and W02;
physical HIL requires signed P00 + G05/G06/G07/H01 gates.
