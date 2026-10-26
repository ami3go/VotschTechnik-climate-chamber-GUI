# G08 security model (lab-only deployment)

This document describes the **current** security architecture. It replaces the
earlier internet-era design (TLS mode, selectable security profiles, PIN login,
HMAC audit chains, signed backup manifests and the H02 permit/watchdog stack).
Those historical reviews remain in `G08_SECURITY_REVIEW.md` and
`W02_SECURITY_REVIEW.md` for traceability and must not be used as operating
instructions.

## Threat model and boundary

The server runs on a dedicated, physically controlled machine on a closed lab
network with the chamber and one operator laptop. Physical access, OS account
security, filesystem ACLs and the chamber's own limits/emergency stop are the
primary controls. A host administrator who can rewrite the database and all
local files is outside the software's ability to prove past events.

Remote internet exposure is not supported. Plain HTTP is accepted only in
`lab` mode on a private, dedicated network; `localhost` mode is loopback-only.

## Network and transport

| Control | Behaviour |
|---|---|
| Default deployment | `CHAMBER_NETWORK_MODE=localhost`, bind `127.0.0.1`, no LAN access. |
| Lab deployment | `CHAMBER_NETWORK_MODE=lab`, explicit bind address or public origin, plain HTTP, private client CIDRs only. |
| TLS | Not supported. `CHAMBER_TLS_CERT`, `CHAMBER_TLS_KEY` and TLS origins are startup errors. |
| Host validation | Every HTTP/WS request requires an allowlisted canonical `Host`; mutations and WebSockets require a matching `Origin`. `X-Forwarded-For` is never trusted. |
| Cookies | Session cookie is signed, `HttpOnly`, `SameSite=Lax`, `Secure` false, max age 8 hours. |
| Proxies | No reverse-proxy or TLS-termination mode is supported. |

Plain HTTP exposes credentials and session cookies to anyone who can observe
the lab network. Use a switched, dedicated VLAN or point-to-point connection.

## Identity and sessions

- Local accounts only: `ADMIN`, `OPERATOR`, `VIEWER`.
- Passwords are stored with scrypt (`N=32768`, `r=8`, `p=1`) and a random salt.
- One password policy for every deployment: 12–128 UTF-8 bytes. There are no
  selectable profiles, PINs or recovery tokens.
- Login lockout: 5 failures per account / 900 s; 30 failures per client / 900 s.
  Expensive password hashing runs outside SQLite write transactions.
- Sessions are server-side, rotated on login, bound to CSRF tokens, revocable on
  password/role/account changes, and expire after 30 minutes idle or 8 hours
  absolute. A backwards clock jump is treated as expiry.
- First bootstrap is host-console only. Factory `admin` / `admin` is flagged as
  a warning, not a network gate. `--reset-credentials` restores factory values
  from the host console only, revokes all sessions and preserves other users.

## Authorization and chamber safety

- Every browser mutation re-authenticates the session and CSRF token at the
  service boundary; browser-supplied roles or operator names are never trusted.
- One controller owns the chamber through a generation-fenced lease. STOP is
  verified by independent readback; manual/profile ownership cannot overlap.
- Profile execution in physical mode requires isolated lab mode, a verified
  `GOOD`/`STOPPED` chamber, a healthy run journal and all G06 runtime checks.
  There is no administrator ownership override.
- Run journal records are immutable and hash-manifested for run artifacts.

## Audit

- The `audit` table is append-only in normal operation. Rows are never pruned
  automatically and have no HMAC chain or startup integrity gate.
- Free-form details redact password/token/CSRF/secret-like values.
- `SecurityStore.export_audit()` and
  `ClimateChamberServer.exe --export-audit PATH.csv` write a non-overwriting CSV
  snapshot plus `PATH.csv.sha256`.
- Schedule the export daily to isolated media. The CSV/hash pair is evidence,
  not an anti-tamper chain; a host administrator can modify the live database.
  Off-device retention and access control remain the compensating control.

## Backups

- `--backup-security` takes an online SQLite snapshot, runs
  `PRAGMA integrity_check`, checks the schema and writes a plain JSON manifest
  containing size, schema, creation time and SHA-256. No signing key is used.
- `--verify-security` rechecks the manifest, size and SHA-256.
- `--stage-restore-security` only restores into a new empty directory, revokes
  all restored sessions and refuses in-place overwrites.
- Protect backup files with OS ACLs. A SHA-256 manifest detects accidental
  corruption; it does not authenticate the backup against a malicious host.

## Updates and supply chain

- One release verifier is maintained:
  `scripts/w02_target_verifier.py` (frozen as
  `ClimateChamberReleaseVerifier.exe`) with the PowerShell hash-checking wrapper
  `scripts/verify_w02_release.ps1`.
- Signed W02 bundles bind every file to an Ed25519 publisher key supplied
  out-of-band, an externally pinned minimum version and a complete inventory.
- The G08 PowerShell verifier was removed to avoid a second divergent verifier.
- SBOM and third-party license output are **advisory**. The build emits them for
  review, but they are not a release gate. The signed inventory and signature
  remain the integrity gate.

## Archived components

The H02 signed-permit, witness, independent-watchdog and pinned-revision stack
is archived under `archive/h02/` and is not imported by the runtime. Legacy
`CHAMBER_H02_*` settings have no effect. Historical H02 evidence is not current
operating approval.

## Residual risks

- No TLS; plain HTTP is acceptable only on the closed lab network.
- A host administrator can rewrite the audit database and backups.
- No external/WORM audit anchor, no anti-rollback backup authorization and no
  independent penetration test.
- Physical chamber safety ultimately depends on the chamber's own limits,
  over-temperature protection and emergency stop.
- No certified release artifact, Authenticode publisher signature or clean-VM
  acceptance is implied by this document.
