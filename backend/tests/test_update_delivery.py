"""Health, time-driven freshness, conditional reads and failed-write overlays."""

import asyncio
from datetime import timedelta
import logging
import sqlite3
import unittest
from unittest.mock import patch

from app.api import require_dashboard_access
from app.collectors.handoff import RepositoryBridge
from app.queries import QueryIntegrityError
import test_api
from test_normalization import NOW, wb
from test_repository import prepare
from test_scheduler import FakeClient
from test_snapshot_cache import check


class UpdateDeliveryTests(unittest.TestCase):
    setUp = test_api.ApiTests.setUp
    populate = test_api.ApiTests.populate
    get = test_api.ApiTests.get

    def test_public_health_is_ready_with_empty_data_and_independent_of_source_outages(self):
        self.application.dependency_overrides.clear()
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertNotIn("security", self.client.get("/openapi.json").json()["paths"]["/health"]["get"])
        cache = RepositoryBridge(self.repository).open_cache()
        self.assertTrue(cache.record_failure(("world_bank_gdp",), run_id="source-down", started=NOW, finished=NOW, reason="timeout"))
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})

    def test_health_database_down_and_recovered_never_exposes_paths(self):
        with patch.object(self.application.state.database, "connection", side_effect=sqlite3.OperationalError("C:/secret/db password")):
            response = self.client.get("/health")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})
        self.assertEqual(self.client.get("/health").status_code, 200)
        with self.application.state.database.connection() as connection:
            connection.execute("PRAGMA user_version=999")
        self.assertEqual(self.client.get("/health").status_code, 503)

    def test_matching_validators_return_bodyless_304_after_authenticated_success(self):
        self.populate()
        for path in ("/dashboard", "/indicators", "/indicators/trade", "/indicators/trade/history?series_id=exports", "/ticker"):
            url = "/api/v1" + path
            first = self.client.get(url)
            tag = first.headers["etag"]
            self.assertTrue(tag.startswith('W/"sha256:'))
            self.assertEqual(first.json()["meta"]["poll_interval_seconds"], 60)
            self.assertEqual(first.json()["meta"]["data_version"], "first")
            for supplied in (tag, tag.removeprefix("W/"), '"unrelated", ' + tag, "*"):
                response = self.client.get(url, headers={"If-None-Match": supplied})
                self.assertEqual(response.status_code, 304, response.text)
                self.assertEqual(response.content, b"")
                self.assertEqual(response.headers["etag"], tag)
                self.assertEqual(response.headers["x-poll-interval"], "60")
                self.assertEqual(response.headers["cache-control"], "no-store")

    def test_generation_clock_does_not_churn_etag_and_query_variants_are_distinct(self):
        self.populate()
        first = self.client.get("/api/v1/dashboard")
        self.clock.now.return_value += timedelta(seconds=1)
        second = self.client.get("/api/v1/dashboard")
        self.assertNotEqual(first.json()["meta"]["generated_at"], second.json()["meta"]["generated_at"])
        self.assertEqual(first.json()["meta"]["version"], second.json()["meta"]["version"])
        self.assertEqual(first.headers["etag"], second.headers["etag"])
        self.assertEqual(self.client.get("/api/v1/dashboard?window=1", headers={"If-None-Match": first.headers["etag"]}).status_code, 200)

    def test_freshness_expires_without_new_sql_commit_or_changed_observation_dates(self):
        self.populate()
        before = self.client.get("/api/v1/dashboard")
        original = before.json()["data"]["panels"]["gdp_growth"]["series"]["gdp_growth_world"]["latest"]
        self.assertEqual(original["status"], "fresh")
        self.clock.now.return_value = NOW + timedelta(days=30)
        response = self.client.get("/api/v1/dashboard", headers={"If-None-Match": before.headers["etag"]})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        point = body["data"]["panels"]["gdp_growth"]["series"]["gdp_growth_world"]["latest"]
        self.assertEqual(point["status"], "stale")
        self.assertEqual(point["reason_code"], "refresh_check_overdue")
        self.assertEqual((point["value"], point["as_of"], point["retrieved_at"]), (original["value"], original["as_of"], original["retrieved_at"]))
        self.assertEqual(body["meta"]["data_version"], before.json()["meta"]["data_version"])
        self.assertNotEqual(body["meta"]["version"], before.json()["meta"]["version"])
        self.assertEqual(self.repository.load().envelope.run_id, "first")

    def test_publication_deadline_can_expire_while_check_is_current(self):
        self.populate()
        with patch("app.collectors.freshness.publication_deadline", return_value=NOW + timedelta(hours=2)):
            before = self.client.get("/api/v1/dashboard")
            self.clock.now.return_value = NOW + timedelta(hours=3)
            after = self.client.get("/api/v1/dashboard", headers={"If-None-Match": before.headers["etag"]})
        self.assertEqual(after.status_code, 200)
        world = after.json()["data"]["panels"]["gdp_growth"]["series"]["gdp_growth_world"]["latest"]
        self.assertEqual(world["reason_code"], "observation_release_overdue")
        self.assertEqual(world["last_success_at"], "2026-10-16T12:00:00Z")

    def test_source_empty_failed_and_blocked_states_are_distinct(self):
        self.repository.commit(prepare(checks=(check(wb(total=0)),)))
        empty = self.get("/api/v1/dashboard")["data"]["panels"]["gdp_growth"]["series"]["gdp_growth_world"]
        self.assertEqual(empty["latest"]["status"], "empty")
        self.assertEqual(empty["history"]["status"], "empty")
        cache = RepositoryBridge(self.repository).open_cache()
        later = NOW + timedelta(hours=1)
        self.assertTrue(cache.record_failure(("world_bank_gdp",), run_id="empty-then-failed", started=later, finished=later, reason="timeout"))
        body = self.get("/api/v1/dashboard")
        world = body["data"]["panels"]["gdp_growth"]["series"]["gdp_growth_world"]["latest"]
        debt = body["data"]["panels"]["debt_to_gdp"]["series"]["debt_to_gdp_india"]["latest"]
        self.assertEqual((world["status"], world["reason_code"]), ("error", "timeout"))
        self.assertIsNone(world["value"])
        self.assertFalse(world["retention_allowed"])
        self.assertEqual(debt["status"], "unavailable")

    def test_failed_write_overlay_is_explicit_and_newer_durable_recovery_wins(self):
        self.populate()
        before = self.client.get("/api/v1/dashboard")
        runner = self.application.state.collection_runner
        runner.now = lambda: NOW + timedelta(hours=1)
        runner.client_factory = FakeClient
        async def timeout(*args, **kwargs):
            raise TimeoutError()
        runner.collect = timeout
        logger = logging.Logger("silent-overlay-test")
        logger.addHandler(logging.NullHandler())
        with patch.object(self.repository, "_write_states", side_effect=sqlite3.OperationalError("disk full")), patch("app.collectors.runner.LOGGER", logger):
            result = asyncio.run(runner.run(("world_bank_gdp",), trigger="test"))
        self.assertFalse(result.persisted)
        after = self.client.get("/api/v1/dashboard", headers={"If-None-Match": before.headers["etag"]})
        self.assertEqual(after.status_code, 200)
        point = after.json()["data"]["panels"]["gdp_growth"]["series"]["gdp_growth_world"]["latest"]
        self.assertEqual(point["status"], "stale")
        self.assertFalse(point["failure_state_persisted"])
        self.assertEqual(after.json()["meta"]["data_version"], "first")
        # Equal/coarse timestamps must also prefer durable state over a RAM warning.
        self.repository.commit(prepare(wb, previous=self.repository.load(), at=NOW + timedelta(hours=1), run_id="recovered"))
        self.clock.now.return_value = NOW + timedelta(hours=3)
        recovered = self.get("/api/v1/dashboard")
        point = recovered["data"]["panels"]["gdp_growth"]["series"]["gdp_growth_world"]["latest"]
        self.assertEqual(point["status"], "fresh")
        self.assertIsNot(point["failure_state_persisted"], False)
        self.assertEqual(recovered["meta"]["data_version"], "recovered")

    def test_auth_and_storage_failures_never_turn_into_304(self):
        self.populate()
        tag = self.client.get("/api/v1/dashboard").headers["etag"]
        self.application.dependency_overrides.clear()
        self.assertEqual(self.client.get("/api/v1/dashboard", headers={"If-None-Match": tag}).status_code, 401)
        self.assertEqual(self.client.get("/api/v1/dashboard", headers={"If-None-Match": "*", "Authorization": "Bearer invalid"}).status_code, 503)
        self.application.dependency_overrides[require_dashboard_access] = lambda: None
        with patch.object(self.application.state.dashboard_queries, "dashboard", side_effect=sqlite3.OperationalError("unavailable")):
            self.assertEqual(self.client.get("/api/v1/dashboard", headers={"If-None-Match": tag}).status_code, 503)

    def test_conditional_polling_headers_work_only_with_allowed_browser_origin(self):
        preflight = self.client.options("/api/v1/dashboard", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization,if-none-match"})
        self.assertEqual(preflight.status_code, 200)
        response = self.client.get("/api/v1/dashboard", headers={"Origin": "http://localhost:5173"})
        self.assertIn("ETag", response.headers["access-control-expose-headers"])
        denied = self.client.get("/api/v1/dashboard", headers={"Origin": "https://unknown.example"})
        self.assertNotIn("access-control-allow-origin", denied.headers)


if __name__ == "__main__":
    unittest.main()
