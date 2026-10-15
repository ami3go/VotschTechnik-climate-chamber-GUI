"""Explicit G08-min entry point for browser-driven mutations.

Future G02-B/G03-C/G06-A use this facade, NEVER expose ChamberManager or its
G04 trusted server-only token-free compatibility calls to web requests.
"""
from __future__ import annotations

import threading
from enum import Enum
from typing import Any

from .auth import Actor, AuthorizationError, Role, SecurityStore


class Permission(str, Enum):
    READ = "read"
    CHAMBER_CONTROL = "chamber.control"
    STOP = "chamber.stop"
    RECONCILE = "chamber.reconcile"
    PROFILE_EDIT = "profile.edit"
    PROFILE_RUN = "profile.run"
    SETTINGS = "settings.write"
    AUDIT_READ = "audit.read"
    USER_ADMIN = "user.admin"


_GRANTS = {
    Role.VIEWER: frozenset({Permission.READ}),
    Role.OPERATOR: frozenset({
        Permission.READ, Permission.CHAMBER_CONTROL, Permission.STOP,
        Permission.PROFILE_EDIT, Permission.PROFILE_RUN,
    }),
    Role.ADMIN: frozenset(Permission),
}


def require_permission(actor: Actor, permission: Permission) -> None:
    if not isinstance(permission, Permission) or permission not in _GRANTS[actor.role]:
        raise AuthorizationError(f"Permission denied: {permission}")


_COMMAND_PERMISSIONS = {
    "set_temperature": Permission.CHAMBER_CONTROL,
    "start": Permission.CHAMBER_CONTROL,
    "stop": Permission.STOP,
    "reconcile_stop": Permission.RECONCILE,
    "claim_operator": Permission.CHAMBER_CONTROL,
    "release_operator": Permission.CHAMBER_CONTROL,
    "connect": Permission.SETTINGS,
    "disconnect": Permission.SETTINGS,
}


