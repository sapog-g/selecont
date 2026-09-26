"""Password credentials, rate limits and opaque server-side sessions."""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import sqlite3
import time
from secrets import token_urlsafe

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError


_PASSWORDS = PasswordHasher()
_DUMMY_PASSWORD_HASH = _PASSWORDS.hash("invalid-account-password")


class AuthenticationFailed(Exception):
    """Use one public error for unknown users and incorrect passwords."""


class CredentialExists(Exception):
    pass


class RateLimited(Exception):
    def __init__(self, retry_after):
        self.retry_after = max(1, int(retry_after))
        super().__init__("Too many sign-in attempts")


@dataclass(frozen=True)
class Session:
    user_id: str
    handle: str
    expires_at: int


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AuthStore:
    """One short-lived instance per request or operator command."""

    def __init__(
        self,
        path,
        *,
        now=None,
        session_ttl=8 * 60 * 60,
        failure_limit=5,
        failure_window=15 * 60,
        block_seconds=5 * 60,
    ):
        self.db = sqlite3.connect(path, isolation_level=None, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.now = now or (lambda: int(time.time()))
        self.session_ttl = session_ttl
        self.failure_limit = failure_limit
        self.failure_window = failure_window
        self.block_seconds = block_seconds
        self.passwords = _PASSWORDS

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @contextmanager
    def _transaction(self, *, write=False):
        self.db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def set_password(self, user_id, password, *, replace=False):
        if not isinstance(password, str) or not 12 <= len(password) <= 256:
            raise ValueError("Password must contain 12 to 256 characters")
        password_hash = self.passwords.hash(password)
        with self._transaction(write=True):
            if self.db.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone() is None:
                raise ValueError("Unknown user")
            exists = self.db.execute(
                "SELECT 1 FROM credentials WHERE user_id = ?", (user_id,)
            ).fetchone()
            if exists and not replace:
                raise CredentialExists()
            self.db.execute(
                "INSERT INTO credentials(user_id, password_hash, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET password_hash = excluded.password_hash, "
                "updated_at = excluded.updated_at",
                (user_id, password_hash, self.now()),
            )
            if replace:
                self.db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    def _bucket_hashes(self, handle, client_key):
        # Both buckets matter: one prevents username rotation from bypassing the
        # client limit, the other slows distributed guesses for one account.
        return (
            _digest(f"client\0{client_key}"),
            _digest(f"account\0{handle}"),
        )

    def _check_rate_limit(self, buckets, now):
        placeholders = ",".join("?" for _ in buckets)
        row = self.db.execute(
            f"SELECT MAX(blocked_until) FROM login_attempts WHERE bucket_hash IN ({placeholders})",
            buckets,
        ).fetchone()
        blocked_until = row[0] or 0
        if blocked_until > now:
            raise RateLimited(blocked_until - now)

    def _record_failure(self, buckets, now):
        with self._transaction(write=True):
            for bucket in buckets:
                row = self.db.execute(
                    "SELECT failures, window_started_at FROM login_attempts WHERE bucket_hash = ?",
                    (bucket,),
                ).fetchone()
                if row is None or now - row["window_started_at"] >= self.failure_window:
                    failures, started = 1, now
                else:
                    failures, started = row["failures"] + 1, row["window_started_at"]
                blocked_until = now + self.block_seconds if failures >= self.failure_limit else 0
                self.db.execute(
                    "INSERT INTO login_attempts VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(bucket_hash) DO UPDATE SET failures = excluded.failures, "
                    "window_started_at = excluded.window_started_at, blocked_until = excluded.blocked_until",
                    (bucket, failures, started, blocked_until),
                )

    def authenticate(self, handle, password, client_key):
        handle = handle.strip().lower() if isinstance(handle, str) else ""
        password = password if isinstance(password, str) else ""
        now = self.now()
        buckets = self._bucket_hashes(handle, client_key)
        self._check_rate_limit(buckets, now)
        row = self.db.execute(
            "SELECT u.id, u.handle, c.password_hash FROM users u "
            "JOIN credentials c ON c.user_id = u.id WHERE u.handle = ?",
            (handle,),
        ).fetchone()
        usable_password = isinstance(password, str) and 1 <= len(password) <= 256
        encoded = row["password_hash"] if row and usable_password else _DUMMY_PASSWORD_HASH
        valid = False
        try:
            valid = self.passwords.verify(
                encoded, password if usable_password else "invalid-overlong-password"
            )
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            pass
        if not row or not usable_password or not valid:
            self._record_failure(buckets, now)
            raise AuthenticationFailed()

        token = token_urlsafe(32)
        expires = now + self.session_ttl
        with self._transaction(write=True):
            self.db.executemany("DELETE FROM login_attempts WHERE bucket_hash = ?", [(x,) for x in buckets])
            if self.passwords.check_needs_rehash(row["password_hash"]):
                self.db.execute(
                    "UPDATE credentials SET password_hash = ?, updated_at = ? WHERE user_id = ?",
                    (self.passwords.hash(password), now, row["id"]),
                )
            self.db.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?)",
                (_digest(token), row["id"], now, expires),
            )
            self.db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        return token

    def session(self, token):
        if not isinstance(token, str) or not token:
            return None
        now = self.now()
        row = self.db.execute(
            "SELECT s.user_id, u.handle, s.expires_at FROM sessions s "
            "JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?",
            (_digest(token),),
        ).fetchone()
        if row is None:
            return None
        if row["expires_at"] <= now:
            with self._transaction(write=True):
                self.db.execute("DELETE FROM sessions WHERE token_hash = ?", (_digest(token),))
            return None
        return Session(row["user_id"], row["handle"], row["expires_at"])

    def logout(self, token):
        if not isinstance(token, str) or not token:
            return
        with self._transaction(write=True):
            self.db.execute("DELETE FROM sessions WHERE token_hash = ?", (_digest(token),))
