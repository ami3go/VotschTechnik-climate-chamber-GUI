> **HISTORICAL SECURITY BASELINE — SUPERSEDED (2026-10-26).** This document describes the former PIN/security-profile/TLS design. Use `G08_FULL_SECURITY.md` for the current lab-only model.

# G08-min — offline authentication and authorization (mock-only)

Status: **G08-min simulation-only software merged via PR #25** (`61d8aefaadcdb6f5035b6683410bee0abf76e9d1`; exact-head Windows NiceGUI/security run [38438666305](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38438666305), W01 [38438666518](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38438666518)); full G08 and live physical certification remain OPEN.
No hardware I/O release is authorized by this document. References:
[P00](P00_DECISION_CONTRACTS.md), [G04-A](G04_A_CONTROLLER_CONTRACT.md),
[abstraction contract](CHAMBER_ABSTRACTION_CONTRACT.md) and
[delivery sequence](DEVELOPMENT_SEQUENCE.md).

## Local setup / secure first administrator

**Factory setup update (2026-10-16):** New NiceGUI deployments provision `admin` / `admin` and default PIN `12345678` on first startup if no administrator exists. These deliberately weak values are for localhost commissioning only; change the password and PIN via Admin before LAN operation. As of 2026-10-19, incomplete credential rotation yields a warning rather than denying chamber settings saves, server startup or profile selection; the normal identity, TLS, ACL, and hardware-safety checks still apply. Existing accounts are preserved, and the strong-password policy still applies to subsequent changes. See [Factory Credentials](FACTORY_CREDENTIALS.md). The CLI procedure below remains an optional way to provision a strong administrator before starting the GUI.


Run the GUI only as a single local process, bound to `127.0.0.1`, with a
dedicated operating-system account. BEFORE using the browser run in a local
interactive terminal (not via HTTP or an unattended launch script):

```bash
python -m chamber_web.security.bootstrap
python main.py
```

In the frozen W01 Windows ZIP (no Python installed), provision via an
interactive PowerShell console:

```powershell
.\\server\\ClimateChamberServer.exe --bootstrap-admin
```

The CLI prompts for a **chosen** administrator username, a password of at least
12 UTF-8 bytes, and confirmation (hidden input). The manual CLI does not use the factory password,
no initial bearer token in a file, no web/bootstrap endpoint and no automated
password reset. Provisioning is an atomic SQLite transaction, permitted **once**
per data directory. Concurrent bootstrap is rejected for the losing process.
NiceGUI server-side per-browser session storage is redirected to\n\`~/.chamber_web/security/nicegui_storage\` (never cwd/.nicegui).\nKeep local recovery/backup procedures outside the web GUI; do not publish
database or signing-key files.

By default sensitive state is stored under
`~/.chamber_web/security/security.sqlite3`, and a randomly generated 256-bit
NiceGUI cookie signing secret under
`~/.chamber_web/security/nicegui_cookie_secret`. On POSIX the directory and key
are owner-only. Windows requires OS/NTFS ACL verification at deployment.
Override `CHAMBER_SECURITY_DIR` for tests or a dedicated protected local data
volume. Do **not** store this directory in the repository or a network share.
Back it up with host OS access controls; deleting/recreating it is **not** an
approved password-recovery method.

Passwords use per-user 128-bit salts and scrypt (N=32768, r=8, p=1, dklen=32);
plaintext is neither stored nor included in audit. Rate-limited username login
failures lock out after five unsuccessful attempts for 15 minutes (no claim of
production-grade distributed/IP rate limiting).

## Session / transport contract

Successful login creates two unrelated 256-bit random opaque tokens: the
session ID and CSRF token. Only SHA-256 digests are stored in SQLite. Tokens
are kept **server-side** in NiceGUI per-browser persistent user storage, bound
to a signed HttpOnly browser session cookie. Each protected call revalidates
the session against SQLite and the current DB role/enabled flag. Logout revokes
the token in SQLite, clears NiceGUI storage and navigates to /login. Role changes
and account disable revoke all affected sessions immediately.

Idle expiry defaults to **30 minutes**, absolute expiry to **8 hours** from login. Passive NiceGUI dashboard/page timer reads do **not** refresh idle activity.
Only explicit navigation/interactions or mutating service calls renew last activity.
Live callbacks recheck the session and redirect to sign-in on revocation/expiry.
Expiry survives page refresh and application restarts if both SQLite and the
cookie signing secret are retained. Session continuity across restart must be
smoke-tested in the packaged Windows build; NiceGUI storage is not a multi-host
session backend. G08-min assumes one trusted process and a local filesystem.

Browser callback model:
1. NiceGUI page requires `require_authenticated_page()` before rendering
   nonpublic data. Public `/login` contains **no** privileged controls.
2. All future control, profile, settings and user-management callbacks MUST
   revalidate tokens and permissions **when invoked**, not merely on page load.
   Call `AuthorizedChamber.execute(session, csrf, chamber_id, command, ...)`
   for controller operations or `require_browser_permission(permission)` for
   other service mutations. The UI must never receive raw `ChamberManager`,
   access a vendor adapter, or use G04's server-trusted token-free bypass.
3. No public REST mutation endpoint exists in this scope. The ASGI
   `OriginMiddleware` blocks **all unknown HTTP mutations** by default. NiceGUI
   internal Socket.IO transport POSTs require an allowlisted exact Origin and
   matching Host, with cross-site Fetch Metadata denied; WebSocket handshakes
   also require this and reject missing/null/foreign Origin. The internal
   NiceGUI event transport is not a standalone authenticated REST API.
4. Future explicitly reviewed custom HTTP endpoints must extend the ASGI
   route allowlist AND call `authorize_http_mutation(request, security,
   session, permission)` (X-CSRF-Token checked against the session's stored
   digest). Their handlers must audit intent/results. They must NEVER treat
   an Origin header by itself as authentication.

Default origins are `http://127.0.0.1:8080` and
`http://localhost:8080` (or `CHAMBER_PORT`). Use
`CHAMBER_ALLOWED_ORIGINS` as an explicit comma-separated list of full
origins for a controlled development/test proxy. LAN / non-loopback hosting,
TLS reverse-proxy trust, secure-cookie deployment and internet exposure
**remain blocked** pending full G08 and a separate security assessment.
Never enable physical hardware based only on this setting.

