"""Offline identities, short-lived opaque server-side sessions, durable audit.

No browser-supplied role is trusted. No default account or password exists.
The SQLite database and NiceGUI cookie signing secret are deployment-local.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable


class AuthenticationError(Exception):
    """Anonymous, expired, revoked, or invalid credentials."""


class AuthorizationError(Exception):
    """Authenticated principal lacks a required permission."""


class Role(str, Enum):
    ADMIN = "ADMIN"
    OPERATOR = "OPERATOR"
    VIEWER = "VIEWER"


@dataclass(frozen=True)
class Actor:
    user_id: int
    username: str
    role: Role


@dataclass(frozen=True)
class SessionTokens:
    session: str
    csrf: str


_USERNAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{2,63}$")
# Intentionally bounded for predictable CPU/memory consumption on login.
_SCRYPT_N = 1 << 15
_SCRYPT_R = 8
_SCRYPT_P = 1
_DUMMY_SALT = b"no-user-salt-16!"
_DUMMY_HASH = hashlib.scrypt(b"no-such-user-password", salt=_DUMMY_SALT,
                             n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32, maxmem=64 * 1024 * 1024)


def _password_bytes(password: str) -> bytes:
    if not isinstance(password, str):
        raise ValueError("Invalid password type")
    raw = password.encode("utf-8")
    if not 12 <= len(raw) <= 1024:
        raise ValueError("Password must be 12–1024 UTF-8 bytes")
    return raw


def _hash_password(raw: bytes) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(raw, salt=salt, n=_SCRYPT_N, r=_SCRYPT_R,
                            p=_SCRYPT_P, dklen=32, maxmem=64 * 1024 * 1024)
    return f"scrypt:{_SCRYPT_N}:{_SCRYPT_R}:{_SCRYPT_P}:{salt.hex()}:{digest.hex()}"


def _verify_password(password: str, stored: str | None) -> bool:
    if not isinstance(password, str) or len(password.encode("utf-8")) > 1024:
        return False
    if stored is None:
        hmac.compare_digest(hashlib.scrypt(password.encode(), salt=_DUMMY_SALT,
                            n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32, maxmem=64 * 1024 * 1024), _DUMMY_HASH)
        return False
    try:
        algorithm, n, r, p, salt, expected = stored.split(":")
        if (algorithm, int(n), int(r), int(p)) != (
                "scrypt", _SCRYPT_N, _SCRYPT_R, _SCRYPT_P):
            return False
        computed = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt),
                                  n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32, maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(computed, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class SecurityStore:
    """Process- and thread-safe SQLite identity authority.

    Uses a fresh connection per transaction so concurrent browser clients, and
    multiple processes sharing this *local* database, cannot race bootstrap or
    session revocation. The clock injection is for deterministic unit tests.
    """

    def __init__(self, directory: Path | None = None, *,
                 clock: Callable[[], float] = time.time,
                 idle_timeout_s: int = 1800,
                 absolute_timeout_s: int = 28800):
        if idle_timeout_s <= 0 or absolute_timeout_s <= 0:
            raise ValueError("Session lifetimes must be positive")
        self.directory = Path(directory or (Path.home() / ".chamber_web" / "security"))
        self.directory.mkdir(parents=True, exist_ok=True)
        if __import__("os").name != "nt":
            self.directory.chmod(0o700)
        self.database = self.directory / "security.sqlite3"
        self.clock = clock
        self.idle_timeout_s = idle_timeout_s
        self.absolute_timeout_s = absolute_timeout_s
        self._lock = threading.RLock()
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS bootstrap (
                    id INTEGER PRIMARY KEY CHECK (id=1),
                    completed_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('ADMIN','OPERATOR','VIEWER')),
                    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1))
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    csrf_hash TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0 CHECK(revoked IN (0,1))
                );
                CREATE TABLE IF NOT EXISTS login_failures (
                    username TEXT PRIMARY KEY COLLATE NOCASE,
                    attempts INTEGER NOT NULL,
                    lock_until REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    at_utc REAL NOT NULL,
                    user_id INTEGER,
                    username TEXT,
                    role TEXT,
                    action TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    chamber_id TEXT,
                    detail TEXT NOT NULL
                );
            """)
        if __import__("os").name != "nt":
            self.database.chmod(0o600)

    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.database, timeout=10, isolation_level=None)
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _audit(self, db: sqlite3.Connection, actor: Actor | None, action: str,
               outcome: str, chamber_id: str | None = None, detail: str = "") -> None:
        db.execute(
            "INSERT INTO audit(at_utc,user_id,username,role,action,outcome,chamber_id,detail)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (self.clock(), actor.user_id if actor else None,
             actor.username if actor else None, actor.role.value if actor else None,
             action[:80], outcome[:40], chamber_id, detail[:300]),
        )

    def audit(self, actor: Actor | None, action: str, outcome: str,
              chamber_id: str | None = None, detail: str = "") -> None:
        # Audit insertion failure is never silently downgraded to success.
        with self._db() as db:
            with db:
                self._audit(db, actor, action, outcome, chamber_id, detail)

    def is_bootstrapped(self) -> bool:
        db = self._db()
        try:
            return db.execute("SELECT 1 FROM bootstrap WHERE id=1").fetchone() is not None
        finally:
            db.close()

    def bootstrap_admin(self, username: str, password: str) -> None:
        """Trusted LOCAL CLI only; atomic one-time initialization, never an HTTP route."""
        self._validate_username(username)
        encoded = _password_bytes(password)
        password_hash = _hash_password(encoded)
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM bootstrap WHERE id=1").fetchone():
                raise AuthorizationError("Initial administrator already provisioned")
            cursor = db.execute(
                "INSERT INTO users(username,password_hash,role) VALUES(?,?,?)",
                (username, password_hash, Role.ADMIN.value),
            )
            db.execute("INSERT INTO bootstrap(id,completed_at) VALUES(1,?)", (self.clock(),))
            self._audit(db, Actor(cursor.lastrowid, username, Role.ADMIN),
                        "bootstrap", "SUCCESS")
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _validate_username(username: str) -> None:
        if not isinstance(username, str) or not _USERNAME.fullmatch(username):
            raise ValueError("Username must be 3–64 ASCII letters, digits, _ . or -")

    def login(self, username: str, password: str) -> SessionTokens:
        now = self.clock()
        if not isinstance(username, str) or len(username) > 64:
            raise AuthenticationError("Invalid username or password")
        # Expensive scrypt occurs outside the SQLite write transaction. Login
        # traffic must not hold the audit/STOP intent database lock.
        db = self._db()
        try:
            candidate = db.execute(
                "SELECT id,username,password_hash,enabled FROM users WHERE username=?",
                (username,),
            ).fetchone()
            valid = _verify_password(password, candidate[2] if candidate else None)
            with self._lock:
                db.execute("BEGIN IMMEDIATE")
                # Re-read after locking: account may have been disabled, or
                # password changed, while the hash was being computed.
                row = db.execute(
                    "SELECT id,username,password_hash,enabled,role FROM users"
                    " WHERE username=?", (username,),
                ).fetchone()
                fail = db.execute(
                    "SELECT attempts,lock_until FROM login_failures WHERE username=?",
                    (username,),
                ).fetchone()
                locked = bool(fail and fail[0] >= 5 and fail[1] > now)
                current = bool(candidate and row and candidate[2] == row[2]
                               and candidate[0] == row[0] and row[3])
                if locked or not valid or not current:
                    attempts = fail[0] + 1 if fail and fail[1] > now else 1
                    # Track a sliding 15-minute failure window. Only the
                    # fifth failed attempt activates account lockout.
                    until = now + 900
                    db.execute(
                        "INSERT INTO login_failures(username,attempts,lock_until) VALUES(?,?,?)"
                        " ON CONFLICT(username) DO UPDATE SET attempts=excluded.attempts,"
                        " lock_until=excluded.lock_until",
                        (username, attempts, until),
                    )
                    self._audit(db, None, "login", "DENIED",
                                detail="invalid credentials or lockout")
                    db.commit()
                    raise AuthenticationError("Invalid username or password")
                db.execute("DELETE FROM login_failures WHERE username=?", (username,))
                tokens = SessionTokens(secrets.token_urlsafe(32), secrets.token_urlsafe(32))
                db.execute(
                    "INSERT INTO sessions(token_hash,user_id,csrf_hash,created_at,last_seen)"
                    " VALUES(?,?,?,?,?)",
                    (_digest(tokens.session), row[0], _digest(tokens.csrf), now, now),
                )
                self._audit(db, Actor(row[0], row[1], Role(row[4])), "login", "SUCCESS")
                db.commit()
                return tokens
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def authenticate(self, session: str | None, *, csrf: str | None = None,
                     mutation: bool = False) -> Actor:
        if not isinstance(session, str) or not 20 <= len(session) <= 128:
            raise AuthenticationError("Authentication required")
        now = self.clock()
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT s.csrf_hash,s.created_at,s.last_seen,s.revoked,"
                "u.id,u.username,u.role,u.enabled FROM sessions s"
                " JOIN users u ON s.user_id=u.id WHERE s.token_hash=?",
                (_digest(session),),
            ).fetchone()
            if not row or row[3] or not row[7] or (
                now - row[1] >= self.absolute_timeout_s or
                now - row[2] >= self.idle_timeout_s or now < row[1] - 10
            ):
                db.commit()
                raise AuthenticationError("Session invalid or expired")
            if mutation and (not isinstance(csrf, str) or
                             not hmac.compare_digest(row[0], _digest(csrf))):
                self._audit(db, Actor(row[4], row[5], Role(row[6])),
                            "csrf", "DENIED")
                db.commit()
                raise AuthorizationError("CSRF token required")
            # Sliding idle timeout; absolute expiry remains anchored.
            db.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?",
                       (now, _digest(session)))
            db.commit()
            return Actor(row[4], row[5], Role(row[6]))
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def logout(self, session: str | None) -> None:
        if not isinstance(session, str) or not 20 <= len(session) <= 128:
            return
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT u.id,u.username,u.role FROM sessions s JOIN users u"
                " ON u.id=s.user_id WHERE s.token_hash=?", (_digest(session),)
            ).fetchone()
            db.execute("UPDATE sessions SET revoked=1 WHERE token_hash=?",
                       (_digest(session),))
            self._audit(db, Actor(row[0], row[1], Role(row[2])) if row else None,
                        "logout", "SUCCESS")
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def create_user(self, admin_session: str, csrf: str, username: str,
                    password: str, role: Role) -> None:
        admin = self.authenticate(admin_session, csrf=csrf, mutation=True)
        if admin.role is not Role.ADMIN:
            self.audit(admin, "user.create", "DENIED")
            raise AuthorizationError("Administrator required")
        self._validate_username(username)
        pw = _hash_password(_password_bytes(password))
        if not isinstance(role, Role):
            raise ValueError("Invalid role")
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO users(username,password_hash,role) VALUES(?,?,?)",
                       (username, pw, role.value))
            self._audit(db, admin, "user.create", "SUCCESS", detail=username)
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def change_role(self, admin_session: str, csrf: str, username: str,
                    role: Role) -> None:
        admin = self.authenticate(admin_session, csrf=csrf, mutation=True)
        if admin.role is not Role.ADMIN:
            self.audit(admin, "user.role", "DENIED")
            raise AuthorizationError("Administrator required")
        if not isinstance(role, Role):
            raise ValueError("Invalid role")
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id,role FROM users WHERE username=? AND enabled=1",
                             (username,)).fetchone()
            if row is None:
                raise ValueError("No active user")
            if row[0] == admin.user_id and role is not Role.ADMIN:
                raise AuthorizationError("Cannot remove own administrator authority")
            db.execute("UPDATE users SET role=? WHERE id=?", (role.value, row[0]))
            db.execute("UPDATE sessions SET revoked=1 WHERE user_id=?", (row[0],))
            self._audit(db, admin, "user.role", "SUCCESS", detail=username)
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def disable_user(self, admin_session: str, csrf: str, username: str) -> None:
        admin = self.authenticate(admin_session, csrf=csrf, mutation=True)
        if admin.role is not Role.ADMIN:
            self.audit(admin, "user.disable", "DENIED")
            raise AuthorizationError("Administrator required")
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
            if not row or row[0] == admin.user_id:
                raise AuthorizationError("Cannot disable missing or own account")
            db.execute("UPDATE users SET enabled=0 WHERE id=?", (row[0],))
            db.execute("UPDATE sessions SET revoked=1 WHERE user_id=?", (row[0],))
            self._audit(db, admin, "user.disable", "SUCCESS", detail=username)
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def audit_records(self) -> list[tuple]:
        """Local review tool; never register as a public endpoint."""
        db = self._db()
        try:
            return db.execute("SELECT action,outcome,chamber_id,username,detail"
                              " FROM audit ORDER BY sequence").fetchall()
        finally:
            db.close()
