"""Real SQLite ingestion, retry/rollback safety, immutable revisions and restart reload."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import logging
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.collectors.handoff import CollectionEnvelope, RepositoryBridge
from app.collectors.observations import NormalizedBatch
from app.collectors.runner import CollectionRunner
from app.collectors.snapshot_cache import SnapshotCache
from app.config import BACKEND_DIRECTORY, DatabaseSettings, SchedulerSettings
from app.database import Database
from app.repository import RepositoryConflict, SQLiteCollectionRepository
from test_normalization import NOW, changed, cpi, expenditure, gdp, trade, wb
from test_snapshot_cache import check, collection, label


def prepare(*fixtures, previous=None, at=NOW, run_id="first", checks=None):
    plans = []
    cache = SnapshotCache.from_plan(previous.envelope.to_plan()) if previous else SnapshotCache()
    cache.before_commit = plans.append
    checks = checks if checks is not None else tuple(check(f(), at=at) for f in fixtures)
    sources = tuple(dict.fromkeys(c.batch.source_id for c in checks))
    cache.accept(collection(checks), sources, run_id=run_id, started=at, finished=at, trigger="test")
    return CollectionEnvelope.from_plan(plans[-1])


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.database = Database(DatabaseSettings(_env_file=None, app_env="test", directory=self.root / "db"))
        self.database.bootstrap()
        self.repository = SQLiteCollectionRepository(self.database)

    def count(self, table):
        # Test-owned identifiers only.
        with self.database.connection() as connection:
            return connection.execute("SELECT count(*) FROM " + table).fetchone()[0]

    def test_five_sources_commit_exact_data_provenance_bindings_and_restore(self):
        self.assertIsNone(self.repository.load())
        item = prepare(wb, gdp, trade, cpi, expenditure)
        acknowledgement = self.repository.commit(item)
        self.assertTrue(acknowledgement.verifies(item))
        stored = SQLiteCollectionRepository(self.database).load()
        self.assertEqual(stored.envelope, item)
        self.assertEqual(stored.acknowledgement, acknowledgement)
        self.assertEqual(self.count("observations"), len(item.observations))
        self.assertEqual(self.count("requirement_bindings"), 17)
        self.assertEqual(self.count("collector_run_sources"), 5)
        restored = RepositoryBridge(self.repository).open_cache()
        self.assertEqual(label(restored, "gdp_growth_world").observation.value, Decimal("2.123456789012345678"))
        self.assertEqual(label(restored, "trade_balance").observation.value, Decimal("-4.70"))
        self.assertEqual(label(restored, "cpi_yoy").observation.value, Decimal(0))
        self.assertIsNone(label(restored, "gst_total").observation)
        self.assertTrue(all(r.body is None for entry in restored._resources.values() for r in entry.receipts))

    def test_idempotent_retry_and_run_id_conflict_do_not_rewind_checkpoint(self):
        first = prepare(wb)
        ack = self.repository.commit(first)
        self.assertEqual(self.repository.commit(first), ack)
        self.assertEqual(self.count("collector_runs"), 1)
        later = prepare(trade, previous=self.repository.load(), at=NOW + timedelta(hours=1), run_id="second")
        self.repository.commit(later)
        self.assertEqual(self.repository.commit(first), ack)
        self.assertEqual(self.repository.load().envelope, later)
        with self.assertRaises(RepositoryConflict):
            self.repository.commit(first.model_copy(update={"trigger": "different"}))
        self.assertEqual(self.count("collector_runs"), 2)

    def test_atomic_rollback_after_observations_preserves_old_checkpoint(self):
        self.repository.commit(prepare(wb))
        before = self.repository.load()
        later = prepare(trade, previous=before, at=NOW + timedelta(hours=1), run_id="rolled-back")
        with patch.object(self.repository, "_write_states", side_effect=sqlite3.OperationalError("simulated disk failure")):
            with self.assertRaises(sqlite3.OperationalError):
                self.repository.commit(later)
        self.assertEqual(self.repository.load(), before)
        self.assertEqual(self.count("observations"), 1)
        self.assertEqual(self.count("collector_runs"), 1)
        self.assertEqual(self.count("collector_run_sources"), 1)
        self.assertEqual(self.count("source_states"), 1)

    def test_sql_injection_tokens_are_bound_as_data(self):
        token = "x'); DROP TABLE observations; --"
        item = prepare(wb, run_id=token)
        self.repository.commit(item)
        self.assertEqual(self.repository.load().envelope.run_id, token)
        self.assertEqual(self.count("observations"), 1)
        with self.database.connection() as connection:
            self.assertEqual(connection.execute("SELECT trigger FROM collector_runs WHERE run_id=?", (token,)).fetchone()[0], "test")

    def test_invalid_constructed_numeric_definition_and_blocked_source_reject_before_writes(self):
        item = prepare(wb)
        for updates in ({"value": 1.25}, {"value": Decimal("NaN")}, {"definition_id": "wrong"}, {"unit": "inr_crore"}):
            point = item.observations[0].model_copy(update=updates)
            candidate = item.model_copy(update={"observations": (point,)})
            with self.subTest(updates=repr(updates)), self.assertRaises((ValueError, ValidationError)):
                self.repository.commit(candidate)
        blocked = item.model_copy(update={"source_ids": ("nse_indices",)})
        with self.assertRaises(ValueError):
            self.repository.commit(blocked)
        self.assertEqual(self.count("collector_runs"), 0)
        self.assertEqual(self.count("sources"), 0)

    def test_stale_writer_cannot_erase_another_sources_checkpoint(self):
        first, stale = prepare(wb), prepare(trade, at=NOW + timedelta(hours=1), run_id="stale")
        self.repository.commit(first)
        with self.assertRaises(RepositoryConflict):
            self.repository.commit(stale)
        merged = prepare(trade, previous=self.repository.load(), at=NOW + timedelta(hours=1), run_id="merged")
        self.repository.commit(merged)
        self.assertEqual(len(self.repository.load().envelope.source_states), 2)

    def test_failure_event_is_durable_and_preserves_last_good_and_validators(self):
        self.repository.commit(prepare(wb))
        cache = RepositoryBridge(self.repository).open_cache()
        original = label(cache, "gdp_growth_world").observation
        receipts = cache.get("world_bank_gdp").receipts
        later = NOW + timedelta(hours=1)
        self.assertTrue(cache.record_failure(("world_bank_gdp",), run_id="failure", started=later, finished=later, reason="timeout"))
        restored = RepositoryBridge(SQLiteCollectionRepository(self.database)).open_cache()
        state = label(restored, "gdp_growth_world", later)
        self.assertEqual(state.observation, original)
        self.assertEqual(state.status, "stale")
        self.assertEqual(restored.get("world_bank_gdp").receipts, receipts)
        self.assertEqual(self.count("observations"), 1)

    def test_database_failure_keeps_runtime_overlay_uncommitted(self):
        self.repository.commit(prepare(wb))
        cache = RepositoryBridge(self.repository).open_cache()
        before = self.repository.load()
        later = NOW + timedelta(hours=1)
        with patch.object(self.repository, "_write_states", side_effect=sqlite3.OperationalError("unavailable")):
            self.assertFalse(cache.record_failure(("world_bank_gdp",), run_id="failed-write", started=later, finished=later, reason="timeout"))
        self.assertEqual(label(cache, "gdp_growth_world", later).status, "stale")
        self.assertEqual(self.repository.load(), before)

    def test_first_failed_run_persists_unavailable_without_invented_observations(self):
        cache = RepositoryBridge(self.repository).open_cache()
        self.assertTrue(cache.record_failure(("world_bank_gdp",), run_id="first-failure", started=NOW, finished=NOW, reason="timeout"))
        restored = RepositoryBridge(self.repository).open_cache()
        self.assertEqual(label(restored, "gdp_growth_world").status, "unavailable")
        self.assertEqual(self.count("observations"), 0)
        self.assertEqual(self.count("requirement_bindings"), 17)

    def test_missing_refresh_cannot_overwrite_durable_last_good(self):
        self.repository.commit(prepare(wb))
        item = prepare(lambda: wb("null"), previous=self.repository.load(), at=NOW + timedelta(hours=1), run_id="missing-refresh")
        self.repository.commit(item)
        restored = RepositoryBridge(self.repository).open_cache()
        self.assertEqual(label(restored, "gdp_growth_world", NOW + timedelta(hours=1)).status, "stale")
        self.assertEqual(label(restored, "gdp_growth_world").observation.value, Decimal("2.123456789012345678"))
        self.assertEqual(self.count("observations"), 1)

    def test_null_then_valid_and_publisher_revisions_preserve_history(self):
        self.repository.commit(prepare(lambda: wb("null")))
        # New dataset edition can fill a genuinely missing observation.
        revised = lambda: changed(wb("0"), "2026-10-08", "2026-10-09")
        second = prepare(revised, previous=self.repository.load(), at=NOW + timedelta(hours=1), run_id="valid")
        self.repository.commit(second)
        self.assertEqual(self.count("observations"), 2)
        self.assertEqual(label(RepositoryBridge(self.repository).open_cache(), "gdp_growth_world").observation.value, Decimal(0))

    def test_archive_keeps_values_outside_bounded_checkpoint(self):
        sample = check(wb())
        from app.collectors.normalization import SourceNormalizer
        normalizer = SourceNormalizer()
        points = tuple(normalizer.parse(wb(year=str(year))).observations[0] for year in range(1970, 2019))
        resource = replace(sample, batch=NormalizedBatch(source_id="world_bank_gdp", observations=points, coverage="bounded_page"))
        item = prepare(checks=(resource,))
        self.assertEqual(len(item.observations), 48)
        self.repository.commit(item)
        self.assertEqual(self.count("observations"), 49)
        # A later failure/omitted historical point never deletes its archived SQL row.
        cache = RepositoryBridge(self.repository).open_cache()
        at = NOW + timedelta(hours=1)
        self.assertTrue(cache.record_failure(("world_bank_gdp",), run_id="archive-retained", started=at, finished=at, reason="timeout"))
        self.assertEqual(self.count("observations"), 49)

    def test_conflicting_archived_vintage_cannot_be_reintroduced_after_ram_eviction(self):
        first_vintage = None
        for index in range(4):
            factory = lambda i=index: changed(wb(str(i + 2)), "2026-10-08", f"2026-10-{8+i:02}")
            item = prepare(factory, previous=self.repository.load(), at=NOW + timedelta(hours=index), run_id=f"revision-{index}")
            first_vintage = first_vintage or item.observations[0].vintage_id
            self.repository.commit(item)
        self.assertEqual(len(self.repository.load().envelope.observations), 3)
        self.assertEqual(self.count("observations"), 4)
        resource = check(changed(wb("99"), "2026-10-08", "2026-10-12"), at=NOW + timedelta(hours=5))
        malicious = resource.batch.observations[0].model_copy(update={"vintage_id": first_vintage})
        resource = replace(resource, batch=resource.batch.model_copy(update={"observations": (malicious,)}))
        item = prepare(previous=self.repository.load(), at=NOW + timedelta(hours=5), run_id="conflict", checks=(resource,))
        with self.assertRaises(RepositoryConflict):
            self.repository.commit(item)
        self.assertEqual(self.count("observations"), 4)
        self.assertEqual(self.repository.load().envelope.run_id, "revision-3")

    def test_tampered_sql_archive_or_checkpoint_fails_closed(self):
        self.repository.commit(prepare(wb))
        with self.database.transaction() as connection:
            connection.execute("UPDATE observations SET value_decimal=?", ("9",))
        with self.assertRaises(RepositoryConflict):
            self.repository.load()

    def test_malformed_checkpoint_and_catalog_drift_fail_without_overwrite(self):
        item = prepare(wb)
        self.repository.commit(item)
        next_item = prepare(trade, previous=self.repository.load(), at=NOW + timedelta(hours=1), run_id="new")
        with self.database.transaction() as connection:
            connection.execute("UPDATE sources SET name=? WHERE source_id=?", ("unexpected", "world_bank_gdp"))
        with self.assertRaises(RepositoryConflict):
            self.repository.commit(next_item)
        self.assertEqual(self.count("collector_runs"), 1)
        with self.database.transaction() as connection:
            connection.execute("UPDATE collector_runs SET envelope_json=?", ('{"invalid":true}',))
        with self.assertRaises(ValidationError):
            self.repository.load()

    def test_new_process_reloads_checkpoint_without_upstream_http(self):
        self.repository.commit(prepare(wb))
        code = """
