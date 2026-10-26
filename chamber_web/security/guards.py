"""Explicit G08-min entry point for browser-driven mutations.

Future G02-B/G03-C/G06-A use this facade, NEVER expose ChamberManager or its
G04 trusted server-only token-free compatibility calls to web requests.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from chamber_web.domain.chamber import (
    ChamberSafetyError,
    OperationState,
    ReadingQuality,
)

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
        # Internal revision prevents rearming after lease release/handover/reclaim.
        # It is not an ownership token and is never sent to the browser.
        self._token_revision = 0

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
                self._token_revision += 1
        elif command == "release_operator":
            with self._token_lock:
                self._token_owner.pop(token, None)
                self._token_names.pop(token, None)
                self._token_revision += 1
        self._security.audit(actor, "chamber." + command, "SUCCESS", chamber_id)
        return result

    def stop(self, session: str | None, csrf: str | None, chamber_id: str) -> None:
        # Intentionally NO operator_token. STOP is role-checked but lease-independent.
        self.execute(session, csrf, chamber_id, "stop")

    def ensure_manual_operator_lease(
        self, session: str | None, csrf: str | None, chamber_id: str,
    ) -> None:
        """Acquire a free manual lease on an explicit operator action.

        Never transfer an existing lease, including a G06 profile runner lease.
        This operation cannot issue any device write or bypass G04 fencing.
        The registry lock serializes competing browser claims; G04 remains the
        final authority, including when a profile owns the controller.
        """
        self.ensure_manual_operator_lease_revision(session, csrf, chamber_id)

    def ensure_manual_operator_lease_revision(
        self, session: str | None, csrf: str | None, chamber_id: str,
    ) -> int:
        """Acquire a free manual lease and return its registry revision.

        The revision is read inside the same critical section as the claim, so
        a concurrent reader (for example the one-second dashboard refresh)
        can never make an *owned* lease look unowned. The previous design used
        a separate best-effort, non-blocking probe that was only ever safe on
        the priority STOP path; on a Start path its contention was
        indistinguishable from "no lease held" and refused a legitimate
        operator Start while the STOP fence stayed latched.

        Returns the current registry revision of the lease the caller holds.
        """
        actor = self.authorize(
            session, csrf, Permission.CHAMBER_CONTROL, chamber_id=chamber_id)
        self._manager.get(chamber_id)
        with self._token_lock:
            if actor.user_id in self._token_owner.values():
                return self._token_revision
            if self._token_owner:
                raise AuthorizationError("Another operator owns chamber control")
            # execute() audits INTENT/SUCCESS and registers the opaque token.
            # The reentrant lock makes the check/claim/update atomic for manual
            # browser requests while G04 blocks a parallel G06 owner.
            self.execute(session, csrf, chamber_id, "claim_operator")
            return self._token_revision

    def release_stopped_manual_lease_for_profile(
        self, session: str | None, csrf: str | None, chamber_id: str,
        *, expected_generation: int,
    ) -> bool:
        """Hand an idle manual lease to G06 only on its owner's explicit Run.

        No other user's lease can be transferred; a live chamber RUNNING,
        UNKNOWN, or under a new STOP generation is never released. G04's
        subsequent profile claim is independent and must pass full admission.
        STOP remains lease-independent and never waits for this registry.
        """
        actor = self.authorize(
            session, csrf, Permission.PROFILE_RUN, chamber_id=chamber_id)
        self._manager.get(chamber_id)
        with self._token_lock:
            if not self._token_owner:
                return False
            if (len(self._token_owner) != 1 or
                    actor.user_id not in self._token_owner.values()):
                raise AuthorizationError(
                    "Chamber manual control belongs to another operator")
            health = self._manager.health(chamber_id)
            if (not health.connected or health.stop_latched or
                    health.state != "VERIFIED_STOPPED" or
                    health.generation != expected_generation):
                raise ChamberSafetyError(
                    "Stop and verify the chamber before running a profile")
            # A second authoritative status check is required before handing
            # over the lease. The profile runner independently rechecks.
            sample = self._manager.status(chamber_id)
            sampled = sample.sampled_at_utc
            if (sample.quality is not ReadingQuality.GOOD or
                    sample.operation_state is not OperationState.STOPPED or
                    sampled is None or sampled.tzinfo is None or
                    not -1 <= (datetime.now(timezone.utc) -
                               sampled.astimezone(timezone.utc)).total_seconds() <= 5):
                raise ChamberSafetyError(
                    "Fresh STOPPED chamber status required for profile handoff")
            latest = self._manager.health(chamber_id)
            if (latest.stop_latched or latest.state != "VERIFIED_STOPPED" or
                    latest.generation != expected_generation):
                raise ChamberSafetyError("Chamber state changed during profile handoff")
            token = next(iter(self._token_owner))
            self._security.audit(
                actor, "chamber.manual_to_profile", "INTENT", chamber_id)
            try:
                self.execute(session, csrf, chamber_id, "release_operator", token)
            except BaseException as exc:
                self._security.audit(
                    actor, "chamber.manual_to_profile", "FAILED",
                    chamber_id, type(exc).__name__)
                raise
            self._security.audit(
                actor, "chamber.manual_to_profile", "SUCCESS", chamber_id)
            return True

    def owned_lease_revision_now(self, user_id: int) -> int | None:
        """Best-effort, nonblocking lease-owner snapshot for priority STOP.

        Never wait for an admin handover or a token-registry lock before
        dispatching STOP. Contention disables automatic rearm, not STOP.

        Only the priority STOP path may use this probe: ``None`` means
        "unknown", which is safe there (the rearm is merely skipped) but is
        indistinguishable from "no lease held" on a Start path. A Start must
        use ``ensure_manual_operator_lease_revision`` instead.
        """
        if not self._token_lock.acquire(blocking=False):
            return None
        try:
            return (self._token_revision
                    if user_id in self._token_owner.values() else None)
        finally:
            self._token_lock.release()

    def rearm_after_owned_verified_stop(
        self, session: str | None, csrf: str | None, chamber_id: str,
        *, expected_generation: int, expected_lease_revision: int,
    ) -> bool:
        """Rearm a *verified* STOP for the authenticated current lease owner.

        Called after STOP by its original owner, or on an explicit subsequent
        Start/Set Target request. Never clears UNKNOWN/FAULT, never issues
        START itself, and never accepts a browser-provided bearer token.
        G04 independently checks fresh STOPPED readback and exact generation.
        A concurrent STOP, changed lease, revoked session or G06-owned
        controller cannot be recovered through this path.
        """
        actor = self.authorize(session, csrf, Permission.CHAMBER_CONTROL,
                               chamber_id=chamber_id)
        self._manager.get(chamber_id)
        with self._token_lock:
            if (self._token_revision != expected_lease_revision or
                    not any(owner_id == actor.user_id
                            for owner_id in self._token_owner.values())):
                return False
            health = self._manager.health(chamber_id)
            if (not health.connected or not health.stop_latched or
                    health.state != "VERIFIED_STOPPED" or
                    health.generation != expected_generation):
                return False
            # Durable audit INTENT before changing the controller latch.
            self._security.audit(
                actor, "chamber.stop.auto_rearm", "INTENT", chamber_id)
            try:
                # G04 independently rechecks fresh, matching, GOOD STOPPED
                # readback and the same generation before clearing the
                # durable uncertainty fence. A newer STOP cannot be bypassed.
                self._manager.reconcile_stop(chamber_id)
            except BaseException as exc:
                self._security.audit(
                    actor, "chamber.stop.auto_rearm", "FAILED",
                    chamber_id, type(exc).__name__)
                raise
            self._security.audit(
                actor, "chamber.stop.auto_rearm", "SUCCESS", chamber_id)
            return True

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
                self._token_revision += 1
        except BaseException as exc:
            self._security.audit(actor, "chamber.handover", "FAILED",
                                 chamber_id, type(exc).__name__)
            raise
        self._security.audit(actor, "chamber.handover", "SUCCESS", chamber_id)
