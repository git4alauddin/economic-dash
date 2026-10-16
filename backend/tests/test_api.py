"""Protected v1 API contracts. Test dependency overrides are not JWT authentication."""

from datetime import timedelta
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import require_dashboard_access
from app.api_models import DashboardData, Envelope
from app.collectors.handoff import RepositoryBridge
from app.config import DatabaseSettings, SchedulerSettings, Settings
from app.main import create_app
from test_normalization import NOW, cpi, expenditure, gdp, trade
from test_queries import world_resource
from test_repository import prepare
from test_snapshot_cache import check


class ApiTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.application = create_app(Settings(_env_file=None, app_env="test"),
            database_settings=DatabaseSettings(_env_file=None, app_env="test", directory=Path(directory.name) / "db"),
            scheduler_settings=SchedulerSettings(_env_file=None, enabled=False))
        # M5 must supply the real verifier; this override only tests the read layer.
        self.application.dependency_overrides[require_dashboard_access] = lambda: None
        self.client = self.enterContext(TestClient(self.application))
        self.clock = self.enterContext(patch("app.api.datetime"))
        self.clock.now.return_value = NOW + timedelta(hours=1)
        self.repository = self.application.state.collection_repository

    def populate(self):
        self.repository.commit(prepare(checks=(world_resource(),) + tuple(check(f()) for f in (gdp, trade, cpi, expenditure))))

    def get(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        return response.json()

    def test_guard_is_closed_for_missing_and_unverified_tokens_on_every_data_route(self):
        self.application.dependency_overrides.clear()
        with patch.object(self.application.state.dashboard_queries, "dashboard", side_effect=AssertionError("Denied requests must not read data")):
            for path in ("/dashboard", "/indicators", "/indicators/trade", "/indicators/trade/history?series_id=exports", "/ticker"):
                response = self.client.get("/api/v1" + path)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.headers["www-authenticate"], "Bearer")
                self.assertEqual(response.json()["error"]["code"], "authentication_required")
                response = self.client.get("/api/v1" + path, headers={"Authorization": "Bearer unverified-test-token"})
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()["error"]["code"], "authentication_not_configured")
                self.assertNotIn("unverified-test-token", response.text)

    def test_openapi_declares_models_bearer_security_bounds_and_error_schemas(self):
        schema = self.client.get("/openapi.json").json()
        for path in ("/api/v1/dashboard", "/api/v1/indicators", "/api/v1/indicators/{indicator_id}", "/api/v1/indicators/{indicator_id}/history", "/api/v1/ticker"):
            operation = schema["paths"][path]["get"]
            self.assertEqual(operation["security"], [{"DashboardBearer": []}])
            for status in ("200", "401", "404", "422", "503"):
                self.assertIn("schema", operation["responses"][status]["content"]["application/json"])
        window = next(p for p in schema["paths"]["/api/v1/dashboard"]["get"]["parameters"] if p["name"] == "window")
        self.assertEqual((window["schema"]["minimum"], window["schema"]["maximum"]), (1, 24))
        self.assertEqual(self.client.get("/docs").status_code, 200)

    def test_empty_response_has_explicit_null_metadata_and_all_required_slots(self):
        body = self.get("/api/v1/dashboard")
        Envelope[DashboardData].model_validate_json(self.client.get("/api/v1/dashboard").text)
        self.assertEqual(body["meta"]["api_version"], "v1")
        self.assertEqual(body["meta"]["data_version"], "empty")
        self.assertTrue(body["meta"]["partial"])
        self.assertEqual(len(body["data"]["panels"]), 6)
        self.assertEqual(sum(len(p["summaries"]) for p in body["data"]["panels"].values()), 12)
        for panel in body["data"]["panels"].values():
            for series in panel["series"].values():
                point = series["latest"]
                self.assertIsNone(point["value"])
                self.assertIsNone(point["observation_period"])
                self.assertIsNone(point["as_of"])
                self.assertFalse(point["retention_allowed"])
                self.assertTrue(point["reason_code"])
        ticker = body["data"]["ticker"]
        self.assertEqual(ticker["cadence"], "unknown")
        self.assertEqual(len(ticker["items"]), 3)
        self.assertTrue(all(item["value"] is None and item["as_of"] is None for item in ticker["items"]))

    def test_populated_dashboard_preserves_decimal_provenance_and_compatible_chart_axes(self):
        self.populate()
        body = self.get("/api/v1/dashboard")
        self.assertEqual(body["meta"]["data_version"], "first")
        panels = body["data"]["panels"]
        world = panels["gdp_growth"]["series"]["gdp_growth_world"]["latest"]
        self.assertEqual(world["value"], "2.123456789012345678")
        self.assertEqual(world["observation_period"]["basis"], "calendar")
        self.assertIsNone(world["published_at"])
        self.assertEqual(len(world["sources"]), 2)
        self.assertTrue(world["vintage_id"] and world["parser_version"])
        self.assertEqual({period["basis"] for period in panels["gdp_growth"]["chart"]["periods"]}, {"calendar", "fiscal"})
        exports = panels["trade"]["series"]["exports"]
        self.assertEqual(exports["comparison"]["unit"], "percent")
        self.assertEqual((exports["comparison"]["exact_numerator"], exports["comparison"]["exact_denominator"]), ("100", "9"))
        self.assertEqual(panels["inflation_india"]["series"]["cpi_yoy"]["latest"]["value"], "0.00")
        balance = panels["trade"]["series"]["trade_balance"]["latest"]
        self.assertEqual(balance["value"], "-4.70")
        self.assertEqual([p["series_id"] for p in balance["inputs"]], ["exports", "imports"])
        self.assertLess(float(panels["trade"]["chart"]["domain"][0]), 0)

    def test_detail_and_history_select_canonical_periods_and_keep_reference_outside_chart(self):
        self.populate()
        detail = self.get("/api/v1/indicators/gdp_growth?period=gdp_growth_india:FY2024-25&period=gdp_growth_world:CY2024")
        self.assertEqual(detail["data"]["series"]["gdp_growth_world"]["latest"]["value"], "1.00")
        history = self.get("/api/v1/indicators/trade/history?series_id=exports&window=1")
        self.assertEqual(len(history["data"]["series"]["history"]["points"]), 1)
        self.assertEqual(history["data"]["series"]["comparison"]["reference_period_id"], "2025-09")
        self.assertTrue(history["data"]["series"]["history"]["truncated"])
        historical = self.get("/api/v1/indicators/gdp_growth/history?series_id=gdp_growth_world&end_period_id=CY2024")
        self.assertEqual(historical["data"]["selected_period"]["id"], "CY2024")

    def test_catalog_and_ticker_preserve_blockers_without_fetching_quotes(self):
        self.populate()
        catalog = self.get("/api/v1/indicators?window=24")
        self.assertEqual(len(catalog["data"]), 6)
        gdp_catalog = next(p for p in catalog["data"] if p["indicator_id"] == "gdp_growth")
        world = next(s for s in gdp_catalog["series"] if s["series_id"] == "gdp_growth_world")
        self.assertEqual([p["id"] for p in world["available_periods"]], ["CY2024", "CY2025"])
        debt = next(p for p in catalog["data"] if p["indicator_id"] == "debt_to_gdp")
        self.assertIn("debt_india_us_comparison", debt["summary_requirements"])
        with patch.object(self.application.state.dashboard_queries, "dashboard", side_effect=AssertionError("Ticker must not query macro history")):
            quotes = self.get("/api/v1/ticker")["data"]["items"]
        self.assertEqual({q["instrument_id"] for q in quotes}, {"sensex", "nifty_bank", "nifty_it"})
        self.assertTrue(all(q["status"] == "unavailable" and q["sources"] == [] for q in quotes))

    def test_invalid_queries_unknown_ids_and_wrong_series_return_safe_consistent_errors(self):
        cases = [("/indicators/unknown", 404), ("/indicators/unknown/history?series_id=exports", 404),
                 ("/indicators/trade/history?series_id=cpi_yoy", 404), ("/dashboard?window=0", 422),
                 ("/dashboard?window=25", 422), ("/dashboard?window=1.5", 422), ("/dashboard?secret=untrusted-secret", 422),
                 ("/indicators/trade/history", 422), ("/indicators/gdp_growth/history?series_id=gdp_growth_india&end_period_id=CY2025", 422),
                 ("/indicators/trade?period=exports:2026-09&period=exports:2025-09", 422),
                 ("/indicators/trade?period=cpi_yoy:2026-09", 422), ("/ticker?window=5", 422)]
        for path, status in cases:
            with self.subTest(path=path):
                response = self.client.get("/api/v1" + path)
                self.assertEqual(response.status_code, status, response.text)
                self.assertEqual(set(response.json()), {"error"})
                self.assertNotIn("untrusted-secret", response.text)

    def test_storage_and_response_failures_hide_internal_exception_details(self):
        queries = self.application.state.dashboard_queries
        with patch.object(queries, "dashboard", side_effect=sqlite3.OperationalError("password=secret C:/private/db")):
            response = self.client.get("/api/v1/dashboard")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "storage_unavailable")
        self.assertNotIn("secret", response.text)
        with patch("app.api.project.dashboard", return_value={"invalid": "secret"}):
            response = self.client.get("/api/v1/dashboard")
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("secret", response.text)

    def test_failure_retains_original_values_and_dates_with_stale_status(self):
        self.populate()
        before = self.get("/api/v1/dashboard")
        cache = RepositoryBridge(self.repository).open_cache()
        now = NOW + timedelta(hours=1)
        self.assertTrue(cache.record_failure(tuple(self.repository.load().envelope.source_ids), run_id="outage", started=now, finished=now, reason="timeout"))
        after = self.get("/api/v1/dashboard")
        self.assertEqual(after["meta"]["data_version"], "outage")
        for indicator, panel in after["data"]["panels"].items():
            for sid, entry in panel["series"].items():
                if entry["latest"]["value"] is not None:
                    old = before["data"]["panels"][indicator]["series"][sid]["latest"]
                    self.assertEqual((entry["latest"]["value"], entry["latest"]["as_of"]), (old["value"], old["as_of"]))
                    self.assertEqual(entry["latest"]["status"], "stale")

    def test_get_routes_do_not_collect_or_write_and_ingest_stays_absent(self):
        self.populate()
        before = self.repository.load()
        with patch("socket.socket.connect", side_effect=AssertionError("Reads must not open network connections")), \
                patch("app.collectors.http_client.CollectorHttpClient.fetch", side_effect=AssertionError("Reads must not fetch upstream")):
            for path in ("/dashboard", "/indicators", "/indicators/trade", "/indicators/trade/history?series_id=exports", "/ticker"):
                self.get("/api/v1" + path)
        self.assertEqual(self.repository.load(), before)
        self.assertEqual(self.client.post("/api/v1/internal/ingest", json={}).status_code, 404)
        self.assertEqual(self.client.get("/").json(), {"message": "Economic Indicators API"})


if __name__ == "__main__":
    unittest.main()