## Server-side permission matrix (contract version 1)

| Permission / action | ADMIN | OPERATOR | VIEWER |
|---|---|---|---|
| Read dashboard / profiles / history | Yes | Yes | Yes |
| START, set temperature, claim/release G04 operator lease | Yes | Yes | No |
| STOP irrespective of another operator's lease | Yes | Yes | No |
| Reconcile STOP / clear uncertainty latch | Yes | No | No |
| Edit/save/import profiles (G03-C future integration) | Yes | Yes | No |
| Start/pause/abort profile run (G06-A future integration) | Yes | Yes | No |
| Settings, connect/disconnect backend | Yes | No | No |
| Read security audit and manage accounts | Yes | No | No |

Stable API: `SecurityStore.bootstrap_admin` (CLI only), `login`,
`authenticate(session, csrf=..., mutation=True)`, `logout`,
`create_user`, `change_role`, `disable_user`, `audit`.
`Role`, `Actor`, `SessionTokens`, `Permission`, `require_permission`,
`AuthorizedChamber.authorize`, `AuthorizedChamber.execute`,
`AuthorizedChamber.stop`, `require_browser_permission` and
`authorize_http_mutation` are the integration surface.

**Integration for G02-B:** obtain opaque tokens from `active_tokens()` only in
server-side callbacks; use guarded facade for permitted control buttons;
use `current_actor()` only for presentation, not as authorization.
**G03-C (PR #26 merged):** the persistent Profiles page guards every browser
profile read/create/modify/delete/import/save/export via G08 READ/PROFILE_EDIT
and rechecks after asynchronous uploads; core SQLite service remains server-owned.
The browser cannot access G04 or the vendor driver. **G06-A:** guard run start/abort and all runner-control
commands with PROFILE_RUN; use separate STOP permission for direct STOP.
Other future sensitive services must be enumerated here before deployment.
Controller mutations are all dispatched through `AuthorizedChamber`;
its `INTENT` audit commits before device dispatch and records `SUCCESS`
or `FAILED` afterward. Denied calls record `DENIED`. Audit failure
before dispatch must block the operation. The facade binds claimed operator tokens to the authenticated user ID,\nrejects another user's token and rejects token-free browser START/setpoint\nwrites. G02-B must use one shared process-owned facade instance.\nThe owner token is NOT an\nauthentication secret; STOP never needs it but always needs active
ADMIN/OPERATOR authorization.

## Verification and outstanding risks

Run `python -m unittest discover -s tests -p "test_security_*.py" -v`,
`python -m pytest -q tests/test_web_ui.py`, and the Windows 3.10/3.12
`web-gui-demo.yml` CI, plus Windows packaging CI. Tests cover initial
bootstrap races, per-account lockout, privilege escalation, forged origins,
WebSocket and HTTP write attempts, CSRF, concurrency, expiry, logout,
restart/readback, auditable STOP bypassing a foreign lease and FakeBackend.

Residual security gaps (full G08, **NOT** complete here): documented
disconnected-host TLS/secure-cookie setup, reverse proxy/header hardening,
backup/restore + offline credential recovery, IP/network rate limits and
lockout DoS defense, hardened account administration UI, audit retention /
integrity protection and archive signing, log rotation/monitoring, operating
system ACLs and Windows packaged-data migration, supply-chain hash lock
and vulnerability review, session/socket forced disconnect on revocation,
complete integration across future G05/G06-A/G07 operational control endpoints, CSRF
regression against actual deployed browser/network topologies, external
penetration testing and site-approved operational lifecycle/shutdown.
NiceGUI per-browser storage may retain revoked opaque IDs until cleared;
the DB is authoritative for all protected operations. Audit logging is
durable SQLite (FULL synchronous), **not tamper-proof** against a compromised
host administrator. SQLite availability/storage failure can block controls
but must not be mistaken for verified physical STOP.

**Physical gate remains OFF.** G04 remains mock-only, and G05/H01 cannot
activate real-device commands without signed site P00 limits, firmware/identity
and STOP/fault response decisions, fixed-bounds maintained driver + real HIL
readback tests, controller safety review, deployment security signoff and
the complete relevant integration checks. Web STOP is not a certified
emergency stop. Full G08 and W02 are additional gates for general LAN release.
