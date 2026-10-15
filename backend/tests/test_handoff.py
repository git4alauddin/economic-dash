"""M4 protocol doubles only: these tests do not establish SQL/API durability."""

from datetime import timedelta
from decimal import Decimal
import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.collectors.handoff import (
    CollectionEnvelope, CommitAcknowledgement, RepositoryBridge, StoredCheckpoint,
)
from app.collectors.runner import CollectionRunner
from app.collectors.snapshot_cache import SnapshotCache
from app.config import SchedulerSettings
from test_normalization import NOW, cpi, expenditure, gdp, trade, wb
from test_snapshot_cache import accept, check, collection, label
from test_scheduler import FakeClient


def envelope(fixtures=(wb,)):
    plans = []
    cache = SnapshotCache(before_commit=plans.append)
    accept(cache, tuple(check(f()) for f in fixtures))
    return CollectionEnvelope.from_plan(plans[-1])


class RepositoryDouble:
    """In-memory simulation of M4 acknowledgements, NEVER a production backend."""
    def __init__(self):
        self.checkpoint = None
        self.commits = {}
        self.fail = False
        self.mismatch = False

    def load(self):
        return self.checkpoint

    def commit(self, item):
        if self.fail:
            raise OSError("simulated SQL transaction failure")
        if item.run_id in self.commits:
            previous = self.commits[item.run_id]
            if previous.envelope_digest != item.digest:
                raise ValueError("run ID reused with different content")
            return previous
        acknowledgement = CommitAcknowledgement(run_id=item.run_id, envelope_digest=item.digest,
                                                 repository_version=f"test-double-{len(self.commits)+1}")
        if self.mismatch:
            return acknowledgement.model_copy(update={"envelope_digest": "wrong"})
        self.commits[item.run_id] = acknowledgement
        self.checkpoint = StoredCheckpoint(envelope=item, acknowledgement=acknowledgement)
        return acknowledgement


