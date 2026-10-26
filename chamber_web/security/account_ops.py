"""Account maintenance on the SAME SecurityStore and SQLite authority as G08-min."""
from __future__ import annotations


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

        Revokes all of that account's sessions, without changing role.
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

    def reset_factory_credentials_offline(self) -> None:
        """Explicit HOST-ONLY recovery; restore one existing admin to factory values.

        This method is never exposed as an HTTP/WS action. The trusted CLI
        enforces local-interactive execution and an operator confirmation.
        Database ownership/OS permissions are the actual authority.
        Never create an account in a missing or unprovisioned security store.
        """
        from .auth import Actor, AuthorizationError, Role, _hash_password

        password_hash = _hash_password(b"admin")
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM bootstrap WHERE id=1").fetchone():
                raise AuthorizationError("No completed administrator provisioning")

            admins = db.execute(
                "SELECT id,username,enabled FROM users WHERE role='ADMIN'"
            ).fetchall()
            named = db.execute(
                "SELECT id,role FROM users WHERE username='admin'"
            ).fetchone()
            if named is not None:
                if named[1] != Role.ADMIN.value:
                    raise AuthorizationError(
                        "Username admin belongs to a non-administrator; "
                        "refusing to elevate or overwrite it"
                    )
                selected_id = named[0]
            elif len(admins) == 1:
                selected_id = admins[0][0]
            else:
                raise AuthorizationError(
                    "No unambiguous administrator account for factory recovery"
                )

            db.execute(
                "UPDATE users SET username='admin',password_hash=?,"
                "role='ADMIN',enabled=1 WHERE id=?",
                (password_hash, selected_id),
            )
            # Revoke all existing principals after a factory-credential restore.
            db.execute("UPDATE sessions SET revoked=1")
            db.execute("DELETE FROM login_failures")
            db.execute("DELETE FROM login_clients")
            self._audit(
                db, Actor(selected_id, "admin", Role.ADMIN),
                "recovery.factory.reset", "SUCCESS",
                detail="local operator recovery; all sessions revoked",
            )
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
