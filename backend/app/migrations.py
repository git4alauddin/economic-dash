"""Ordered SQL migrations, checksum-locked and committed as one upgrade transaction."""

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import re
import sqlite3
from typing import Iterator

SCHEMA_VERSION = 2
SQL_DIRECTORY = Path(__file__).with_name("sql")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        # Git may check out CRLF on Windows; checksums must match Linux deployments.
        return sha256(self.sql.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def migration_plan() -> tuple[Migration, ...]:
    return (
        Migration(1, "initial", (SQL_DIRECTORY / "001_initial.sql").read_text(encoding="utf-8")),
        Migration(2, "auth_users", (SQL_DIRECTORY / "002_auth_users.sql").read_text(encoding="utf-8")),
    )


def statements(sql: str) -> Iterator[str]:
    """Use SQLite's parser boundary, preserving semicolons inside strings/triggers.

    execute(), unlike executescript(), never commits the caller's transaction.
    Migration files are reviewed application SQL, never request-supplied SQL.
    """
    pending = ""
    for character in sql:
        pending += character
        if character == ";" and sqlite3.complete_statement(pending):
            yield pending
            pending = ""
    if re.sub(r"--[^\n]*(?:\n|$)|/\*.*?\*/", "", pending, flags=re.DOTALL).strip():
        raise RuntimeError("Migration statements require a terminating semicolon.")


def migrate(connection: sqlite3.Connection) -> None:
    plan = migration_plan()
    if tuple(m.version for m in plan) != tuple(range(1, SCHEMA_VERSION + 1)):
        raise RuntimeError("Migration versions must be contiguous and match the application.")
    if sqlite3.sqlite_version_info < (3, 37, 0):
        raise RuntimeError("SQLite 3.37 or newer is required for STRICT tables.")
    connection.execute("BEGIN IMMEDIATE")
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if not 0 <= version <= SCHEMA_VERSION:
            raise RuntimeError("Unsupported database schema version; newer application is required.")
        if version and not connection.execute("SELECT 1 FROM sqlite_schema WHERE name = 'schema_migrations' AND type = 'table'").fetchone():
            raise RuntimeError("Database migration ledger is missing.")
        connection.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY CHECK(version > 0), name TEXT NOT NULL,
            checksum TEXT NOT NULL CHECK(length(checksum) = 64), applied_at TEXT NOT NULL
        ) STRICT""")
        applied = [tuple(row) for row in connection.execute("SELECT version, name, checksum FROM schema_migrations ORDER BY version")]
        expected = [(m.version, m.name, m.checksum) for m in plan[:version]]
        if applied != expected:
            raise RuntimeError("Migration ledger/checksum mismatch; applied migrations are immutable.")
        for migration in plan[version:]:
            for statement in statements(migration.sql):
                connection.execute(statement)
            connection.execute("INSERT INTO schema_migrations(version, name, checksum, applied_at) VALUES (?, ?, ?, ?)",
                               (migration.version, migration.name, migration.checksum,
                                datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")))
            # Only the internal, contiguous integer version is interpolated.
            connection.execute(f"PRAGMA user_version={migration.version}")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise RuntimeError("Database foreign-key integrity check failed.")
        connection.execute("COMMIT")
    except BaseException:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
