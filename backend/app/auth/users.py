"""Parameterized private identity storage; public identities contain no hash."""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from app.database import Database
from .passwords import hash_password, needs_rehash, normalize_username, validate_new_password, verify_password


class AccountConflict(ValueError):
    pass


@dataclass(frozen=True)
class Identity:
    user_id: str
    username: str
    is_active: bool
    credential_version: int


@dataclass(frozen=True)
class ProvisionResult:
    identity: Identity
    action: str  # created, unchanged, password_reset, hash_upgraded


def identity(row) -> Identity:
    return Identity(row["user_id"], row["username"], bool(row["is_active"]), row["credential_version"])


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class UserStore:
    def __init__(self, database: Database):
        self.database = database

    def _record(self, name):
        with self.database.connection(read_only=True) as connection:
            return connection.execute("SELECT * FROM auth_users WHERE username=?", (name,)).fetchone()

    def get(self, user_id: str) -> Identity | None:
        with self.database.connection(read_only=True) as connection:
            row = connection.execute("SELECT user_id,username,is_active,credential_version FROM auth_users WHERE user_id=?", (user_id,)).fetchone()
        return identity(row) if row else None

    def provision(self, username: str, password: str, *, reset_password: bool = False) -> ProvisionResult:
        name = normalize_username(username)
        validate_new_password(password)
        previous = self._record(name)
        matched = previous is not None and verify_password(previous["password_hash"], password)
        if previous is not None and not matched and not reset_password:
            raise AccountConflict("Account exists; use --reset-password for an intentional password change.")
        if previous is None and reset_password:
            raise AccountConflict("Account does not exist; provision it before resetting its password.")
        if matched and not needs_rehash(previous["password_hash"]):
            return ProvisionResult(identity(previous), "unchanged")
        encoded = hash_password(password)  # Expensive work stays outside the SQL write lock.
        now = timestamp()
        with self.database.transaction() as connection:
            if previous is None:
                uid = uuid4().hex
                cursor = connection.execute("""INSERT INTO auth_users(user_id,username,password_hash,created_at,updated_at)
                    VALUES (?,?,?,?,?) ON CONFLICT(username) DO NOTHING""", (uid, name, encoded, now, now))
                action = "created"
            else:
                uid = previous["user_id"]
                cursor = connection.execute("""UPDATE auth_users SET password_hash=?,updated_at=?,credential_version=credential_version+?
                    WHERE user_id=? AND password_hash=? AND credential_version=? AND is_active=?""",
                    (encoded, now, int(not matched), uid, previous["password_hash"], previous["credential_version"], previous["is_active"]))
                action = "hash_upgraded" if matched else "password_reset"
            if cursor.rowcount != 1:
                raise AccountConflict("Account changed concurrently; retry the operation.")
            row = connection.execute("SELECT * FROM auth_users WHERE user_id=?", (uid,)).fetchone()
        return ProvisionResult(identity(row), action)

    def set_active(self, username: str, active: bool) -> Identity:
        if type(active) is not bool:
            raise ValueError("Account status must be boolean.")
        name = normalize_username(username)
        with self.database.transaction() as connection:
            connection.execute("""UPDATE auth_users SET is_active=?,updated_at=?,credential_version=credential_version+1
                WHERE username=? AND is_active!=?""", (int(active), timestamp(), name, int(active)))
            row = connection.execute("SELECT * FROM auth_users WHERE username=?", (name,)).fetchone()
            if row is None:
                raise AccountConflict("Account does not exist.")
        return identity(row)

    def authenticate(self, username: str, password: str) -> Identity | None:
        try:
            name = normalize_username(username)
        except ValueError:
            verify_password(None, password)  # Same bounded password work for an unknown identity.
            return None
        row = self._record(name)
        encoded = row["password_hash"] if row is not None and row["is_active"] else None
        if not verify_password(encoded, password) or row is None or not row["is_active"]:
            return None
        if needs_rehash(encoded):
            upgraded = hash_password(password)
            with self.database.transaction() as connection:
                cursor = connection.execute("""UPDATE auth_users SET password_hash=?,updated_at=?
                    WHERE user_id=? AND password_hash=? AND credential_version=? AND is_active=1""",
                    (upgraded, timestamp(), row["user_id"], encoded, row["credential_version"]))
                if cursor.rowcount != 1:
                    return None  # A concurrent disable/reset wins over a verified old password.
        current = self.get(row["user_id"])
        return current if current is not None and current.is_active and current.credential_version == row["credential_version"] else None