class HandoffTests(unittest.TestCase):
    def test_lossless_json_round_trip_preserves_decimals_periods_and_unknown_publication(self):
        item = envelope()
        restored = CollectionEnvelope.model_validate_json(item.model_dump_json())
        self.assertEqual(restored, item)
        self.assertEqual(restored.digest, item.digest)
        point = restored.observations[0]
        self.assertEqual(point.value, Decimal("2.123456789012345678"))
        self.assertEqual(point.as_of, "2025")
        self.assertIsNone(point.published_at)
        self.assertEqual(restored.source_ids, ("world_bank_gdp",))
        self.assertEqual(json.loads(item.model_dump_json())["observations"][0]["value"], "2.123456789012345678")

    def test_acceptance_may_follow_the_upstream_check_before_reload(self):
        plans = []
        cache = SnapshotCache(before_commit=plans.append)
        cache.accept(collection((check(wb()),)), ("world_bank_gdp",), run_id="delayed-acceptance",
                     started=NOW - timedelta(seconds=1), finished=NOW + timedelta(seconds=30))
        item = CollectionEnvelope.from_plan(plans[-1])
        resource = item.resources[0]
        self.assertGreater(resource.accepted_at, resource.checked_at)
        restored = SnapshotCache.from_plan(CollectionEnvelope.model_validate_json(item.model_dump_json()).to_plan())
        self.assertEqual(label(restored, "gdp_growth_world", NOW + timedelta(seconds=30)).status, "fresh")

    def test_floats_noncanonical_strings_extra_payload_fields_and_unknown_versions_rejected(self):
        base = json.loads(envelope().model_dump_json())
        for value in (2.5, 2, True, "NaN", "Infinity", "1e2", "-", "+1.2", "1,000", "01"):
            data = json.loads(json.dumps(base))
            data["observations"][0]["value"] = value
            with self.subTest(value=value), self.assertRaises(ValidationError):
                CollectionEnvelope.model_validate_json(json.dumps(data))
        for changes in ({"contract_version": "v999"}, {"parser_version": "other"}, {"catalog_fingerprint": "wrong"}, {"operation": "replace"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                CollectionEnvelope.model_validate_json(json.dumps(base | changes))
        data = json.loads(json.dumps(base))
        data["resources"][0]["receipts"][0]["body"] = "forbidden upstream payload"
        with self.assertRaises(ValidationError):
            CollectionEnvelope.model_validate_json(json.dumps(data))

    def test_all_five_sources_and_seventeen_requirements_share_contract(self):
        item = envelope((wb, gdp, trade, cpi, expenditure))
        restored = CollectionEnvelope.model_validate_json(item.model_dump_json())
        self.assertEqual(len(restored.source_ids), 5)
        self.assertEqual(len(restored.requirements), 17)
        self.assertEqual(sum(r.status == "blocked" for r in restored.requirements), 8)
        self.assertEqual(len({p.series_id for p in restored.observations}), 8)
        cache = SnapshotCache.from_plan(restored.to_plan())
        view = cache.view(NOW)
        self.assertEqual(sum(s.observation is not None for s in view.freshness), 9)
        self.assertEqual(label(cache, "trade_balance").observation.value, Decimal("-4.70"))
        self.assertTrue(all(r.body is None for e in cache._resources.values() for r in e.receipts))

    def test_zero_null_and_fiscal_periods_survive_reload(self):
        item = envelope((lambda: wb("0"), gdp, expenditure))
        cache = SnapshotCache.from_plan(CollectionEnvelope.model_validate_json(item.model_dump_json()).to_plan())
        self.assertEqual(label(cache, "gdp_growth_world").observation.value, 0)
        self.assertEqual(label(cache, "gdp_growth_india").observation.observation_period.id, "FY2025-26")
        self.assertEqual(label(cache, "expenditure_total").observation.observation_period.id, "FY2026-27:2026-08")
        missing = envelope((lambda: wb("null"),))
        cache = SnapshotCache.from_plan(CollectionEnvelope.model_validate_json(missing.model_dump_json()).to_plan())
        self.assertEqual(label(cache, "gdp_growth_world").status, "unavailable")
        self.assertIsNone(label(cache, "gdp_growth_world").observation.value)

    def test_scope_blockers_and_source_state_timestamps_cannot_be_tampered(self):
        base = json.loads(envelope().model_dump_json())
        for field, value in (("source_ids", ["nse_indices"]), ("requirements", base["requirements"][:-1]), ("finished_at", "2020-01-01T00:00:00Z")):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                CollectionEnvelope.model_validate_json(json.dumps(base | {field: value}))
        data = json.loads(json.dumps(base))
        data["source_states"][0]["last_checked_at"] = "2026-10-16T13:00:00+05:30"
        with self.assertRaises(ValidationError):
            CollectionEnvelope.model_validate_json(json.dumps(data))

    def test_resource_and_observation_revisions_cannot_disagree_or_misattribute_source(self):
        base = json.loads(envelope().model_dump_json())
        data = json.loads(json.dumps(base))
        data["observations"][0]["value"] = "3.5"
        with self.assertRaises(ValidationError):
            CollectionEnvelope.model_validate_json(json.dumps(data))
        for field, value in (("is_nse", True), ("url", "https://unreviewed.example/data")):
            data = json.loads(json.dumps(base))
            data["observations"][0]["sources"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValidationError):
                CollectionEnvelope.model_validate_json(json.dumps(data))

    def test_acknowledgement_is_bound_to_run_content_and_repository_version(self):
        item = envelope()
        repo = RepositoryDouble()
        acknowledgement = repo.commit(item)
        self.assertTrue(acknowledgement.verifies(item))
        self.assertEqual(repo.commit(item), acknowledgement)
        altered = item.model_copy(update={"trigger": "different"})
        with self.assertRaises(ValueError):
            repo.commit(altered)
        with self.assertRaises(ValidationError):
            StoredCheckpoint(envelope=item, acknowledgement=acknowledgement.model_copy(update={"run_id": "other"}))
        with self.assertRaises(ValidationError):
            CommitAcknowledgement(run_id=item.run_id, envelope_digest=item.digest, repository_version="v1", durable=False)

    def test_failure_event_uses_same_contract_and_reload_preserves_last_good(self):
        repo = RepositoryDouble()
        bridge = RepositoryBridge(repo)
        cache = bridge.open_cache()
        accept(cache, (check(wb()),))
        original = label(cache, "gdp_growth_world").observation
        later = NOW + timedelta(hours=1)
        self.assertTrue(cache.record_failure(("world_bank_gdp",), run_id="failure", started=later, finished=later, reason="timeout", trigger="scheduled"))
        self.assertEqual(repo.checkpoint.envelope.run_id, "failure")
        restored = RepositoryBridge(repo).open_cache()
        self.assertEqual(label(restored, "gdp_growth_world", later).observation, original)
        self.assertEqual(label(restored, "gdp_growth_world", later).status, "stale")
        self.assertEqual(label(restored, "gdp_growth_world", later).reason_code, "timeout")

    def test_database_failure_keeps_runtime_failure_overlay_without_claiming_commit(self):
        repo = RepositoryDouble()
        bridge = RepositoryBridge(repo)
        cache = bridge.open_cache()
        accept(cache, (check(wb()),))
        committed = repo.checkpoint
        repo.fail = True
        later = NOW + timedelta(hours=1)
        self.assertFalse(cache.record_failure(("world_bank_gdp",), run_id="failed-write", started=later, finished=later, reason="database_unavailable"))
        self.assertIsNone(bridge.last_acknowledgement)
        self.assertEqual(repo.checkpoint, committed)
        self.assertEqual(label(cache, "gdp_growth_world", later).status, "stale")


class RunnerHandoffTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.clock = NOW
        self.settings = SchedulerSettings(_env_file=None, state_directory=Path(self.directory.name))
        logger = logging.Logger("test_handoff")
        logger.addHandler(logging.NullHandler())
        self.enterContext(patch("app.collectors.runner.LOGGER", logger))

    def runner(self, repository):
        async def collected(*args, **kwargs):
            return collection((check(wb(), at=self.clock),))
        return CollectionRunner(self.settings, repository=repository, client_factory=FakeClient,
                                collect=collected, now=lambda: self.clock)

    async def test_commit_acknowledged_before_http_validators_and_reload_fetches_nothing(self):
        repo = RepositoryDouble()
        runner = self.runner(repo)
        acknowledged = []
        class Client(FakeClient):
            def acknowledge(self, receipt):
                assert repo.checkpoint is not None
                acknowledged.append(receipt.source_id)
        runner.client_factory = Client
        result = await runner.run(("world_bank_gdp",), trigger="manual")
        self.assertTrue(result.persisted)  # Simulated M4 acknowledgement only.
        self.assertEqual(acknowledged, ["world_bank_gdp", "world_bank_gdp.metadata"])
        restored = self.runner(repo)
        self.assertEqual(label(restored.cache, "gdp_growth_world").observation, label(runner.cache, "gdp_growth_world").observation)
        self.assertEqual(len(repo.commits), 1)

    async def test_wrong_acknowledgement_never_publishes_data_or_http_validators(self):
        repo = RepositoryDouble()
        repo.mismatch = True
        runner = self.runner(repo)
        class Client(FakeClient):
            def acknowledge(self, receipt):
                raise AssertionError("Unacknowledged data must not advance HTTP validators")
        runner.client_factory = Client
        result = await runner.run(("world_bank_gdp",), trigger="manual")
        self.assertFalse(result.persisted)
        self.assertEqual(result.reason_code, "snapshot_acceptance_failed")
        self.assertIsNone(label(runner.cache, "gdp_growth_world").observation)


if __name__ == "__main__":
    unittest.main()
