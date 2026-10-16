"""Private file boundaries and absence of external collection/SQL surfaces."""

from contextlib import ExitStack
import os
from pathlib import Path
import sqlite3
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth.settings import AuthSettings
from app.auth.users import UserStore
from app.config import BACKEND_DIRECTORY, DatabaseSettings, SchedulerSettings, Settings
from app.database import Database
from app.main import create_app
from secrets import token_hex
from starlette.routing import Mount, WebSocketRoute


class PrivateFileTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.settings = DatabaseSettings(_env_file=None, app_env="test", directory=self.root / "private")
        self.database = Database(self.settings)
        self.database.bootstrap()

    def test_linked_database_or_sidecars_are_refused_before_open_or_chmod(self):
        for suffix in ("", "-wal", "-shm", "-journal"):
            file = Path(str(self.settings.path) + suffix)
            if not file.exists():
                file.touch(mode=0o600)
            link = self.root / "public-copy"
            os.link(file, link)
            try:
                with self.subTest(suffix=suffix), patch("app.database.sqlite3.connect", side_effect=AssertionError("Linked file opened")):
                    with self.assertRaisesRegex(RuntimeError, "hard links"), self.database.connection():
                        pass
                    with self.assertRaisesRegex(RuntimeError, "hard links"):
                        self.database.bootstrap()
            finally:
                link.unlink()
                if suffix:
                    file.unlink()
        with self.database.connection(read_only=True) as connection:
            self.assertEqual(connection.execute("PRAGMA quick_check").fetchone()[0], "ok")

    def test_directory_redirection_after_settings_validation_is_refused(self):
        # Real symlink creation may require Windows developer mode/admin. Mock
        # only resolution here; the genuine filesystem hard-link test is above.
        resolve = Path.resolve
        def redirected(path, *args, **kwargs):
            if path == self.settings.directory:
                return self.root / "public"
            return resolve(path, *args, **kwargs)
        with patch.object(Path, "resolve", redirected), patch("app.database.sqlite3.connect", side_effect=AssertionError("Redirected directory opened")):
            with self.assertRaisesRegex(RuntimeError, "canonical"), self.database.connection():
                pass
            with self.assertRaisesRegex(RuntimeError, "canonical"):
                self.database.bootstrap()

    def test_frontend_directory_and_nested_public_paths_cannot_hold_database(self):
        for directory in (BACKEND_DIRECTORY.parent / "frontend", BACKEND_DIRECTORY.parent / "frontend/dist/assets",
                          BACKEND_DIRECTORY.parent / "frontend/public"):
            with self.subTest(directory=directory), self.assertRaises(ValidationError):
                DatabaseSettings(_env_file=None, directory=directory)

    @unittest.skipUnless(os.name == "posix", "Service-user modes require POSIX runtime")
    def test_runtime_permission_drift_is_refused_and_owned_files_can_be_repaired_at_bootstrap(self):
        for path, mode in ((self.settings.directory, 0o755), (self.settings.path, 0o644)):
            path.chmod(mode)
            with self.assertRaisesRegex(RuntimeError, "service user"), self.database.connection():
                pass
            self.database.bootstrap()
        self.assertEqual(stat.S_IMODE(self.settings.directory.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.settings.path.stat().st_mode), 0o600)

    def test_sql_and_identity_operations_require_no_tcp_connection(self):
        with patch("socket.socket.connect", side_effect=AssertionError("SQLite attempted network I/O")), \
                patch("socket.create_connection", side_effect=AssertionError("SQLite attempted network I/O")):
            self.database.bootstrap()
            users = UserStore(self.database)
            identity = users.provision("private_check", "synthetic private boundary passphrase").identity
            self.assertEqual(users.authenticate("private_check", "synthetic private boundary passphrase").user_id, identity.user_id)
            with self.database.transaction() as connection:
                connection.execute("CREATE TABLE private_write(value TEXT)")
                connection.execute("INSERT INTO private_write VALUES (?)", ("retained",))
            with self.database.connection(read_only=True) as connection:
                self.assertEqual(connection.execute("SELECT value FROM private_write").fetchone()[0], "retained")
                connection.execute("PRAGMA query_only=OFF")
                with self.assertRaises(sqlite3.OperationalError):
                    connection.execute("DELETE FROM private_write")


class HttpBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.application = create_app(Settings(_env_file=None, app_env="test"),
            auth_settings=AuthSettings(_env_file=None, app_env="test", jwt_signing_key=token_hex(32)),
            database_settings=DatabaseSettings(_env_file=None, app_env="test", directory=Path(temporary.name) / "db"),
            scheduler_settings=SchedulerSettings(_env_file=None, enabled=False))
        self.client = self.enterContext(TestClient(self.application))
        users = self.application.state.auth_service.users
        users.provision("private_check", "synthetic private boundary passphrase")
        grant = self.client.post("/api/v1/auth/login", json={"username": "private_check", "password": "synthetic private boundary passphrase"})
        self.assertEqual(grant.status_code, 200)
        self.headers = {"Authorization": "Bearer " + grant.json()["access_token"]}

    def test_route_inventory_has_no_file_mount_websocket_or_external_write_surface(self):
        self.assertFalse(any(isinstance(route, (Mount, WebSocketRoute)) for route in self.application.routes))
        schema = self.client.get("/openapi.json").json()
        for path, operations in schema["paths"].items():
            for method in operations:
                self.assertTrue(method == "get" or (path == "/api/v1/auth/login" and method == "post"), (path, method))

    def test_public_and_authenticated_requests_cannot_fetch_private_files_or_proxy_sql(self):
        paths = ["/dashboard.sqlite3", "/dashboard.sqlite3-wal", "/dashboard.sqlite3-shm",
            "/.runtime/database/dashboard.sqlite3", "/backend/.runtime/database/dashboard.sqlite3",
            "/.env", "/backend/.env", "/app/auth/users.py", "/app/migrations/002_auth_users.sql",
            "/@fs/" + self.application.state.database.settings.path.as_posix(),
            "/api/v1/database", "/api/v1/sql", "/api/v1/backup", "/api/v1/internal/ingest",
            "/api/v1/collect", "/api/v1/refresh", "/api/v1/auth/register"]
        for headers in ({}, self.headers):
            for path in paths:
                for method in ("GET", "HEAD", "POST"):
                    result = self.client.request(method, path, headers=headers, follow_redirects=False)
                    self.assertEqual(result.status_code, 404, (method, path))
                    self.assertNotIn(b"SQLite format 3", result.content)
                    self.assertNotIn(b"$argon2id$", result.content)
        self.assertFalse(self.application.dependency_overrides)

    def test_authenticated_read_routes_cannot_mutate_and_never_fetch_upstreams(self):
        service = self.application.state.database
        with service.connection(read_only=True) as connection:
            before = connection.execute("SELECT count(*) FROM observations").fetchone()[0]
        with ExitStack() as stack:
            stack.enter_context(patch.object(service, "transaction", side_effect=AssertionError("HTTP wrote private data")))
            stack.enter_context(patch("app.collectors.http_client.CollectorHttpClient.fetch", side_effect=AssertionError("HTTP fetched upstream")))
            for path in ("/api/v1/dashboard", "/api/v1/indicators", "/api/v1/indicators/gdp_growth",
                         "/api/v1/indicators/gdp_growth/history?series_id=gdp_growth_world", "/api/v1/ticker"):
                self.assertEqual(self.client.get(path, headers=self.headers).status_code, 200, path)
                for method in ("POST", "PUT", "PATCH", "DELETE"):
                    result = self.client.request(method, path, headers=self.headers, json={"sql": "DELETE FROM observations"})
                    self.assertEqual(result.status_code, 405, (method, path))
        with service.connection(read_only=True) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM observations").fetchone()[0], before)


if __name__ == "__main__":
    unittest.main()
