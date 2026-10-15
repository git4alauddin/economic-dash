"""Last-good retention, conditional caching, atomic acceptance and freshness."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

import httpx2 as httpx

from app.collectors.adapters import SourcePayloads
from app.collectors.catalog import SourceRegistry
from app.collectors.freshness import publication_deadline
from app.collectors.history import HistoryCollection, ResourceCheck, SourceFailure, build_history
from app.collectors.http_client import CollectorHttpClient
from app.collectors.normalization import SourceNormalizer
from app.collectors.runner import CollectionRunner, collect_sources
from app.collectors.snapshot_cache import CacheCommitError, SnapshotCache
from app.config import CollectorSettings, SchedulerSettings
from test_normalization import NOW, changed, cpi, expenditure, gdp, trade, wb
from test_scheduler import index_html


def check(bundle, *, at=NOW, normalizer=None):
    batch = (normalizer or SourceNormalizer()).parse(bundle)
    receipts = tuple(replace(r, retrieved_at=at) for r in (bundle.payload, bundle.metadata) if r is not None)
    return ResourceCheck(bundle.payload.source_id, batch, receipts, at)


def collection(checks=(), failures=()):
    batches = tuple(c.batch for c in checks)
    return HistoryCollection(build_history(batches, failures=failures), batches, tuple(r for c in checks for r in c.receipts), checks)


def accept(cache, checks=(), *, sources=None, at=NOW, failures=()):
    sources = sources or tuple(dict.fromkeys(c.batch.source_id for c in checks))
    return cache.accept(collection(checks, failures), sources, run_id=f"test-{at.isoformat()}", started=at, finished=at)


def label(cache, sid, at=NOW):
    return next(s for s in cache.view(at).freshness if s.series_id == sid)


class CacheTests(unittest.TestCase):
    def test_failure_retains_value_source_period_and_original_retrieval(self):
        cache = SnapshotCache()
        accept(cache, (check(trade()),))
        before = label(cache, "exports")
        later = NOW + timedelta(hours=1)
        cache.record_failure(("commerce_trade_pib",), run_id="failed", started=later, finished=later, reason="timeout")
        retained = label(cache, "exports", later)
        self.assertEqual(retained.observation, before.observation)
        self.assertEqual(retained.retrieved_at, NOW)
        self.assertEqual(retained.status, "stale")
        self.assertEqual(retained.reason_code, "timeout")
        self.assertTrue(retained.retention_allowed)
        self.assertEqual(retained.last_success_at, NOW)
        self.assertEqual(retained.last_checked_at, later)
        self.assertIsNone(label(SnapshotCache(), "exports").observation)
        self.assertEqual(label(SnapshotCache(), "exports").status, "unavailable")

    def test_subset_refresh_does_not_erase_other_sources(self):
        cache = SnapshotCache()
        accept(cache, (check(trade()), check(wb())))
        world = label(cache, "gdp_growth_world").observation
        later = NOW + timedelta(hours=1)
        accept(cache, (check(changed(trade(), "15 OCT", "16 OCT"), at=later),), at=later)
        self.assertEqual(label(cache, "gdp_growth_world", later).observation, world)
        self.assertEqual(len(cache.view(later).freshness), 13)
        self.assertEqual(len(cache.view(later).history.unavailable_requirements), 8)

    def test_raw_hash_changes_are_unchanged_and_raw_bodies_are_discarded(self):
        cache = SnapshotCache()
        original = check(trade())
        accept(cache, (original,))
        later = NOW + timedelta(hours=1)
        new = check(changed(trade(), "</body>", "<!-- counter --> </body>"), at=later)
        result = accept(cache, (new,), at=later)
        self.assertEqual((result.changed, result.unchanged), (0, 1))
        entry = cache.get("commerce_trade_pib")
        self.assertEqual(entry.batch, original.batch)
        self.assertEqual(entry.accepted_at, NOW)
        self.assertEqual(entry.checked_at, later)
        self.assertTrue(all(r.body is None for r in entry.receipts))

    def test_empty_or_null_same_period_cannot_delete_last_good(self):
        for sample, reason in ((wb(total=0), "empty_refresh_retained"), (wb("null"), "missing_refresh_retained")):
            with self.subTest(reason=reason):
                cache = SnapshotCache()
                accept(cache, (check(wb()),))
                before = label(cache, "gdp_growth_world").observation
                later = NOW + timedelta(hours=1)
                result = accept(cache, (check(sample, at=later),), at=later)
                self.assertEqual(result.checks, ())
                self.assertEqual(result.failures[0].reason_code, reason)
                self.assertEqual(label(cache, "gdp_growth_world", later).observation, before)
                self.assertEqual(label(cache, "gdp_growth_world", later).status, "stale")

    def test_cold_empty_dataset_is_unavailable_and_new_missing_period_not_filled(self):
        cache = SnapshotCache()
        accept(cache, (check(wb(total=0)),))
        self.assertEqual(label(cache, "gdp_growth_world").reason_code, "source_dataset_empty")
        cache = SnapshotCache()
        accept(cache, (check(wb("2.5", year="2024")),))
        later = NOW + timedelta(hours=1)
        accept(cache, (check(wb("null", year="2025"), at=later),), at=later)
        latest = label(cache, "gdp_growth_world", later)
        self.assertIsNone(latest.observation.value)
        self.assertEqual(latest.observation.as_of, "2025")
        self.assertFalse(latest.retention_allowed)
        self.assertEqual(len(next(s for s in cache.view(later).history.series if s.series_id == "gdp_growth_world").observations), 2)

    def test_conflict_rejected_on_warm_and_cold_cache(self):
        original = check(trade())
        other_bundle = changed(trade(), "12.50", "13.00")
        registry, key = SourceRegistry.load().with_discovered_release("commerce_trade_pib", "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2324000")
        resource = registry.resolve(key)
        other_bundle = replace(other_bundle, payload=replace(other_bundle.payload, source_id=key, resource_url=resource.url, response_url=resource.url, body=other_bundle.payload.body.replace(b"2323944", b"2324000")))
        conflict = check(other_bundle, normalizer=SourceNormalizer(registry=registry))
        cold = SnapshotCache()
        result = accept(cold, (original, conflict))
        self.assertEqual(len(result.failures), 2)
        self.assertIsNone(label(cold, "exports").observation)
        warm = SnapshotCache()
        accept(warm, (original,))
        later = NOW + timedelta(hours=1)
        result = accept(warm, (replace(conflict, checked_at=later),), at=later)
        self.assertEqual(result.failures[0].reason_code, "conflicting_source_revision")
        self.assertEqual(label(warm, "exports", later).observation.value, Decimal("12.50"))

    def test_recovery_accepts_new_revision_and_clears_active_failure(self):
        cache = SnapshotCache()
        accept(cache, (check(trade()),))
        later = NOW + timedelta(hours=1)
        cache.record_failure(("commerce_trade_pib",), run_id="failed", started=later, finished=later, reason="timeout")
        later += timedelta(hours=1)
        revised = changed(changed(trade(), "15 OCT", "16 OCT"), "12.50", "13.00")
        result = accept(cache, (check(revised, at=later),), at=later)
        self.assertEqual(result.changed, 1)
        self.assertEqual(label(cache, "exports", later).observation.value, Decimal("13.00"))
        self.assertEqual(label(cache, "exports", later).status, "fresh")
        state = cache.view(later).source_states[0]
        self.assertEqual(state.last_success_at, later)
        self.assertIsNotNone(state.last_failure_at)
        self.assertIsNone(state.failure_reason)

    def test_regressed_period_and_incomplete_trade_batch_cannot_refresh_latest(self):
        cache = SnapshotCache()
        accept(cache, (check(wb("2.5", year="2025")),))
        later = NOW + timedelta(hours=1)
        result = accept(cache, (check(wb("2.5", year="2024"), at=later),), at=later)
        self.assertEqual(result.failures[0].reason_code, "observation_period_regressed")
        self.assertEqual(label(cache, "gdp_growth_world", later).observation.as_of, "2025")
        cache = SnapshotCache()
        sample = check(trade())
        accept(cache, (sample,))
        incomplete = replace(sample, batch=type(sample.batch)(source_id=sample.batch.source_id, observations=tuple(p for p in sample.batch.observations if p.series_id == "exports"), coverage="release_only"), checked_at=later)
        result = accept(cache, (incomplete,), at=later)
        self.assertEqual(result.failures[0].reason_code, "incomplete_release_retained")
        self.assertEqual(label(cache, "trade_balance", later).observation.value, Decimal("-4.70"))

    def test_history_and_revision_cache_remain_bounded(self):
        cache = SnapshotCache()
        for year in range(1960, 2010):
            at = NOW + timedelta(seconds=year)
            accept(cache, (check(wb("2.5", year=str(year)), at=at),), at=at)
        self.assertEqual(len(cache._resources), 1)
        self.assertEqual(len(cache._candidates), 48)
        self.assertEqual(min(p.observation_period.start.year for p in cache._candidates), 1962)

    def test_resource_eviction_does_not_discard_an_accepted_batch(self):
        def release_check(number):
            release = str(2400000 + number)
            registry, key = SourceRegistry.load().with_discovered_release("commerce_trade_pib", f"https://www.pib.gov.in/PressReleasePage.aspx?PRID={release}")
            resource = registry.resolve(key)
            fixture = trade()
            payload = replace(fixture.payload, source_id=key, resource_url=resource.url, response_url=resource.url,
                              body=fixture.payload.body.replace(b"2323944", release.encode()))
            return check(replace(fixture, payload=payload), normalizer=SourceNormalizer(registry=registry))
        cache = SnapshotCache()
        first = release_check(0)
        for number in range(32):
            accept(cache, (release_check(number),))
        result = accept(cache, (first, release_check(32)))
        self.assertEqual(len(result.checks), 2)
        self.assertEqual(len(cache._resources), 32)
        self.assertEqual(label(cache, "exports").observation.value, Decimal("12.50"))

    def test_dynamic_registry_fits_cached_releases_plus_max_discovery_setting(self):
        registry = SourceRegistry.load()
        for number in range(6):
            registry, _ = registry.with_discovered_release("commerce_trade_pib", f"https://www.pib.gov.in/PressReleasePage.aspx?PRID={2400000+number}")
        with self.assertRaises(ValueError):
            registry.with_discovered_release("commerce_trade_pib", "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2400006")

    def test_history_failure_and_discovery_failure_have_different_latest_effect(self):
        for resource, expected in (("commerce_trade_pib.history.2026-08", "fresh"), ("pib_release_index", "stale")):
            cache = SnapshotCache()
            accept(cache, (check(trade()),))
            later = NOW + timedelta(hours=1)
            failure = SourceFailure(source_id="commerce_trade_pib", resource_id=resource, reason_code="timeout")
            accept(cache, (check(trade(), at=later),), at=later, failures=(failure,))
            self.assertEqual(label(cache, "exports", later).status, expected)

    def test_failed_m4_transaction_hook_publishes_nothing(self):
        cache = SnapshotCache()
        accept(cache, (check(trade()),))
        before = cache.view(NOW)
        def fail(plan):
            self.assertTrue(plan.resources)
            raise OSError("simulated database commit failure")
        cache.before_commit = fail
        later = NOW + timedelta(hours=1)
        with self.assertRaises(CacheCommitError):
            accept(cache, (check(changed(trade(), "15 OCT", "16 OCT"), at=later),), at=later)
        self.assertEqual(cache.view(NOW), before)

    def test_conditional_without_accepted_snapshot_and_bad_times_cannot_enter_cache(self):
        sample = check(trade())
        conditional = replace(sample, not_modified=True, receipts=tuple(replace(r, outcome="not_modified", body=None) for r in sample.receipts))
        cache = SnapshotCache()
        self.assertEqual(accept(cache, (conditional,)).failures[0].reason_code, "conditional_snapshot_missing")
        with self.assertRaises(ValueError):
            accept(SnapshotCache(), (sample,), at=NOW.replace(tzinfo=None))
        with self.assertRaises(ValueError):
            accept(SnapshotCache(), (sample, sample))

    def test_source_specific_observation_deadlines_and_no_freshness_from_polling_alone(self):
        cases = ((trade, "exports", (2026, 11, 22)), (cpi, "cpi_yoy", (2026, 11, 20)),
                 (expenditure, "expenditure_total", (2026, 11, 7)), (gdp, "gdp_growth_india", (2027, 6, 15)),
                 (wb, "gdp_growth_world", (2027, 9, 30)))
        for fixture, sid, day in cases:
            with self.subTest(sid=sid):
                cache = SnapshotCache()
                sample = check(fixture())
                accept(cache, (sample,))
                point = label(cache, sid).observation
                deadline = publication_deadline(point)
                self.assertEqual((deadline.astimezone(timezone(timedelta(hours=5, minutes=30))).year, deadline.astimezone(timezone(timedelta(hours=5, minutes=30))).month, deadline.astimezone(timezone(timedelta(hours=5, minutes=30))).day), day)
                after = deadline + timedelta(seconds=1)
                refresh = replace(sample, checked_at=after, not_modified=True, receipts=tuple(replace(r, retrieved_at=after, outcome="not_modified", body=None) for r in sample.receipts))
                accept(cache, (refresh,), at=after)
                stale = label(cache, sid, after)
                self.assertEqual(stale.status, "stale")
                self.assertEqual(stale.reason_code, "observation_release_overdue")
                self.assertEqual(stale.observation, point)

    def test_check_overdue_does_not_treat_an_old_annual_period_like_daily_data(self):
        cache = SnapshotCache()
        accept(cache, (check(wb()), check(trade())))
        self.assertEqual(label(cache, "gdp_growth_world", NOW + timedelta(days=1)).status, "fresh")
        self.assertEqual(label(cache, "exports", NOW + timedelta(days=1)).reason_code, "refresh_check_overdue")
        self.assertEqual(label(cache, "gdp_growth_world", NOW + timedelta(days=15)).reason_code, "refresh_check_overdue")
        self.assertEqual(label(cache, "gst_total").status, "unavailable")
        cache.view(NOW).model_dump(mode="json")


class ConditionalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.clock = NOW
        self.calls = []
        self.clients = []
        self.mode = "good"
        self.bundle = wb("2.5")
        self.cache = SnapshotCache()
        self.settings = SchedulerSettings(_env_file=None, state_directory=Path(self.directory.name))
        logger = logging.Logger("test_retention")
        logger.addHandler(logging.NullHandler())
        self.enterContext(patch("app.collectors.runner.LOGGER", logger))

    def factory(self):
        def handler(request):
            metadata = request.url.path == "/v2/indicator/NY.GDP.MKTP.KD.ZG"
            self.calls.append((metadata, dict(request.headers)))
            if self.mode == "fail":
                return httpx.Response(503)
            if self.mode == "invalid":
                return httpx.Response(200, content=b"not JSON", headers={"content-type": "application/json", "etag": '"invalid"'})
            conditional = "if-none-match" in request.headers
            if self.mode == "unchanged" and conditional:
                return httpx.Response(304)
            if self.mode == "mixed" and not metadata and conditional:
                return httpx.Response(304)
            if self.mode == "mixed_reverse" and metadata and conditional:
                return httpx.Response(304)
            body = self.bundle.metadata.body if metadata else self.bundle.payload.body
            tag = ('"new_metadata"' if metadata else '"new_data"') if self.mode == "new" else ('"metadata"' if metadata else '"data"')
            return httpx.Response(200, content=body, headers={"content-type": "application/json", "etag": tag})
        client = CollectorHttpClient(settings=CollectorSettings(_env_file=None, min_interval=0.001, max_attempts=1), transport=httpx.MockTransport(handler), utc_now=lambda: self.clock)
        self.clients.append(client)
        return client

    def runner(self):
        return CollectionRunner(self.settings, client_factory=self.factory, now=lambda: self.clock, cache=self.cache)

    async def test_cross_client_304_reuses_only_accepted_data_without_timestamp_fabrication(self):
        runner = self.runner()
        self.assertEqual((await runner.run(("world_bank_gdp",), trigger="manual")).status, "prepared")
        original = label(self.cache, "gdp_growth_world").observation
        self.mode, self.clock = "unchanged", NOW + timedelta(hours=1)
        result = await runner.run(("world_bank_gdp",), trigger="scheduled")
        self.assertEqual(result.status, "unchanged")
        self.assertEqual(result.unchanged_resources, 1)
        self.assertEqual(label(self.cache, "gdp_growth_world", self.clock).observation, original)
        self.assertEqual(label(self.cache, "gdp_growth_world", self.clock).last_success_at, self.clock)
        self.assertTrue(all("if-none-match" in headers for _, headers in self.calls[-2:]))
        self.assertTrue(all(r.body is None for r in self.cache.get("world_bank_gdp").receipts))

    async def test_both_mixed_data_metadata_directions_refetch_missing_body_once(self):
        runner = self.runner()
        await runner.run(("world_bank_gdp",), trigger="manual")
        for mode in ("mixed", "mixed_reverse"):
            self.mode, self.clock = mode, self.clock + timedelta(hours=1)
            before = len(self.calls)
            self.assertEqual((await runner.run(("world_bank_gdp",), trigger="manual")).status, "unchanged")
            self.assertEqual(len(self.calls) - before, 3)
            self.assertNotIn("if-none-match", self.calls[-1][1])

    async def test_failed_or_malformed_refresh_retains_snapshot_and_old_validators_then_recovers(self):
        runner = self.runner()
        await runner.run(("world_bank_gdp",), trigger="manual")
        original = label(self.cache, "gdp_growth_world").observation
        for mode in ("fail", "invalid"):
            self.mode, self.clock = mode, self.clock + timedelta(hours=1)
            self.assertEqual((await runner.run(("world_bank_gdp",), trigger="scheduled")).status, "failed")
            self.assertEqual(label(self.cache, "gdp_growth_world", self.clock).observation, original)
            self.assertEqual(label(self.cache, "gdp_growth_world", self.clock).status, "stale")
            self.assertEqual(self.cache.get("world_bank_gdp").receipts[0].etag, '"data"')
            self.assertEqual(self.clients[-1]._accepted["world_bank_gdp"][0], '"data"')
        self.mode, self.clock = "unchanged", self.clock + timedelta(hours=1)
        self.assertEqual((await runner.run(("world_bank_gdp",), trigger="scheduled")).status, "unchanged")
        self.assertEqual(label(self.cache, "gdp_growth_world", self.clock).status, "fresh")

    async def test_failed_acceptance_does_not_acknowledge_http_validators(self):
        runner = self.runner()
        await runner.run(("world_bank_gdp",), trigger="manual")
        before = self.cache.get("world_bank_gdp")
        self.bundle = changed(wb("3.5"), "2026-10-08", "2026-10-09")
        def fail(plan):
            raise OSError("database transaction rolled back")
        self.cache.before_commit = fail
        self.mode = "new"
        self.clock += timedelta(hours=1)
        result = await runner.run(("world_bank_gdp",), trigger="manual")
        self.assertEqual(result.reason_code, "snapshot_acceptance_failed")
        self.assertEqual(self.cache.get("world_bank_gdp"), before)
        self.assertEqual(label(self.cache, "gdp_growth_world", self.clock).status, "stale")
        self.assertEqual(self.clients[-1]._accepted["world_bank_gdp"][0], '"data"')


if __name__ == "__main__":
    unittest.main()
