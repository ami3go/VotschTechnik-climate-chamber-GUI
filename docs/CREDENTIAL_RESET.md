# Offline administrator credential reset

The administrator password and PIN can be reset **locally** using the
existing authenticated recovery authority. No browser, internet connection,
cloud service or chamber driver is involved.

## Before proceeding

- Use a **trusted local interactive console** on the installed server host,
  under the OS account/service identity that owns the security database.
- On a live site, first bring the chamber to a verified safe state using
  approved on-site procedures. Credential reset is **not** a hardware STOP and
  does not terminate active hardware work.
- Identify the correct security directory, default
  `~/.chamber_web/security` on Windows and Linux, overridden by
  `CHAMBER_SECURITY_DIR`. Never point it at a backup or another deployment.
- Have **either** the current administrator **primary password** (works at
  the local console even in Isolated LAN/PIN mode) **or** a previously issued,
  unexpired, one-time offline recovery token.
- Back up the security store using the established signed-backup procedure.
  Restrict access to the database, signing keys and audits using OS ACLs.

## Reset commands

From a source checkout with the existing Python environment:

~~~powershell
# Windows
.venv\Scripts\python.exe -m scripts.reset_credentials
~~~

~~~bash
# Linux
.venv/bin/python -m scripts.reset_credentials
~~~

The source script supports `--data-dir <existing-security-directory>`.

For a frozen Windows offline distribution, no Python install is necessary:

~~~powershell
.\server\ClimateChamberServer.exe --reset-credentials
~~~

The frozen server respects `CHAMBER_SECURITY_DIR`. Run it in a real local
terminal, **not** as a background startup command or through remote HTTP.
Choose password proof (`p`) or recovery-token proof (`t`) at the prompt,
then enter and confirm a new password. Secrets are read with hidden input
and the new password must satisfy the current deployment policy.

On success, the security database is updated atomically:

1. Change the named **enabled administrator** password to a new scrypt hash.
2. Remove that administrator's PIN and set the security profile to
   **General**, permitting password login again.
3. Revoke **all** sessions, including other users' existing sessions, because
   the global login profile has changed.
4. Consume outstanding offline recovery tokens, clear that administrator's
   login lockout, and append a chained audit event.

Other users, roles, profile definitions, chamber configuration and test/run
evidence are preserved. Other users' PIN hashes remain stored, but cannot
be used in General mode. No default password is created, bootstrap cannot
be repeated, and no hardware I/O is performed.

After reset, sign in using the new password. To use PIN-only login again,
enroll a new administrator PIN and reselect Isolated LAN in the Admin tab.
Issue and escrow a **fresh** recovery token on separately controlled media:

~~~bash
python -m chamber_web.security.bootstrap --issue-recovery-token
~~~

Frozen Windows distribution:

~~~powershell
.\server\ClimateChamberServer.exe --issue-recovery-token
~~~

## Failure and recovery

If both the current administrator password and all valid recovery tokens
are unavailable, this command **cannot bypass authorization**. Follow the
site's independently authorized signed-backup restore or administrative
re-provisioning procedure. Do not delete `security.sqlite3`, invent a default
credential, tamper with the audit chain or replace signing keys. An absent or
corrupt security authority fails closed.

The older `--recover-admin` mode is unchanged: it resets **only** the
administrator password, leaving the security profile and PIN as they are.
Use `--reset-credentials` when an unavailable PIN or PIN-only profile may
otherwise prevent logging in.
