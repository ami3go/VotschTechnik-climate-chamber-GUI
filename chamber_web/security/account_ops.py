"""Account maintenance on the SAME SecurityStore and SQLite authority as G08-min.

Recovery tokens are offline, one-use, independently random credentials. They
are never sent over the application HTTP/WS surface or stored in plaintext.
"""
from __future__ import annotations

import secrets


class AccountOperations:
    """Mixin: requires SecurityStore._db, _audit, authenticate and admin fence."""

    def change_password(self, session: str, csrf: str,
                        old_password: str, new_password: str) -> None:
        from .auth import (AuthenticationError, _digest, _hash_password,
                           _password_bytes, _verify_password)
        actor = self.authenticate(session, csrf=csrf, mutation=True)
        pw = _hash_password(_password_bytes(
            new_password, min_bytes=self.password_min_bytes))
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT u.password_hash,s.revoked,s.created_at,s.last_seen"
                " FROM users u JOIN sessions s ON u.id=s.user_id"
                " WHERE s.token_hash=? AND u.id=? AND u.enabled=1",
                (_digest(session), actor.user_id),
            ).fetchone()
            now = self.clock()
            if (not row or row[1] or
                    self._session_expired(db, row[2], row[3], now) or
                    not _verify_password(old_password, row[0])):
                self._audit(db, actor, "user.password", "DENIED")
                db.commit()
                raise AuthenticationError("Current password or session invalid")
            db.execute("UPDATE users SET password_hash=? WHERE id=?",
                       (pw, actor.user_id))
            db.execute("UPDATE sessions SET revoked=1 WHERE user_id=?",
                       (actor.user_id,))
            db.execute("DELETE FROM login_failures WHERE username=?",
                       (actor.username,))
            self._audit(db, actor, "user.password", "SUCCESS")
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def change_admin_username(self, session: str, csrf: str,
                              password: str, new_username: str) -> None:
        """Rename the signed-in administrator after password reauthentication.

        Revokes all of that account's sessions, without changing role or PIN.
        """
        from .auth import AuthorizationError, Role
        self._validate_username(new_username)
        actor = self.authenticate(session, csrf=csrf, mutation=True)
        if actor.role is not Role.ADMIN:
            raise AuthorizationError("Administrator required")
        confirmed_hash = self._confirm_admin_password(actor, password)
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            self._require_current_admin(db, session, actor)
            current = db.execute(
                "SELECT password_hash FROM users WHERE id=?", (actor.user_id,)
            ).fetchone()
            if not current or current[0] != confirmed_hash:
                raise AuthorizationError("Administrator credentials changed")
            if db.execute(
                "SELECT 1 FROM users WHERE username=? AND id<>?",
                (new_username, actor.user_id),
            ).fetchone():
                raise ValueError("Username already exists")
            db.execute("UPDATE users SET username=? WHERE id=?",
                       (new_username, actor.user_id))
            db.execute("UPDATE sessions SET revoked=1 WHERE user_id=?",
                       (actor.user_id,))
            db.execute("DELETE FROM login_failures WHERE username=?",
                       (actor.username,))
            db.execute("DELETE FROM login_failures WHERE username=?",
                       (new_username,))
            self._audit(db, actor, "user.username", "SUCCESS",
                        detail="Administrator account renamed")
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def revoke_sessions(self, admin_session: str, csrf: str,
                        username: str) -> None:
        from .auth import AuthorizationError, Role
        actor = self.authenticate(admin_session, csrf=csrf, mutation=True)
        if actor.role is not Role.ADMIN:
            self.audit(actor, "session.revoke", "DENIED")
            raise AuthorizationError("Administrator required")
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            self._require_current_admin(db, admin_session, actor)
            row = db.execute("SELECT id FROM users WHERE username=?",
                             (username,)).fetchone()
            if row is None:
                raise ValueError("Unknown account")
            db.execute("UPDATE sessions SET revoked=1 WHERE user_id=?",
                       (row[0],))
            self._audit(db, actor, "session.revoke", "SUCCESS", detail=username)
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def issue_recovery_token(self, admin_session: str, csrf: str,
                             lifetime_s: int = 30 * 86400) -> str:
        from .auth import AuthorizationError, Role, _digest
        if not 60 <= lifetime_s <= 365 * 86400:
            raise ValueError("Recovery lifetime outside permitted range")
        actor = self.authenticate(admin_session, csrf=csrf, mutation=True)
        if actor.role is not Role.ADMIN:
            self.audit(actor, "recovery.issue", "DENIED")
            raise AuthorizationError("Administrator required")
        token = secrets.token_urlsafe(48)
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            self._require_current_admin(db, admin_session, actor)
            now = self.clock()
            # Issuance invalidates all older tokens: only most recent offline
            # credential remains usable; never add it to program logs.
            db.execute("DELETE FROM recovery_tokens")
            db.execute(
                "INSERT INTO recovery_tokens(token_hash,created_at,expires_at,"
                "issued_by) VALUES(?,?,?,?)",
                (_digest(token), now, now + lifetime_s, actor.user_id),
            )
            self._audit(db, actor, "recovery.issue", "SUCCESS")
            db.commit()
            return token
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def recover_admin_offline(self, token: str, username: str,
                              new_password: str, *,
                              reset_credentials: bool = False) -> None:
        """Local recovery; optionally clear PIN and restore password login.

        The CLI must authenticate the administrator before calling this.
        The transaction preserves the audit chain and all unrelated data.
        """
        from .auth import (AuthenticationError, Actor, Role, SecurityProfile,
                           _digest, _hash_password, _password_bytes)
        if not isinstance(token, str) or not 32 <= len(token) <= 256:
            raise AuthenticationError("Invalid recovery credential")
        pw = _hash_password(_password_bytes(
            new_password, min_bytes=self.password_min_bytes))
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            now = self.clock()
            record = db.execute(
                "SELECT expires_at FROM recovery_tokens WHERE token_hash=?",
                (_digest(token),),
            ).fetchone()
            user = db.execute("SELECT id,username FROM users WHERE username=?"
                              " AND role='ADMIN' AND enabled=1", (username,)).fetchone()
            if not record or record[0] <= now or not user:
                self._audit(db, None, "recovery.use", "DENIED")
                db.commit()
                raise AuthenticationError("Invalid or expired recovery credential")
            db.execute("DELETE FROM recovery_tokens")
            db.execute("UPDATE users SET password_hash=? WHERE id=?",
                       (pw, user[0]))
            if reset_credentials:
                # A recovered password alone cannot log in to PIN-only mode.
                # Restore password sign-in and revoke ALL previously issued
                # sessions to fence the global security-profile transition.
                db.execute("UPDATE users SET pin_hash=NULL WHERE id=?",
                           (user[0],))
                db.execute("UPDATE security_policy SET profile=? WHERE id=1",
                           (SecurityProfile.GENERAL.value,))
                db.execute("UPDATE sessions SET revoked=1")
            else:
                db.execute("UPDATE sessions SET revoked=1 WHERE user_id=?",
                           (user[0],))
            db.execute("DELETE FROM login_failures WHERE username=?",
                       (username,))
            self._audit(db, Actor(user[0], user[1], Role.ADMIN),
                        "recovery.credentials.reset" if reset_credentials
                        else "recovery.use", "SUCCESS")
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
