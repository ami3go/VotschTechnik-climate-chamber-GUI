"""Explicit G08-min entry point for browser-driven mutations.

Future G02-B/G03-C/G06-A use this facade, NEVER expose ChamberManager or its
G04 trusted server-only token-free compatibility calls to web requests.
"""
from __future__ import annotations

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
        # Durable INTENT must commit BEFORE dispatch. A full disk blocks writes.
        self._security.audit(actor, "chamber." + command, "INTENT", chamber_id)
        try:
            # Never accept a user-supplied method name outside the allowlist.
            result = getattr(self._manager, command)(chamber_id, *args, **kwargs)
        except BaseException as exc:
            self._security.audit(actor, "chamber." + command, "FAILED",
                                 chamber_id, type(exc).__name__)
            raise
        self._security.audit(actor, "chamber." + command, "SUCCESS", chamber_id)
        return result

    def stop(self, session: str | None, csrf: str | None, chamber_id: str) -> None:
        # Intentionally NO operator_token. STOP is role-checked but lease-independent.
        self.execute(session, csrf, chamber_id, "stop")
