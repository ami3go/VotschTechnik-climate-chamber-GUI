# Local factory credential recovery

Use this from a local, interactive console on the **server PC** when the
administrator password has been forgotten. It requires no existing password
and is not accessible through the web UI.

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

Both versions use `CHAMBER_SECURITY_DIR` when configured, otherwise
`~/.chamber_web/security` for the executing OS account.

4. Read the warning and type `RESET` to confirm.
5. Restart the server and use the factory administrator login. Immediately
   replace the factory password before permitting lab-network access.

## Recovery effects

The script restores the administrator username and password documented in
[Factory Credentials](FACTORY_CREDENTIALS.md), revokes all sessions and resets
login lockouts. Other users, stored chamber profiles, configuration, run
records and audit evidence are preserved.

If the username `admin` belongs to a non-administrator, or there are multiple
ambiguous administrator accounts, reset is refused. The existing database and
audit history must be intact; a successful reset adds a
`recovery.factory.reset` event.

The OS account's filesystem access is the security boundary. The command
refuses non-TTY execution and detected SSH/RDP sessions, but software cannot
absolutely prove physical console presence against a privileged local operator.
Do not expose the service account or security database to untrusted users.
