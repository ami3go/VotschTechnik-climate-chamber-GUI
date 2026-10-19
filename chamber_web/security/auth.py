"""Offline identities, selectable session security policy, durable audit.

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
from .audit_integrity import AuditLedger


class AuthenticationError(Exception):
    """Anonymous, expired, revoked, or invalid credentials."""


class AuthorizationError(Exception):
    """Authenticated principal lacks a required permission."""


class SecurityProfile(str, Enum):
    GENERAL = "general"
    ISOLATED_LAN = "isolated_lan"
    LARGE_NETWORK = "large_network"


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
                 client_attempts: int = 30,
                 audit_max_rows: int = 10000):
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
        # The audit/backup keys are independent local persistence markers.
        # Loss of both DB and keys still needs external inventory/ACL controls.
        if not self.database.exists() and any(
            (self.directory / key).exists()
            or (self.directory / key).is_symlink()
            for key in ("audit_hmac_key", "backup_signing_key")
        ):
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
        self._audit_ledger = AuditLedger(self.directory, max_rows=audit_max_rows)
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
                CREATE TABLE IF NOT EXISTS security_policy (
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    profile TEXT NOT NULL CHECK(
                        profile IN ('general','isolated_lan','large_network'))
                );
                CREATE TABLE IF NOT EXISTS login_failures (
                    username TEXT PRIMARY KEY COLLATE NOCASE,
                    attempts INTEGER NOT NULL,
                    lock_until REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS recovery_tokens (
                    token_hash TEXT PRIMARY KEY,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    issued_by INTEGER NOT NULL REFERENCES users(id)
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
            # Add a separate salted PIN verifier without modifying legacy password hashes.
            columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
            if "pin_hash" not in columns:
                try:
                    db.execute("ALTER TABLE users ADD COLUMN pin_hash TEXT")
                except sqlite3.OperationalError as exc:
                    # A concurrent first initializer added it between the
                    # table_info check and this ALTER; the schema is correct.
                    if "duplicate column name: pin_hash" not in str(exc):
                        raise
            db.execute("INSERT OR IGNORE INTO security_policy(id,profile)"
                       " VALUES(1,'general')")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise RuntimeError("Unsupported security schema; restore an approved backup")
            self._audit_ledger.initialize(db)
            if version == 0:
                db.execute("PRAGMA user_version=1")
        finally:
            db.close()
        if __import__("os").name != "nt":
            self.database.chmod(0o600)

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
            audit_max_rows=number("CHAMBER_AUDIT_MAX_ROWS", 10000),
        )

    @staticmethod
    def _profile_in(db: sqlite3.Connection) -> SecurityProfile:
        row = db.execute("SELECT profile FROM security_policy WHERE id=1").fetchone()
        try:
            return SecurityProfile(row[0] if row is not None else "")
        except ValueError as exc:
            raise RuntimeError("Security profile invalid; startup/operation refused") from exc

    def get_security_profile(self) -> SecurityProfile:
        """Read the authoritative database setting, not browser or environment input."""
        db = self._db()
        try:
            return self._profile_in(db)
        finally:
            db.close()

    def _session_expired(self, db: sqlite3.Connection, created: float,
                         last_seen: float, now: float) -> bool:
        # A backwards clock jump remains invalid in every mode. The isolated
        # workstation mode has NO idle or absolute server-side timeout.
        if now < created - 10:
            return True
        profile = self._profile_in(db)
        if profile is SecurityProfile.ISOLATED_LAN:
            return False
        idle, absolute = ((3600, 43200) if profile is SecurityProfile.LARGE_NETWORK
                          else (self.idle_timeout_s, self.absolute_timeout_s))
        return now - last_seen >= idle or now - created >= absolute

    @staticmethod
    def _validate_pin(pin: str) -> bytes:
        if not isinstance(pin, str) or re.fullmatch(r"[0-9]{6,12}", pin) is None:
            raise ValueError("PIN must contain 6–12 ASCII digits")
        return pin.encode("ascii")

    def _confirm_admin_password(self, admin: Actor, password: str) -> str:
        """Verify primary password before allowing weaker profile or PIN enrollment."""
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

    def configure_user_pin(self, admin_session: str, csrf: str,
                           admin_password: str, username: str, pin: str) -> None:
        """Explicit administrator-only enrollment of one account's hashed PIN."""
        admin = self.authenticate(admin_session, csrf=csrf, mutation=True)
        if admin.role is not Role.ADMIN:
            raise AuthorizationError("Administrator required")
        self._validate_username(username)
        pin_hash = _hash_password(self._validate_pin(pin))
        confirmed_hash = self._confirm_admin_password(admin, admin_password)
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            self._require_current_admin(db, admin_session, admin)
            current = db.execute("SELECT password_hash FROM users WHERE id=?",
                                 (admin.user_id,)).fetchone()
            if current is None or current[0] != confirmed_hash:
                raise AuthorizationError("Administrator credentials changed")
            target = db.execute("SELECT id FROM users WHERE username=? AND enabled=1",
                                (username,)).fetchone()
            if target is None:
                raise ValueError("No enabled account with that username")
            db.execute("UPDATE users SET pin_hash=? WHERE id=?", (pin_hash, target[0]))
            db.execute("UPDATE sessions SET revoked=1 WHERE user_id=?", (target[0],))
            self._audit(db, admin, "security.pin.set", "SUCCESS", detail=username)
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def set_security_profile(self, admin_session: str, csrf: str,
                             admin_password: str, profile: SecurityProfile) -> None:
        """Persist an explicit mode change; revoke sessions for immediate re-login."""
        if not isinstance(profile, SecurityProfile):
            raise ValueError("Invalid security profile")
        admin = self.authenticate(admin_session, csrf=csrf, mutation=True)
        if admin.role is not Role.ADMIN:
            raise AuthorizationError("Administrator required")
        confirmed_hash = self._confirm_admin_password(admin, admin_password)
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            self._require_current_admin(db, admin_session, admin)
            current = db.execute("SELECT password_hash FROM users WHERE id=?",
                                 (admin.user_id,)).fetchone()
            if current is None or current[0] != confirmed_hash:
                raise AuthorizationError("Administrator credentials changed")
            if profile is SecurityProfile.LARGE_NETWORK and _verify_password(
                    "admin", current[0]):
                raise AuthorizationError(
                    "Change factory administrator password before Large Network mode")
            if profile is SecurityProfile.ISOLATED_LAN:
                # Never lock out every administrator when PIN-only login is enabled.
                enrolled = db.execute(
                    "SELECT 1 FROM users WHERE role='ADMIN' AND enabled=1"
                    " AND pin_hash IS NOT NULL LIMIT 1").fetchone()
                if enrolled is None:
                    raise AuthorizationError("Enroll an administrator PIN first")
            old_profile = self._profile_in(db)
            db.execute("UPDATE security_policy SET profile=? WHERE id=1",
                       (profile.value,))
            db.execute("UPDATE sessions SET revoked=1")
            self._audit(db, admin, "security.profile.change", "SUCCESS",
                        detail=f"{old_profile.value} -> {profile.value}")
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

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
        cursor = db.execute(
            "INSERT INTO audit(at_utc,user_id,username,role,action,outcome,chamber_id,detail)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (self.clock(), actor.user_id if actor else None,
             actor.username if actor else None, actor.role.value if actor else None,
             action[:80], outcome[:40], chamber_id, redacted[:300]),
        )
        self._audit_ledger.append(db, cursor.lastrowid)

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
        This is not exposed over HTTP and does not change the security profile.
        """
        password_hash = _hash_password(b"admin")
        pin_hash = _hash_password(self._validate_pin("12345678"))
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM bootstrap WHERE id=1").fetchone():
                db.commit()
                return False
            if db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                raise RuntimeError("Unprovisioned database has accounts; refusing factory reset")
            cursor = db.execute(
                "INSERT INTO users(username,password_hash,role,pin_hash)"
                " VALUES(?,?,?,?)",
                ("admin", password_hash, Role.ADMIN.value, pin_hash),
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

    def factory_credentials_active(self) -> tuple[bool, bool]:
        """Recognize factory password/PIN even after an account rename."""
        db = self._db()
        try:
            credentials = db.execute(
                "SELECT password_hash,pin_hash FROM users"
                " WHERE role='ADMIN' AND enabled=1"
            ).fetchall()
        finally:
            db.close()
        weak_password = any(_verify_password("admin", row[0]) for row in credentials)
        weak_pin = any(_verify_password("12345678", row[1]) for row in credentials
                       if row[1] is not None)
        return weak_password, weak_pin

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
              client_id: str | None = None, use_pin: bool = False,
              offline_primary_password: bool = False) -> SessionTokens:
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
            profile_at_start = self._profile_in(db)
            # Explicit trusted local CLI recovery may verify the stronger
            # primary password even while the GUI requires PIN-only login.
            # The NiceGUI browser handler never supplies this override.
            if offline_primary_password and use_pin:
                raise AuthenticationError("Invalid offline recovery authentication mode")
            if (not offline_primary_password and
                    use_pin != (profile_at_start is SecurityProfile.ISOLATED_LAN)):
                raise AuthenticationError("Invalid credentials for current security profile")
            if client_hash is not None:
                attempts = db.execute(
                    "SELECT attempts,window_end FROM login_clients"
                    " WHERE client_hash=?", (client_hash,),
                ).fetchone()
                if attempts and attempts[0] >= self.client_attempts and attempts[1] > now:
                    raise AuthenticationError("Invalid username or password")
            candidate = db.execute(
                "SELECT id,username,password_hash,enabled,pin_hash FROM users WHERE username=?",
                (username,),
            ).fetchone()
            if not _LOGIN_KDF_SLOTS.acquire(timeout=5):
                raise AuthenticationError("Invalid username or password")
            try:
                valid = _verify_password(
                    password, candidate[4 if use_pin else 2] if candidate else None)
                if use_pin and (not isinstance(password, str) or
                                re.fullmatch(r"[0-9]{6,12}", password) is None):
                    valid = False
            finally:
                _LOGIN_KDF_SLOTS.release()
            with self._lock:
                db.execute("BEGIN IMMEDIATE")
                # Re-read after locking: account may have been disabled, or
                # password changed, while the hash was being computed.
                row = db.execute(
                    "SELECT id,username,password_hash,enabled,role,pin_hash FROM users"
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
                current = bool(candidate and row and candidate[2] == row[2]
                               and candidate[4] == row[5] and
                               candidate[0] == row[0] and row[3] and
                               self._profile_in(db) is profile_at_start)
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

    def verify_audit_integrity(self) -> int:
        """Verify local HMAC chain; fail closed on missing or modified rows."""
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            result = self._audit_ledger.verify(db)
            db.commit()
            return result
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
