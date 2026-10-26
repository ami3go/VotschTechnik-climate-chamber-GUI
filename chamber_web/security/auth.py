"""Offline identities, one bounded session policy, durable audit.

No browser-supplied role is trusted. Factory credentials are one-time only.
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

from .account_ops import AccountOperations
from .audit_integrity import export_audit_csv


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
class UserAccount:
    """Non-secret account metadata safe for the administrator UI."""

    username: str
    role: Role
    enabled: bool


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
# Limit simultaneous memory-hard login hashing under malicious concurrency.
_LOGIN_KDF_SLOTS = threading.BoundedSemaphore(2)
_DUMMY_HASH = hashlib.scrypt(b"no-such-user-password", salt=_DUMMY_SALT,
                             n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32, maxmem=64 * 1024 * 1024)


def _password_bytes(password: str, *, min_bytes: int = 12) -> bytes:
    if not isinstance(password, str):
        raise ValueError("Invalid password type")
    raw = password.encode("utf-8")
    if not min_bytes <= len(raw) <= 1024:
        raise ValueError(f"Password must be {min_bytes}–1024 UTF-8 bytes")
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


class SecurityStore(AccountOperations):
    """Process- and thread-safe SQLite identity authority.

    Uses a fresh connection per transaction so concurrent browser clients, and
    multiple processes sharing this *local* database, cannot race bootstrap or
    session revocation. The clock injection is for deterministic unit tests.
    """

    def __init__(self, directory: Path | None = None, *,
                 clock: Callable[[], float] = time.time,
                 idle_timeout_s: int = 1800,
                 absolute_timeout_s: int = 28800,
                 password_min_bytes: int = 12,
                 lockout_attempts: int = 5,
                 lockout_seconds: int = 900,
                 client_attempts: int = 30):
        if idle_timeout_s <= 0 or absolute_timeout_s <= 0:
            raise ValueError("Session lifetimes must be positive")
        if not 12 <= password_min_bytes <= 128:
            raise ValueError("Password minimum must be 12–128 UTF-8 bytes")
        if not 3 <= lockout_attempts <= 20 or not 30 <= lockout_seconds <= 86400:
            raise ValueError("Invalid account lockout policy")
        if not 5 <= client_attempts <= 100:
            raise ValueError("Invalid client throttling policy")
        self.directory = Path(directory or (Path.home() / ".chamber_web" / "security"))
        self.directory.mkdir(parents=True, exist_ok=True)
        if __import__("os").name != "nt":
            self.directory.chmod(0o700)
        self.database = self.directory / "security.sqlite3"
        # An established deployment must never silently become a new,
        # unbootstrapped identity authority because its DB was removed.
        marker = self.directory / "identity.present"
        if not self.database.exists() and (
                marker.exists() or marker.is_symlink()):
            raise RuntimeError(
                "Existing security credentials found but database is missing; "
                "restore an approved backup"
            )
        # Create a new SQLite file private from its FIRST byte; chmod after
        # schema initialization alone leaves a credential disclosure window.
        if not self.database.exists():
            try:
                descriptor = __import__("os").open(
                    self.database, __import__("os").O_CREAT |
                    __import__("os").O_EXCL | __import__("os").O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                __import__("os").close(descriptor)
        if self.database.is_symlink():
            raise PermissionError("Security database cannot be a symlink")
        self.clock = clock
        self.idle_timeout_s = idle_timeout_s
        self.absolute_timeout_s = absolute_timeout_s
        self.password_min_bytes = password_min_bytes
        self.lockout_attempts = lockout_attempts
        self.lockout_seconds = lockout_seconds
        self.client_attempts = client_attempts
        self._lock = threading.RLock()
        db = self._db()
        try:
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
                CREATE TABLE IF NOT EXISTS login_clients (
                    client_hash TEXT PRIMARY KEY,
                    attempts INTEGER NOT NULL,
                    window_end REAL NOT NULL
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
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise RuntimeError("Unsupported security schema; restore an approved backup")
            if version == 0:
                db.execute("PRAGMA user_version=1")
        finally:
            db.close()
        if __import__("os").name != "nt":
            self.database.chmod(0o600)
        if not marker.exists():
            marker.write_text("1\n", encoding="ascii")

    @classmethod
    def from_environment(cls, directory: Path | None = None) -> "SecurityStore":
        """Single validated offline policy for interactive CLI and NiceGUI.

        Never apply arbitrary browser-supplied security-policy values.
        Invalid values are startup errors, not silently ignored defaults.
        """
        import os

        def number(name: str, default: int) -> int:
            raw = os.environ.get(name, str(default))
            try:
                return int(raw)
            except ValueError as exc:
                raise ValueError("Invalid security configuration: " + name) from exc

        return cls(
            directory,
            idle_timeout_s=number("CHAMBER_SESSION_IDLE_SECONDS", 1800),
            absolute_timeout_s=number("CHAMBER_SESSION_ABSOLUTE_SECONDS", 28800),
            password_min_bytes=number("CHAMBER_PASSWORD_MIN_BYTES", 12),
            lockout_attempts=number("CHAMBER_LOGIN_LOCKOUT_ATTEMPTS", 5),
            lockout_seconds=number("CHAMBER_LOGIN_LOCKOUT_SECONDS", 900),
            client_attempts=number("CHAMBER_LOGIN_PEER_ATTEMPTS", 30),
        )

    def _session_expired(self, db: sqlite3.Connection, created: float,
                         last_seen: float, now: float) -> bool:
        # A backwards clock jump is invalid. Idle and absolute limits are
        # identical for every deployment; there are no selectable profiles.
        return (now < created - 10
                or now - last_seen >= self.idle_timeout_s
                or now - created >= self.absolute_timeout_s)

    def _confirm_admin_password(self, admin: Actor, password: str) -> str:
        """Verify the current password before sensitive identity changes."""
        db = self._db()
        try:
            row = db.execute("SELECT password_hash FROM users WHERE id=? AND enabled=1",
                             (admin.user_id,)).fetchone()
        finally:
            db.close()
        if not _LOGIN_KDF_SLOTS.acquire(timeout=5):
            raise AuthorizationError("Administrator password verification unavailable")
        try:
            verified = _verify_password(password, row[0] if row else None)
        finally:
            _LOGIN_KDF_SLOTS.release()
        if not verified:
            self.audit(admin, "security.reauthenticate", "DENIED")
            raise AuthorizationError("Current administrator password required")
        return row[0]

    def reauthenticate_admin(self, admin_session: str | None, csrf: str | None,
                             admin_password: str) -> Actor:
        """Current administrator session plus fresh password for sensitive changes."""
        admin = self.authenticate(admin_session, csrf=csrf, mutation=True)
        if admin.role is not Role.ADMIN:
            raise AuthorizationError("Administrator required")
        self._confirm_admin_password(admin, admin_password)
        return admin

    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.database, timeout=10, isolation_level=None)
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _audit(self, db: sqlite3.Connection, actor: Actor | None, action: str,
               outcome: str, chamber_id: str | None = None, detail: str = "") -> None:
        # Avoid persisting bearer tokens and passwords accidentally supplied
        # by an integration caller as free-form diagnostic details.
        redacted = re.sub(
            r"(?i)(password|token|csrf|secret|authorization)\s*[:=]\s*[^\s,;]+",
            r"\1=[REDACTED]", str(detail),
        )
        db.execute(
            "INSERT INTO audit(at_utc,user_id,username,role,action,outcome,chamber_id,detail)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (self.clock(), actor.user_id if actor else None,
             actor.username if actor else None, actor.role.value if actor else None,
             action[:80], outcome[:40], chamber_id, redacted[:300]),
        )

    def audit(self, actor: Actor | None, action: str, outcome: str,
              chamber_id: str | None = None, detail: str = "") -> None:
        # Audit insertion failure is never silently downgraded to success.
        db = self._db()
        try:
            with db:
                self._audit(db, actor, action, outcome, chamber_id, detail)
        finally:
            db.close()

    def is_bootstrapped(self) -> bool:
        db = self._db()
        try:
            return db.execute("SELECT 1 FROM bootstrap WHERE id=1").fetchone() is not None
        finally:
            db.close()


    def provision_factory_admin(self) -> bool:
        """One-time server startup provision: never reset an existing identity.

        The intentionally weak factory password is an exception ONLY here:
        normal password creation/changes retain the configured 12+ byte policy.
        This is not exposed over HTTP.
        """
        password_hash = _hash_password(b"admin")
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM bootstrap WHERE id=1").fetchone():
                db.commit()
                return False
            if db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                raise RuntimeError("Unprovisioned database has accounts; refusing factory reset")
            cursor = db.execute(
                "INSERT INTO users(username,password_hash,role) VALUES(?,?,?)",
                ("admin", password_hash, Role.ADMIN.value),
            )
            db.execute("INSERT INTO bootstrap(id,completed_at) VALUES(1,?)",
                       (self.clock(),))
            self._audit(db, Actor(cursor.lastrowid, "admin", Role.ADMIN),
                        "bootstrap.factory", "SUCCESS")
            db.commit()
            return True
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def factory_credentials_active(self) -> bool:
        """Recognize the factory password even after an administrator rename."""
        db = self._db()
        try:
            credentials = db.execute(
                "SELECT password_hash FROM users WHERE role='ADMIN' AND enabled=1"
            ).fetchall()
        finally:
            db.close()
        return any(_verify_password("admin", row[0]) for row in credentials)

    def bootstrap_admin(self, username: str, password: str) -> None:
        """Trusted LOCAL CLI only; atomic one-time initialization, never an HTTP route."""
        self._validate_username(username)
        encoded = _password_bytes(password, min_bytes=self.password_min_bytes)
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

    def login(self, username: str, password: str, *,
              client_id: str | None = None) -> SessionTokens:
        now = self.clock()
        if not isinstance(username, str) or len(username) > 64:
            raise AuthenticationError("Invalid username or password")
        # Client addresses are trusted only when supplied by the ASGI peer,
        # never X-Forwarded-For or a value supplied by a browser.
        client_hash = (_digest(client_id) if isinstance(client_id, str)
                       and 1 <= len(client_id) <= 128 else None)

        # Expensive scrypt occurs outside the SQLite write transaction. Login
        # traffic must not hold the audit/STOP intent database lock.
        db = self._db()
        try:
            if client_hash is not None:
                attempts = db.execute(
                    "SELECT attempts,window_end FROM login_clients"
                    " WHERE client_hash=?", (client_hash,),
                ).fetchone()
                if attempts and attempts[0] >= self.client_attempts and attempts[1] > now:
                    raise AuthenticationError("Invalid username or password")
            candidate = db.execute(
                "SELECT id,username,password_hash,enabled FROM users WHERE username=?",
                (username,),
            ).fetchone()
            if not _LOGIN_KDF_SLOTS.acquire(timeout=5):
                raise AuthenticationError("Invalid username or password")
            try:
                valid = _verify_password(
                    password, candidate[2] if candidate else None)
            finally:
                _LOGIN_KDF_SLOTS.release()
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
                locked = bool(fail and fail[0] >= self.lockout_attempts and fail[1] > now)
                # A pre-KDF peer check is only an optimization. Recheck while
                # holding SQLite write serialization to close concurrent
                # brute-force attempts racing the threshold.
                peer_fail = db.execute(
                    "SELECT attempts,window_end FROM login_clients"
                    " WHERE client_hash=?", (client_hash,),
                ).fetchone() if client_hash is not None else None
                peer_locked = bool(
                    peer_fail and peer_fail[0] >= self.client_attempts
                    and peer_fail[1] > now)
                current = bool(candidate and row
                               and candidate[2] == row[2]
                               and candidate[0] == row[0] and row[3])
                if locked or peer_locked or not valid or not current:
                    attempts = fail[0] if locked else (
                        fail[0] + 1 if fail and fail[1] > now else 1)
                    # Attempts during lockout may not prolong the lockout.
                    until = fail[1] if locked else now + self.lockout_seconds
                    # Unknown usernames do not create unbounded SQL rows;
                    # the peer rate limiter still counts their failed login.
                    if row is not None:
                        db.execute(
                            "INSERT INTO login_failures(username,attempts,lock_until)"
                            " VALUES(?,?,?) ON CONFLICT(username)"
                            " DO UPDATE SET attempts=excluded.attempts,"
                            " lock_until=excluded.lock_until",
                            (username, attempts, until),
                        )
                    if client_hash is not None:
                        row_client = db.execute(
                            "SELECT attempts,window_end FROM login_clients"
                            " WHERE client_hash=?", (client_hash,),
                        ).fetchone()
                        count = (row_client[0] if peer_locked else
                                 row_client[0] + 1 if row_client and
                                 row_client[1] > now else 1)
                        db.execute(
                            "INSERT INTO login_clients(client_hash,attempts,window_end)"
                            " VALUES(?,?,?) ON CONFLICT(client_hash)"
                            " DO UPDATE SET attempts=excluded.attempts,"
                            " window_end=excluded.window_end",
                            (client_hash, count,
                             row_client[1] if peer_locked else
                             now + self.lockout_seconds),
                        )
                        # Bound retained client throttles even if a malicious
                        # client rotates source IPs (notably IPv6 privacy IPs).
                        db.execute("DELETE FROM login_clients WHERE window_end<=?",
                                   (now,))
                        total = db.execute(
                            "SELECT count(*) FROM login_clients").fetchone()[0]
                        if total > 4096:
                            db.execute("DELETE FROM login_clients WHERE client_hash IN"
                                       " (SELECT client_hash FROM login_clients"
                                       " ORDER BY window_end LIMIT ?)",
                                       (total - 4096,))
                    self._audit(db, None, "login", "DENIED",
                                detail="invalid credentials or lockout")
                    db.commit()
                    raise AuthenticationError("Invalid username or password")
                db.execute("DELETE FROM login_failures WHERE username=?", (username,))
                if client_hash is not None:
                    db.execute("DELETE FROM login_clients WHERE client_hash=?",
                               (client_hash,))
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
                     mutation: bool = False, touch: bool = True) -> Actor:
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
                self._session_expired(db, row[1], row[2], now)
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
            if touch or mutation:
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

    def _require_current_admin(self, db: sqlite3.Connection, session: str,
                               actor: Actor) -> None:
        """Recheck role and session inside the mutation's write transaction.

        Pre-transaction authenticate() can race with another administrator's
        role change, account disable, session logout, or session expiry.
        """
        row = db.execute(
            "SELECT u.id,u.enabled,u.role,s.revoked,s.created_at,s.last_seen"
            " FROM sessions s JOIN users u ON s.user_id=u.id"
            " WHERE s.token_hash=?", (_digest(session),),
        ).fetchone()
        now = self.clock()
        if (row is None or row[0] != actor.user_id or not row[1] or
                row[2] != Role.ADMIN.value or row[3] or
                self._session_expired(db, row[4], row[5], now)):
            raise AuthorizationError("Administrator session no longer authorized")

    def create_user(self, admin_session: str, csrf: str, username: str,
                    password: str, role: Role) -> None:
        admin = self.authenticate(admin_session, csrf=csrf, mutation=True)
        if admin.role is not Role.ADMIN:
            self.audit(admin, "user.create", "DENIED")
            raise AuthorizationError("Administrator required")
        self._validate_username(username)
        pw = _hash_password(_password_bytes(password, min_bytes=self.password_min_bytes))
        if not isinstance(role, Role):
            raise ValueError("Invalid role")
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            self._require_current_admin(db, admin_session, admin)
            db.execute("INSERT INTO users(username,password_hash,role) VALUES(?,?,?)",
                       (username, pw, role.value))
            self._audit(db, admin, "user.create", "SUCCESS", detail=username)
            db.commit()
        except BaseException as exc:
            db.rollback()
            # The denied audit must survive rollback of the rejected mutation.
            if isinstance(exc, AuthorizationError):
                self.audit(admin, "user.admin", "DENIED",
                           detail="stale or unauthorized administrator")
            raise
        finally:
            db.close()

    def list_users(self, admin_session: str) -> tuple[UserAccount, ...]:
        """Return non-secret account metadata to a current administrator."""
        admin = self.authenticate(admin_session)
        if admin.role is not Role.ADMIN:
            self.audit(admin, "user.list", "DENIED")
            raise AuthorizationError("Administrator required")
        db = self._db()
        try:
            rows = db.execute(
                "SELECT username,role,enabled FROM users "
                "ORDER BY lower(username),id"
            ).fetchall()
        finally:
            db.close()
        return tuple(UserAccount(
            username=row[0], role=Role(row[1]), enabled=bool(row[2])
        ) for row in rows)

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
            self._require_current_admin(db, admin_session, admin)
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
        except BaseException as exc:
            db.rollback()
            # The denied audit must survive rollback of the rejected mutation.
            if isinstance(exc, AuthorizationError):
                self.audit(admin, "user.admin", "DENIED",
                           detail="stale or unauthorized administrator")
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
            self._require_current_admin(db, admin_session, admin)
            row = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
            if not row or row[0] == admin.user_id:
                raise AuthorizationError("Cannot disable missing or own account")
            db.execute("UPDATE users SET enabled=0 WHERE id=?", (row[0],))
            db.execute("UPDATE sessions SET revoked=1 WHERE user_id=?", (row[0],))
            self._audit(db, admin, "user.disable", "SUCCESS", detail=username)
            db.commit()
        except BaseException as exc:
            db.rollback()
            # The denied audit must survive rollback of the rejected mutation.
            if isinstance(exc, AuthorizationError):
                self.audit(admin, "user.admin", "DENIED",
                           detail="stale or unauthorized administrator")
            raise
        finally:
            db.close()

    def export_audit(self, destination: Path | str) -> tuple[Path, str]:
        """Append-only CSV snapshot for daily offline retention."""
        return export_audit_csv(self.database, Path(destination))

    def audit_records(self) -> list[tuple]:
        """Local review tool; never register as a public endpoint."""
        db = self._db()
        try:
            return db.execute("SELECT action,outcome,chamber_id,username,detail"
                              " FROM audit ORDER BY sequence").fetchall()
        finally:
            db.close()
