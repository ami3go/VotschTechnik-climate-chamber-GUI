## Factory administrator for new local installations

The NiceGUI server automatically provisions an administrator on first startup
**only if the security database has not already been provisioned**:

| Credential | Initial value |
| --- | --- |
| Username | `admin` |
| Password | `admin` |
| PIN | `12345678` |
| Active security profile | General (password sign-in) |

The default PIN is stored from the start but is used for browser sign-in only
after an administrator explicitly selects **Isolated LAN** in Admin > Security
Profiles. General and Large Network profiles use passwords. PIN-only mode has
no server-side session expiry, as before.

After logging in, open **Admin > Administrator Credentials** to change the
administrator username or password, and **Admin > Security Profiles** to replace
the PIN. Password changes must comply with the configured minimum (12 UTF-8
bytes by default); the weak `admin` password is accepted *only* during factory
provisioning. Password changes and username changes revoke the account's
existing sessions; PIN enrollment revokes the target account's sessions.
Credentials are salted-hashed in the existing local SQLite security store, not
persisted as plaintext. A normal restart does not restore the initial values.

### Password changed but factory warning appears after restart

The factory **password** and **PIN** are separate credentials. Changing the
administrator password does not replace the factory PIN `12345678`. If
the PIN is still unchanged, the login screen now states specifically
that **the password has already been changed** and only the **PIN** needs
replacement in **Admin → Security Profiles → Enroll account PIN**. A warning
about the PIN does not mean your new password was forgotten.

In **Admin → Administrator Credentials**, the interface independently shows
whether the default password or default PIN is still active and displays the
absolute path to the currently used security database
(`security.sqlite3`). Changes are retained in that database across restarts.
If a previous password works again after restarting, confirm that the server
runs as the same OS account and resolves the same `CHAMBER_SECURITY_DIR`
(default `~/.chamber_web/security` for the server account). Running as a
different Windows account, as a service, or with a different environment
variable can select a *different* security database. Never delete or reset
a security database to diagnose this; preserve its keys, audit chain and
backups.


**Security limitation:** the publicly known factory credentials are for initial
loopback-local setup/testing, not network operation. LAN startup is refused
until both the default password and default PIN have been changed. Switching
to Large Network security profile requires changing the factory password.
Do not connect the application or physical chamber to an untrusted network
with factory credentials. Existing installations keep their credentials on normal restart. A separate,
explicit host-console maintenance script can restore these factory credentials
when the administrator password has been lost; this is never automatic or
available through the web interface. See [local credential recovery](CREDENTIAL_RESET.md).

Regression coverage: `python -m unittest discover -s tests -p
"test_security_factory_credentials.py" -v`; GUI smoke:
`python -m pytest -q tests/test_web_factory_admin_ui.py`. CI runs are
bounded with job watchdog timeouts. All tests use simulated services only.
