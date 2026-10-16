"""M4 security/capacity/query-plan checks; JWT and hosted isolation stay M5/M7."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
import json
from math import ceil
from pathlib import Path
import sqlite3
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.api import require_dashboard_access
from app.config import DatabaseSettings
from app.database import Database
import test_api
from test_normalization import cpi, expenditure, gdp, trade
from test_queries import world_resource
from test_repository import prepare
from test_snapshot_cache import check


ROUTES = ("/dashboard", "/indicators", "/indicators/trade",
          "/indicators/trade/history?series_id=exports", "/ticker")


class ConnectionPolicyTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.settings = DatabaseSettings(_env_file=None, app_env="test", directory=Path(temporary.name) / "db",
                                         max_connections=2)
        self.database = Database(self.settings)
        self.database.bootstrap()

    def test_read_connection_cannot_write_even_if_query_only_is_disabled(self):
        with self.database.connection(read_only=True) as connection:
            self.assertEqual(connection.execute("PRAGMA query_only").fetchone()[0], 1)
            connection.execute("PRAGMA query_only=OFF")
            with self.assertRaisesRegex(sqlite3.OperationalError, "readonly"):
                connection.execute("CREATE TABLE forbidden(value TEXT)")
            self.assertEqual(connection.execute("SELECT count(*) FROM observations").fetchone()[0], 0)
        with self.database.transaction() as connection:
            connection.execute("CREATE TABLE allowed(value TEXT)")

    def test_reader_and_writer_slots_are_shared_across_threads_and_released(self):
        with self.database.connection(read_only=True), self.database.transaction():
            def attempt():
                with self.database.connection(read_only=True):
                    self.fail("Connection cap must apply across request threads")
            with ThreadPoolExecutor(max_workers=1) as executor:
                with self.assertRaisesRegex(sqlite3.OperationalError, "capacity"):
                    executor.submit(attempt).result(timeout=2)
        with self.database.transaction() as connection:
            connection.execute("CREATE TABLE after_capacity(value TEXT)")
        for _ in range(4):
            with self.assertRaises(ValueError), self.database.connection():
                raise ValueError("Caller failed")
        with self.database.connection(read_only=True) as connection:
            self.assertEqual(connection.execute("SELECT 1").fetchone()[0], 1)

    def test_failed_open_and_failed_configuration_do_not_leak_slots(self):
        for _ in range(4):
            with patch("app.database.sqlite3.connect", side_effect=sqlite3.OperationalError("open failed")):
                with self.assertRaises(sqlite3.OperationalError), self.database.connection():
                    self.fail("Must not yield")
        for _ in range(4):
            with patch("app.database.monotonic", side_effect=RuntimeError("setup failed")):
                with self.assertRaises(RuntimeError), self.database.connection(read_only=True):
                    self.fail("Must not yield")
        with self.database.connection(), self.database.connection():
            pass

    def test_expensive_read_is_interrupted_and_cleanup_restores_capacity(self):
        # No real sleeps: initial deadline at t=2, progress callback sees t=3.
        with patch("app.database.monotonic", side_effect=(0, 3)):
            with self.assertRaisesRegex(sqlite3.OperationalError, "interrupted"):
                with self.database.connection(read_only=True) as connection:
                    connection.execute("BEGIN")
                    connection.execute("""WITH RECURSIVE n(x) AS
                        (VALUES(0) UNION ALL SELECT x+1 FROM n WHERE x<10000000)
                        SELECT sum(x) FROM n""").fetchone()
        with self.database.transaction() as writer, self.database.connection(read_only=True) as reader:
            writer.execute("CREATE TABLE after_timeout(value TEXT)")
            self.assertEqual(reader.execute("SELECT 1").fetchone()[0], 1)

    def test_capacity_and_read_budget_configuration_is_bounded(self):
        for options in ({"max_connections": 0}, {"max_connections": 33}, {"read_timeout": 0},
                        {"read_timeout": 11}, {"read_timeout": float("nan")}, {"read_timeout": float("inf")}):
            with self.subTest(options=options), self.assertRaises(ValidationError):
                DatabaseSettings(_env_file=None, **options)


class ApiBoundaryTests(unittest.TestCase):
    setUp = test_api.ApiTests.setUp
    populate = test_api.ApiTests.populate

    def test_every_guard_denies_before_any_database_connection_and_validator_check(self):
        self.application.dependency_overrides.clear()
        with patch.object(self.application.state.database, "connection", side_effect=AssertionError("Denied request touched DB")):
            for path in ROUTES:
                for headers, expected in (({}, 401), ({"Authorization": "Basic denied"}, 401),
                        ({"Authorization": "Bearer denied", "If-None-Match": "*"}, 503)):
                    response = self.client.get("/api/v1" + path, headers=headers)
                    self.assertEqual(response.status_code, expected, response.text)
                    self.assertNotIn("etag", response.headers)
                    self.assertNotIn("denied", response.text)

    def test_m5_can_supply_a_verifier_without_changing_data_handlers(self):
        # Explicit fake dependency demonstrates the seam; it does not verify JWT.
        from fastapi import HTTPException, Request
        def verifier(request: Request):
            if request.headers.get("Authorization") != "Bearer verifier-fixture":
                raise HTTPException(401, headers={"WWW-Authenticate": "Bearer"})
            return {"subject": "test-only"}
        self.application.dependency_overrides[require_dashboard_access] = verifier
        for path in ROUTES:
            self.assertEqual(self.client.get("/api/v1" + path).status_code, 401)
            self.assertEqual(self.client.get("/api/v1" + path, headers={"Authorization": "Bearer verifier-fixture"}).status_code, 200)

    def test_excessive_and_ambiguous_queries_are_rejected_before_sql(self):
        with patch.object(self.application.state.database, "connection", side_effect=AssertionError("Invalid query touched DB")):
            for query in ("window=1&window=24", "secret=" + "x" * 4096,
                          "&".join("period=x" for _ in range(17)),
                          "series_id=exports&series_id=imports"):
                response = self.client.get("/api/v1/dashboard?" + query)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertLess(len(response.content), 300)
        self.assertEqual(self.client.get("/api/v1/indicators/trade?period=exports:2026-09&period=imports:2026-09").status_code, 200)

    def test_capacity_returns_safe_503_and_recovers_without_restart(self):
        self.populate()
        database = self.application.state.database
        with ExitStack() as stack:
            for _ in range(database.settings.max_connections):
                stack.enter_context(database.connection(read_only=True))
            for path in ROUTES:
                response = self.client.get("/api/v1" + path, headers={"If-None-Match": "*"})
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()["error"]["code"], "storage_unavailable")
                self.assertNotIn("capacity", response.text)
            self.assertEqual(self.client.get("/health").status_code, 503)
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/dashboard").status_code, 200)

    def test_all_api_reads_and_health_request_read_only_connections(self):
        self.populate()
        database = self.application.state.database
        with patch.object(database, "connection", wraps=database.connection) as connections:
            for path in ROUTES + ("health",):
                url = "/health" if path == "health" else "/api/v1" + path
                self.assertEqual(self.client.get(url).status_code, 200)
            self.assertTrue(connections.call_args_list)
            self.assertTrue(all(call.kwargs == {"read_only": True} for call in connections.call_args_list))

    def test_sql_deadline_returns_safe_503_then_recovers(self):
        self.populate()
        # Begin is short; force the VM progress callback during the dashboard read.
        with patch("app.database.monotonic", side_effect=lambda: next(clock, 3)):
            clock = iter((0,))
            response = self.client.get("/api/v1/dashboard?window=24")
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(response.json()["error"]["code"], "storage_unavailable")
        self.assertNotIn("interrupted", response.text)
        self.assertEqual(self.client.get("/api/v1/dashboard").status_code, 200)

    def test_no_database_files_or_ingest_are_exposed(self):
        for path in ("/dashboard.sqlite3", "/dashboard.sqlite3-wal", "/.runtime/database/dashboard.sqlite3",
                     "/var/data/economic-dash/dashboard.sqlite3", "/api/v1/internal/ingest"):
            for method in (self.client.get, self.client.post):
                self.assertEqual(method(path).status_code, 404)

    def test_actual_history_queries_use_period_and_latest_indexes(self):
        self.populate()
        database = self.application.state.database
        statements = []
        original = database.connection
        @contextmanager
        def traced(**kwargs):
            with original(**kwargs) as connection:
                connection.set_trace_callback(statements.append)
                yield connection
        with patch.object(database, "connection", side_effect=traced):
            self.application.state.dashboard_queries.dashboard(window=24)
        histories = [sql for sql in statements if "SELECT * FROM observations WHERE" in sql]
        latest = [sql for sql in statements if "SELECT period_end FROM observations" in sql]
        self.assertTrue(histories and latest)
        with original(read_only=True) as connection:
            for sql in histories:
                plan = " ".join(row[3] for row in connection.execute("EXPLAIN QUERY PLAN " + sql))
                self.assertIn("SEARCH observations USING INDEX", plan)
                self.assertIn("period_id=?", plan)
                self.assertNotIn("TEMP B-TREE", plan)
            for sql in latest:
                plan = " ".join(row[3] for row in connection.execute("EXPLAIN QUERY PLAN " + sql))
                self.assertIn("SEARCH observations USING INDEX observations_history", plan)
                self.assertIn("period_end<?", plan)

    def test_local_latency_smoke_with_large_synthetic_archive(self):
        # Synthetic stress history, not authentic economic data or production seeds.
        years = tuple(range(1000, 2026))
        self.repository.commit(prepare(checks=(world_resource(years, ("2.5",) * len(years)),)
                                      + tuple(check(f()) for f in (gdp, trade, cpi, expenditure))))
        with self.application.state.database.connection(read_only=True) as connection:
            rows = connection.execute("SELECT count(*) FROM observations").fetchone()[0]
        self.assertGreaterEqual(rows, 1000)
        paths = ("/api/v1/dashboard?window=24", "/api/v1/indicators?window=24",
                 "/api/v1/indicators/trade?window=24",
                 "/api/v1/indicators/gdp_growth/history?series_id=gdp_growth_world&window=24",
                 "/api/v1/ticker", "/health")
        metrics = {}
        for path in paths:
            self.assertEqual(self.client.get(path).status_code, 200)  # Warm up.
            samples = []
            for _ in range(20):
                start = perf_counter()
                response = self.client.get(path)
                samples.append((perf_counter() - start) * 1000)
                self.assertEqual(response.status_code, 200, response.text)
            p95 = sorted(samples)[ceil(len(samples) * 0.95) - 1]
            metrics[path] = {"median_ms": round(median(samples), 2), "p95_ms": round(p95, 2)}
            # Local smoke budget only; M7 measures hosted/network latency.
            self.assertLess(p95, 500, f"Local p95 exceeded 500ms: {path}: {metrics[path]}")
        print(json.dumps({"local_test_only": True, "authentication_verified": False,
                          "synthetic_rows": rows, "samples_per_route": 20,
                          "p95_budget_ms": 500, "latency": metrics}, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
