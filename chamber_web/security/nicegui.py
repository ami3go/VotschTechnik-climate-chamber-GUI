"""NiceGUI login, logout and server-side authorization context (G08-min).

No user input, cookie value, or browser role directly reaches ChamberManager.
All future event handlers must revalidate session+CSRF through guards on EACH
action; creating a page once does not authorize subsequent WebSocket events.
"""
from __future__ import annotations

import os
import secrets
import threading

from nicegui import app, ui

from .auth import AuthenticationError, SecurityProfile, SecurityStore
from .http import OriginMiddleware
from .deployment import DeploymentPolicy
from .paths import security_directory


_store: SecurityStore | None = None
_store_lock = threading.Lock()


def get_security() -> SecurityStore:
    global _store
    with _store_lock:
        if _store is None:
            store = SecurityStore.from_environment(security_directory())
            store.provision_factory_admin()
            # A known factory password or PIN must never be offered over LAN.
            if deployment_policy.is_lan and any(store.factory_credentials_active()):
                raise RuntimeError(
                    "Factory administrator password/PIN active; change both via "
                    "localhost Admin panel before enabling LAN access")
            _store = store
        return _store


def cookie_secret() -> str:
    """Persistent 256-bit signing key, generated once; not in source or CLI."""
    directory = security_directory()
    directory.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        directory.chmod(0o700)
    path = directory / "nicegui_cookie_secret"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "w", encoding="ascii") as output:
            output.write(secrets.token_hex(32))
            output.flush()
            os.fsync(output.fileno())
    secret = path.read_text(encoding="ascii").strip()
    if len(secret) != 64 or any(ch not in "0123456789abcdef" for ch in secret):
        raise RuntimeError("Invalid persistent cookie signing key; startup refused")
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise PermissionError("Insecure cookie key permissions; startup refused")
    return secret


# Reject ambiguous or accidental LAN exposure as soon as app initializes.
# Registration stays idempotent so module re-execution (tests, reload) never
# stacks duplicate middleware.
deployment_policy = DeploymentPolicy.from_env()
if not any(entry.cls is OriginMiddleware for entry in app.user_middleware):
    app.add_middleware(OriginMiddleware, allowed_origins=deployment_policy.allowed_origins,
                       deployment=deployment_policy)


def active_tokens():
    """Read opaque session from server-side NiceGUI storage, not a UI field."""
    return app.storage.user.get("session"), app.storage.user.get("csrf")


def current_actor(*, touch: bool = False):
    token, _ = active_tokens()
    try:
        return get_security().authenticate(token, touch=touch)
    except AuthenticationError:
        return None


def require_authenticated_page(*, touch: bool = True) -> bool:
    if current_actor(touch=touch) is None:
        ui.navigate.to("/login")
        return False
    return True


def logout() -> None:
    token, _ = active_tokens()
    get_security().logout(token)
    app.storage.user.clear()
    ui.navigate.to("/login")


def factory_credential_warning(weak_password: bool, weak_pin: bool) -> str | None:
    """State exactly which factory credential is still active.

    The default PIN is separately enrolled and can remain unchanged after a
    successful administrator password update; do not tell users to change
    the password again in that case. No secrets or hashes are returned.
    """
    if weak_password and weak_pin:
        return (
            "Factory administrator password and PIN are still active. "
            "Change the password in Admin > Administrator Credentials and "
            "the PIN in Admin > Security Profiles before LAN use."
        )
    if weak_password:
        return (
            "Factory administrator password is still active; the factory PIN "
            "has been replaced. Change the password in Admin > "
            "Administrator Credentials before LAN use."
        )
    if weak_pin:
        return (
            "Administrator password has been changed. Only the factory PIN "
            "is still active. Change the PIN in Admin > Security Profiles "
            "(Enroll account PIN) before LAN use; the password does not "
            "need to be changed again."
        )
    return None


@ui.page("/login")
def login_page() -> None:
    if current_actor() is not None:
        ui.navigate.to("/")
        return

    def sign_in():
        try:
            request = getattr(ui.context.client, "request", None)
            peer = getattr(getattr(request, "client", None), "host", None)
            # Never skip peer throttling just because the framework does not
            # expose a Request for a websocket-originated login callback.
            session = get_security().login(
                username.value, password.value,
                client_id=peer if isinstance(peer, str) and peer else "unknown-peer",
                use_pin=(get_security().get_security_profile()
                         is SecurityProfile.ISOLATED_LAN),
            )
        except AuthenticationError:
            password.value = ""
            ui.notify("Invalid credentials or account temporarily locked", color="negative")
            return
        # New server-side credential is generated on every successful login.
        app.storage.user.clear()
        app.storage.user["session"] = session.session
        app.storage.user["csrf"] = session.csrf
        password.value = ""
        ui.navigate.to("/")

    with ui.card().classes("absolute-center items-stretch").style("min-width: 330px"):
        ui.label("Climate Chamber — sign in").classes("text-h5")
        isolated = get_security().get_security_profile() is SecurityProfile.ISOLATED_LAN
        ui.label("Isolated workstation · PIN sign-in · no automatic logout"
                 if isolated else "Offline local account · password sign-in").classes(
                     "text-caption")
        warning = factory_credential_warning(*get_security().factory_credentials_active())
        if warning:
            ui.label(warning).classes("text-caption text-orange-9")
        username = ui.input("Username").props("autocomplete=username")
        password = ui.input("PIN (6–12 digits)" if isolated else "Password",
                            password=True).props(
            "autocomplete=off inputmode=numeric" if isolated
            else "autocomplete=current-password")
        ui.button("Sign in", on_click=sign_in)


def require_browser_permission(permission, chamber_id: str | None = None):
    """Mandatory on every future NiceGUI mutation callback; not page creation."""
    from .guards import require_permission

    token, csrf = active_tokens()
    actor = get_security().authenticate(token, csrf=csrf, mutation=True)
    try:
        require_permission(actor, permission)
    except Exception:
        get_security().audit(actor, str(permission), "DENIED", chamber_id)
        raise
    get_security().audit(actor, str(permission), "AUTHORIZED", chamber_id)
    return actor
