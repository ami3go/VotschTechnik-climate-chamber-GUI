## Factory administrator for new local installations

The NiceGUI server automatically provisions an administrator on first startup
**only if the security database has not already been provisioned**:

| Credential | Initial value |
| --- | --- |
| Username | `admin` |
| Password | `admin` |

There is one password login policy: 12–128 UTF-8 bytes after provisioning.
PINs, selectable security profiles and recovery tokens no longer exist.

After logging in, open **Admin → Administrator Credentials** to change the
administrator username or password. The weak `admin` password is accepted only
during factory provisioning. Password and username changes revoke the account's
existing sessions. Credentials are salted-hashed in the local SQLite security
store, never stored as plaintext. A normal restart does not restore the initial
values.

### Factory warning after restart

The login screen shows an advisory warning while an enabled ADMIN account still
accepts the factory password `admin`. The warning does **not** prevent saving
chamber settings, applying profiles, starting the server or controlling an
otherwise authorized device.

In **Admin → Administrator Credentials**, the interface displays the absolute
path to the active security database (`security.sqlite3`). If an old password
works again after a restart, confirm that the server runs as the same OS account
and resolves the same `CHAMBER_SECURITY_DIR` (default
`~/.chamber_web/security`). Running as a different account, as a service, or
with a different environment variable can select a **different** database.
Never delete or reset a security database to diagnose this; restore an approved
backup instead.

**Security limitation:** the publicly known factory password is for initial
commissioning and is unsafe on any accessible network. Replace it promptly,
even on an isolated network. The server warns but does not block lab startup
solely because the factory credential remains. Keep Host/Origin validation,
client allowlists, login lockout, audit retention and role authorization
enabled. Signed site authorization and safe temperature envelopes remain
separate mandatory gates.

A separate, explicit host-console maintenance script can restore the factory
credential when the administrator password is lost; this is never automatic or
available through the web interface. See
[local credential recovery](CREDENTIAL_RESET.md).

Regression coverage: `python -m pytest -q
tests/test_security_factory_credentials.py tests/test_web_factory_admin_ui.py`.