import sys
from pathlib import Path
from unittest.mock import patch
from app.config import DatabaseSettings
from app.database import Database
from app.repository import SQLiteCollectionRepository
from app.collectors.handoff import RepositoryBridge
with patch('socket.socket', side_effect=AssertionError('No network during reload')):
 db=Database(DatabaseSettings(_env_file=None,app_env='test',directory=Path(sys.argv[1])))
 db.bootstrap()
 cache=RepositoryBridge(SQLiteCollectionRepository(db)).open_cache()
 assert str(cache._candidates[0].value)=='2.123456789012345678'
 assert cache.get('world_bank_gdp').receipts[0].body is None
"""
        result = subprocess.run([sys.executable, "-c", code, str(self.database.settings.directory)], cwd=BACKEND_DIRECTORY,
                                env=os.environ.copy(), capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


class RunnerRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_sql_transaction_never_advances_http_validators(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database = Database(DatabaseSettings(_env_file=None, directory=root / "db"))
            database.bootstrap()
            repository = SQLiteCollectionRepository(database)
            settings = SchedulerSettings(_env_file=None, state_directory=root / "locks")
            seen = []
            class Client:
                async def __aenter__(self):
                    return self
                async def __aexit__(self, *args):
                    pass
                def acknowledge(self, receipt):
                    seen.append(receipt)
            async def collect(*args, **kwargs):
                return collection((check(wb()),))
            runner = CollectionRunner(settings, repository=repository, client_factory=Client, collect=collect, now=lambda: NOW)
            logger = logging.Logger("silent-failed-test")
            logger.addHandler(logging.NullHandler())
            with patch.object(repository, "_write_states", side_effect=sqlite3.OperationalError("disk failed")), patch("app.collectors.runner.LOGGER", logger):
                result = await runner.run(("world_bank_gdp",), trigger="test")
            self.assertEqual(result.status, "failed")
            self.assertFalse(result.persisted)
            self.assertEqual(seen, [])
            self.assertIsNone(repository.load())

    async def test_commit_precedes_http_ack_and_preexisting_runner_reloads_other_process_commit(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database = Database(DatabaseSettings(_env_file=None, directory=root / "db"))
            database.bootstrap()
            repository = SQLiteCollectionRepository(database)
            settings = SchedulerSettings(_env_file=None, state_directory=root / "locks")
            seen = []
            class Client:
                async def __aenter__(self):
                    return self
                async def __aexit__(self, *args):
                    pass
                def acknowledge(self, receipt):
                    assert repository.load() is not None
                    seen.append(receipt.source_id)
            async def collect(*args, **kwargs):
                # The runner was constructed before another command committed World GDP.
                self.assertIsNotNone(kwargs["cache"].get("world_bank_gdp"))
                return collection((check(trade(), at=NOW + timedelta(hours=1)),))
            runner = CollectionRunner(settings, repository=repository, client_factory=Client, collect=collect,
                                      now=lambda: NOW + timedelta(hours=1))
            repository.commit(prepare(wb))
            logger = logging.Logger("silent-test")
            logger.addHandler(logging.NullHandler())
            with patch("app.collectors.runner.LOGGER", logger):
                result = await runner.run(("commerce_trade_pib",), trigger="test")
            self.assertTrue(result.persisted)
            self.assertEqual(result.cache_scope, "repository_checkpoint")
            self.assertEqual(seen, ["commerce_trade_pib"])
            restored = RepositoryBridge(repository).open_cache()
            self.assertIsNotNone(restored.get("world_bank_gdp"))
            self.assertIsNotNone(restored.get("commerce_trade_pib"))


if __name__ == "__main__":
    unittest.main()
