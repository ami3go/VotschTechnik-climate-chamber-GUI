# Local factory credential recovery

Use this script from a local, interactive console on the **server PC** when
administrator credentials have been forgotten. It requires no existing
password, PIN or recovery token. It is not accessible through the web UI.

## Procedure

1. Bring the chamber to a safe state and stop the GUI server. Credential
   recovery does not stop physical hardware.
2. Log into the server operating system as the account that owns the existing
   security database. Remote sessions and unattended execution are refused.
3. Open a local terminal and run one of:

Windows packaged installation:
```powershell
.\server\ClimateChamberServer.exe --reset-credentials
```

Windows source checkout:
```powershell
.venv\Scripts\python.exe -m scripts.reset_credentials
```

Linux source checkout:
```bash
.venv/bin/python -m scripts.reset_credentials
```

The source script also supports direct file execution and `--data-dir`.
Both versions use `CHAMBER_SECURITY_DIR` when configured, otherwise
`~/.chamber_web/security` for the executing OS account.

4. Read the warning and type `RESET` to confirm.
5. Restart the server and use the documented factory administrator login.
   Immediately replace factory credentials before permitting LAN access.

## Recovery effects

The script restores the administrator username, password, and PIN to the
values documented in [Factory Credentials](FACTORY_CREDENTIALS.md), and
selects the **General** security profile (password login; PIN-only login
requires Isolated LAN). It revokes all sessions and outstanding recovery
tokens and resets login lockouts. Other users and stored chamber profiles,
configuration, run records and evidence are preserved.

If the default username belongs to a non-administrator, or there are
multiple ambiguous administrator accounts, reset is refused. The existing
database and tamper-evident audit history must be intact; a successful reset
adds a `recovery.factory.reset` event.

The OS account's filesystem access is the security boundary. The command
refuses non-TTY execution and detected SSH/RDP sessions, but software
cannot absolutely prove physical console presence against a privileged
local operator. Do not expose the service account or security database to
untrusted users. The application also refuses LAN startup while factory
credentials remain enabled.

The separate `--recover-admin` mode still supports one-time recovery
tokens and does not perform a factory reset.
