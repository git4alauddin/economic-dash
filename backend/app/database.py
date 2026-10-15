"""Private SQLite bootstrap and short-lived connections, without domain tables.

M4.2 owns ordered transactional migrations using PRAGMA user_version (currently 0).
Run bootstrap at service startup or with `python -m app.database`, never at build
time: Render disks are runtime-only. M7 must verify the /var/data mount survives
redeploys, one instance/worker, service-user permissions and no HTTP file serving.
SQLite opens no network listener. Windows uses inherited directory ACLs; M7 must
check the Linux runtime's 0700 directory/0600 database and sidecars independently.
"""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
from typing import Iterator

from app.config import DatabaseSettings, get_database_settings, get_settings

SCHEMA_VERSION = 0  # Domain DDL and forward-only migrations begin in M4.2.


class Database:
    """No shared connection or pool; create/use/close within the calling thread."""

    def __init__(self, settings: DatabaseSettings):
        self.settings = settings

    def _check_files(self) -> None:
        for suffix in ("", "-wal", "-shm", "-journal"):
            path = Path(str(self.settings.path) + suffix)
            if path.is_symlink() or (path.exists() and not path.is_file()):
                raise RuntimeError("Database and sidecars must be regular private files.")

    def bootstrap(self) -> None:
        """Repeatable, fail-closed setup; no observation writes or fake seed data."""
        if self.settings.app_env == "production":
            if os.name != "posix" or not os.path.ismount("/var/data"):
                raise RuntimeError("Production requires a persistent disk mounted at /var/data.")
        directory = self.settings.directory
        assert directory is not None
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._check_files()
        if os.name == "posix":
            directory.chmod(0o700)
        try:
            descriptor = os.open(self.settings.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
        if os.name == "posix":
            for suffix in ("", "-wal", "-shm", "-journal"):
                path = Path(str(self.settings.path) + suffix)
                if path.exists():
                    path.chmod(0o600)
        with self.connection() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version != SCHEMA_VERSION:
                raise RuntimeError("Unsupported database schema version; migration is required.")
            mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if mode != "wal":
                raise RuntimeError("Database must support WAL on a local persistent disk.")
            if [row[0] for row in connection.execute("PRAGMA quick_check")] != ["ok"]:
                raise RuntimeError("Database integrity check failed.")

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Open an existing file only; close and roll back any unfinished work."""
        self._check_files()
        connection = sqlite3.connect(
            self.settings.path.as_uri() + "?mode=rw", uri=True,
            timeout=self.settings.busy_timeout, autocommit=True,
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA trusted_schema=OFF")
            if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
                raise RuntimeError("SQLite foreign-key enforcement is required.")
            yield connection
        finally:
            try:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
            finally:
                connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Bounded writer wait; commit only a fully successful explicit transaction."""
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.execute("COMMIT")


def main() -> None:
    database = Database(get_database_settings(get_settings().app_env))
    database.bootstrap()
    print(json.dumps({"result": "ready", "engine": "sqlite", "schema_version": SCHEMA_VERSION}))


if __name__ == "__main__":
    main()
