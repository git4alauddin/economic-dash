"""Real SQLite lifecycle checks; test rows are never production seed data."""

import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import BACKEND_DIRECTORY, DatabaseSettings, SchedulerSettings, Settings
from app.database import Database
from app.migrations import SCHEMA_VERSION
from app.main import create_app


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        # Windows subprocess imports need SystemRoot for the socket provider.
        self.process_environment = os.environ.copy()
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name) / "private-db"
        self.settings = DatabaseSettings(_env_file=None, app_env="test", directory=self.directory, busy_timeout=0.05)
        self.database = Database(self.settings)

    def test_paths_defaults_environment_override_and_public_directory_rejection(self):
        self.assertEqual(DatabaseSettings(_env_file=None).path,
                         BACKEND_DIRECTORY / ".runtime" / "database" / "dashboard.sqlite3")
        self.assertEqual(DatabaseSettings(_env_file=None, directory=".runtime/alternate").directory,
                         BACKEND_DIRECTORY / ".runtime" / "alternate")
        with patch.dict(os.environ, {"DATABASE_DIRECTORY": str(self.directory), "DATABASE_BUSY_TIMEOUT": "2"}):
            self.assertEqual(DatabaseSettings(_env_file=None).path, self.directory / "dashboard.sqlite3")
            self.assertEqual(DatabaseSettings(_env_file=None).busy_timeout, 2)
        for directory in (BACKEND_DIRECTORY.parent / "frontend" / "public", BACKEND_DIRECTORY, Path(self.directory.anchor)):
            with self.subTest(directory=directory), self.assertRaises(ValidationError):
                DatabaseSettings(_env_file=None, directory=directory)
        with self.assertRaises(ValidationError):
            DatabaseSettings(_env_file=None, app_env="production", directory=self.directory)

    def test_repeatable_bootstrap_has_empty_domain_tables_and_sets_connection_policy(self):
        self.database.bootstrap()
        self.database.bootstrap()
        with self.database.connection() as connection:
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(connection.execute("PRAGMA synchronous").fetchone()[0], 2)
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(connection.execute("PRAGMA busy_timeout").fetchone()[0], 50)
            self.assertEqual(connection.execute("PRAGMA trusted_schema").fetchone()[0], 0)
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
            self.assertEqual(connection.execute("SELECT count(*) FROM observations").fetchone()[0], 0)
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")

    def test_connections_never_silently_create_a_missing_database(self):
        with self.assertRaises(sqlite3.OperationalError), self.database.connection():
            pass
        self.assertFalse(self.settings.path.exists())

    def test_commit_rollback_foreign_keys_and_unfinished_transaction_cleanup(self):
        self.database.bootstrap()
        with self.database.transaction() as connection:
            connection.execute("CREATE TABLE parent(id INTEGER PRIMARY KEY)")
            connection.execute("CREATE TABLE child(parent_id INTEGER REFERENCES parent(id))")
            connection.execute("INSERT INTO parent VALUES (?)", (1,))
        with self.assertRaises(sqlite3.IntegrityError), self.database.transaction() as connection:
            connection.execute("INSERT INTO parent VALUES (?)", (2,))
            connection.execute("INSERT INTO child VALUES (?)", (99,))
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("INSERT INTO parent VALUES (?)", (3,))
        with self.database.connection() as connection:
            self.assertEqual([row[0] for row in connection.execute("SELECT id FROM parent")], [1])
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")

    def test_competing_writer_times_out_without_damaging_committed_data(self):
        self.database.bootstrap()
        with self.database.transaction() as connection:
            connection.execute("CREATE TABLE test_value(value TEXT)")
            connection.execute("INSERT INTO test_value VALUES (?)", ("retained",))
        with self.database.transaction():
            with self.assertRaises(sqlite3.OperationalError), self.database.transaction():
                self.fail("A second writer must not enter")
            with self.database.connection() as reader:
                self.assertEqual(reader.execute("SELECT value FROM test_value").fetchone()[0], "retained")
        with self.database.transaction() as connection:
            connection.execute("INSERT INTO test_value VALUES (?)", ("next",))

    def test_committed_data_survives_two_separate_processes(self):
        common = (
            "from pathlib import Path; import sys; "
            "from app.config import DatabaseSettings; from app.database import Database; "
            "db=Database(DatabaseSettings(_env_file=None,app_env='test',directory=Path(sys.argv[1]))); "
            "db.bootstrap(); "
        )
        writer = common + (
            "\nwith db.transaction() as c:\n"
            " c.execute('CREATE TABLE restart_probe(value TEXT)'); "
            "c.execute('INSERT INTO restart_probe VALUES (?)',('1234567890.0123456789',))\n"
        )
        reader = common + (
            "\nwith db.connection() as c:\n"
            " assert c.execute('SELECT value FROM restart_probe').fetchone()[0]=='1234567890.0123456789'\n"
        )
        for script in (writer, reader):
            result = subprocess.run([sys.executable, "-c", script, str(self.directory)],
                                    cwd=BACKEND_DIRECTORY, env=self.process_environment,
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_unknown_schema_version_and_corrupt_file_fail_without_reset(self):
        self.database.bootstrap()
        with self.database.connection() as connection:
            connection.execute("PRAGMA user_version=99")
        with self.assertRaisesRegex(RuntimeError, "schema version"):
            self.database.bootstrap()
        with self.database.connection() as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 99)
        corrupt = self.directory / "corrupt"
        corrupt.mkdir()
        settings = DatabaseSettings(_env_file=None, directory=corrupt)
        settings.path.write_bytes(b"not a sqlite database")
        with self.assertRaises(sqlite3.DatabaseError):
            Database(settings).bootstrap()
        self.assertEqual(settings.path.read_bytes(), b"not a sqlite database")

    def test_nonregular_database_file_rejected(self):
        self.directory.mkdir()
        self.settings.path.mkdir()
        with self.assertRaisesRegex(RuntimeError, "regular private files"):
            self.database.bootstrap()

    @unittest.skipUnless(os.name == "posix", "Linux permissions are verified on a POSIX runtime")
    def test_posix_directory_database_and_live_sidecar_permissions(self):
        self.database.bootstrap()
        with self.database.transaction() as connection:
            connection.execute("CREATE TABLE private_value(id INTEGER)")
            self.assertEqual(stat.S_IMODE(self.directory.stat().st_mode), 0o700)
            for suffix in ("", "-wal", "-shm"):
                self.assertEqual(stat.S_IMODE(Path(str(self.settings.path) + suffix).stat().st_mode), 0o600)

    def test_production_requires_real_mount_and_cannot_use_test_settings(self):
        production = DatabaseSettings(_env_file=None, app_env="production")
        with patch("app.database.os.path.ismount", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "persistent disk"):
                Database(production).bootstrap()
        with self.assertRaisesRegex(ValueError, "production database settings"):
            create_app(Settings(_env_file=None, app_env="production", cors_allowed_origins=["https://dashboard.example.com"]),
                       database_settings=self.settings)

    def test_lifespan_bootstraps_private_database_without_file_routes(self):
        application = create_app(Settings(_env_file=None), database_settings=self.settings,
                                 scheduler_settings=SchedulerSettings(_env_file=None, enabled=False))
        with TestClient(application) as client:
            with application.state.database.transaction() as connection:
                connection.execute("CREATE TABLE lifecycle_probe(value TEXT)")
                connection.execute("INSERT INTO lifecycle_probe VALUES (?)", ("retained",))
            for path in ("/dashboard.sqlite3", "/.runtime/database/dashboard.sqlite3", "/api/v1/internal/ingest"):
                self.assertEqual(client.get(path).status_code, 404)
        with TestClient(application):
            with application.state.database.connection() as connection:
                self.assertEqual(connection.execute("SELECT value FROM lifecycle_probe").fetchone()[0], "retained")

    def test_database_failure_prevents_scheduler_start(self):
        application = create_app(Settings(_env_file=None), database_settings=self.settings,
                                 scheduler_settings=SchedulerSettings(_env_file=None, enabled=False))
        with patch("app.main.Database.bootstrap", side_effect=OSError("disk unavailable")), \
                patch("app.main.CollectorScheduler.start") as start:
            with self.assertRaises(OSError), TestClient(application):
                pass
        start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