class AuthorizedChamber:
    """Fail-closed facade and audit fence; no hardware-specific imports.

    A CSRF token is mandatory for all browser-originating mutation calls.
    The underlying G04 owner-lease is independent of login/role authority.
    """

    def __init__(self, manager: Any, security: SecurityStore):
        self._manager = manager
        self._security = security
        # A token belongs to the authenticated identity which claimed it.
        # Single server-owned facade; never give its token registry to browsers.
        self._token_lock = threading.RLock()
        self._token_owner: dict[str, int] = {}
        self._token_names: dict[str, str] = {}

    def authorize(self, session: str | None, csrf: str | None,
                  permission: Permission, *, chamber_id: str | None = None) -> Actor:
        try:
            actor = self._security.authenticate(session, csrf=csrf, mutation=True)
        except Exception:
            self._security.audit(None, "auth.check", "DENIED", chamber_id)
            raise
        try:
            require_permission(actor, permission)
        except AuthorizationError:
            self._security.audit(actor, permission.value, "DENIED", chamber_id)
            raise
        self._security.audit(actor, permission.value, "AUTHORIZED", chamber_id)
        return actor

    def execute(self, session: str | None, csrf: str | None, chamber_id: str,
                command: str, *args: Any, **kwargs: Any) -> Any:
        if command not in _COMMAND_PERMISSIONS:
            raise AuthorizationError("Unknown chamber mutation")
        actor = self.authorize(session, csrf, _COMMAND_PERMISSIONS[command],
                               chamber_id=chamber_id)
        # Only the claimant may use or release a G04 lease token; the G04
        # backend token itself is NOT a login credential. Never fall back to
        # token-free G04 trusted server compatibility from a browser.
        if command == "claim_operator":
            args, kwargs = (actor.username,), {}
        if command in {"start", "set_temperature", "release_operator"}:
            token = (args[0] if args else kwargs.get("token")) if (
                command == "release_operator") else kwargs.get("operator_token")
            with self._token_lock:
                owner_id = self._token_owner.get(token) if isinstance(token, str) else None
            if owner_id != actor.user_id:
                self._security.audit(actor, "chamber." + command, "DENIED",
                                     chamber_id, "operator ownership")
                raise AuthorizationError("Authenticated operator ownership required")
        # Durable INTENT must commit BEFORE dispatch. A full disk blocks writes.
        self._security.audit(actor, "chamber." + command, "INTENT", chamber_id)
        try:
            # Never accept a user-supplied method name outside the allowlist.
            result = getattr(self._manager, command)(chamber_id, *args, **kwargs)
        except BaseException as exc:
            self._security.audit(actor, "chamber." + command, "FAILED",
                                 chamber_id, type(exc).__name__)
            raise
        if command == "claim_operator":
            with self._token_lock:
                self._token_owner[result] = actor.user_id
                self._token_names[result] = actor.username
        elif command == "release_operator":
            with self._token_lock:
                self._token_owner.pop(token, None)
                self._token_names.pop(token, None)
        self._security.audit(actor, "chamber." + command, "SUCCESS", chamber_id)
        return result

    def stop(self, session: str | None, csrf: str | None, chamber_id: str) -> None:
        # Intentionally NO operator_token. STOP is role-checked but lease-independent.
        self.execute(session, csrf, chamber_id, "stop")

    def ownership_view(self, session: str | None, chamber_id: str) -> tuple[str | None, bool]:
        """Read-only, no owner tokens leave this server-owned facade."""
        actor = self._security.authenticate(session, touch=False)
        require_permission(actor, Permission.READ)
        self._manager.get(chamber_id)  # reject stale/wrong device before reading owner
        with self._token_lock:
            for token, owner_id in self._token_owner.items():
                return self._token_names.get(token), owner_id == actor.user_id
        return None, False

    def execute_owned(self, session: str | None, csrf: str | None,
                      chamber_id: str, command: str, *args: Any) -> Any:
        """Bind manual START/setpoint/release to the server-held user lease.

        Neither the browser nor ManualControlService handles G04 bearer tokens.
        Each dispatch reauthenticates, checks ownership, audits, then uses the
        G04 operator_generation fence. Other commands cannot use this method.
        """
        if command not in ("start", "set_temperature", "release_operator"):
            raise AuthorizationError("Unsupported owned chamber command")
        actor = self.authorize(session, csrf, Permission.CHAMBER_CONTROL,
                               chamber_id=chamber_id)
        with self._token_lock:
            token = next((key for key, user_id in self._token_owner.items()
                          if user_id == actor.user_id), None)
        if token is None:
            self._security.audit(actor, "chamber." + command, "DENIED",
                                 chamber_id, "No operator lease held by this user")
            raise AuthorizationError("Claim the operator lease first")
        if command == "release_operator":
            return self.execute(session, csrf, chamber_id, command, token)
        return self.execute(session, csrf, chamber_id, command, *args,
                            operator_token=token)

    def handover_to_admin(self, session: str | None, csrf: str | None,
                          chamber_id: str) -> None:
        """Explicit ADMIN takeover of the existing manual lease.

        There is no silent release, timeout-based takeover, or auto-restart.
        A partially failed handover leaves control unclaimed; an operator must
        explicitly reclaim it. STOP never waits on this token-registry lock.
        """
        actor = self.authorize(session, csrf, Permission.SETTINGS,
                               chamber_id=chamber_id)
        self._manager.get(chamber_id)
        self._security.audit(actor, "chamber.handover", "INTENT", chamber_id)
        try:
            with self._token_lock:
                if len(self._token_owner) != 1:
                    raise AuthorizationError("No known lease to hand over; reconcile manually")
                token, user_id = next(iter(self._token_owner.items()))
                if user_id == actor.user_id:
                    raise AuthorizationError("Administrator already owns the lease")
                # Recheck the live G08 session after waiting for the lease lock.
                # A revoked/expired administrator cannot continue a takeover.
                self.authorize(session, csrf, Permission.SETTINGS,
                               chamber_id=chamber_id)
                self._manager.release_operator(chamber_id, token)
                self._token_owner.pop(token)
                self._token_names.pop(token, None)
                # Release and claim are separate G04 generation transitions.
                # Recheck again so a mid-handover revocation cannot claim it.
                self.authorize(session, csrf, Permission.SETTINGS,
                               chamber_id=chamber_id)
                replacement = self._manager.claim_operator(chamber_id, actor.username)
                self._token_owner[replacement] = actor.user_id
                self._token_names[replacement] = actor.username
        except BaseException as exc:
            self._security.audit(actor, "chamber.handover", "FAILED",
                                 chamber_id, type(exc).__name__)
            raise
        self._security.audit(actor, "chamber.handover", "SUCCESS", chamber_id)
