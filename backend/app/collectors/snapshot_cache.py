"""Atomic, bounded memory acceptance; M4 supplies durable transactional storage."""

from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import inspect
import json
from types import MappingProxyType
from urllib.parse import urlsplit

from .catalog import CATALOG_PATH, SourceRegistry, validate_url
from .freshness import SourceState, SeriesFreshness, freshness
from .history import HistoryCollection, HistorySnapshot, ResourceCheck, SourceFailure, _resolve, build_history
from .http_client import FetchResult
from .observations import ImmutableModel, NormalizedBatch, NormalizedObservation


def fingerprint(batch: NormalizedBatch) -> str:
    data = batch.model_dump(mode="json")
    for point in data["observations"]:
        point.pop("vintage_id")
        point.pop("retrieved_at")
    # HTML counters/whitespace change raw hashes without changing observations.
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class AcceptedResource:
    resource_id: str
    batch: NormalizedBatch
    receipts: tuple[FetchResult, ...]  # Body-free, accepted validators only.
    accepted_at: datetime
    checked_at: datetime


class RetainedSnapshot(ImmutableModel):
    scope: str = "process_memory"
    history: HistorySnapshot
    freshness: tuple[SeriesFreshness, ...]
    source_states: tuple[SourceState, ...]


@dataclass(frozen=True)
class CachePlan:
    resources: Mapping[str, AcceptedResource]
    candidates: tuple[NormalizedObservation, ...]
    states: tuple[SourceState, ...]
    failures: tuple[SourceFailure, ...]
    run_id: str
    source_ids: tuple[str, ...] = ()
    started_at: datetime | None = None
    finished_at: datetime | None = None
    trigger: str = "unspecified"


@dataclass(frozen=True)
class Acceptance:
    checks: tuple[ResourceCheck, ...]
    failures: tuple[SourceFailure, ...]
    changed: int
    unchanged: int


class CacheCommitError(Exception):
    pass


def _batches(points: tuple[NormalizedObservation, ...]) -> tuple[NormalizedBatch, ...]:
    # One-point batches keep revisions separate without duplicate logical keys.
    return tuple(NormalizedBatch(source_id=p.sources[0].source_id, observations=(p,), coverage="release_only") for p in points)


def _bounded(points) -> tuple[NormalizedObservation, ...]:
    grouped = defaultdict(dict)
    for point in points:
        key = point.series_id, point.observation_period.id
        token = point.model_dump_json(exclude={"retrieved_at"})
        grouped[key][token] = point
    by_series = defaultdict(list)
    for key, candidates in grouped.items():
        by_series[key[0]].append((key, list(candidates.values())))
    retained = []
    for groups in by_series.values():
        # 48 observed periods and 3 revisions per key bound RAM; M4 owns archival history.
        for _, candidates in sorted(groups, key=lambda item: item[1][0].observation_period.end)[-48:]:
            ordered = sorted(candidates, key=lambda p: (p.published_at.isoformat() if p.published_at else (p.dataset_updated_at.isoformat() if p.dataset_updated_at else ""), p.retrieved_at, p.vintage_id))
            retained.extend(ordered[-3:])
    return tuple(sorted(retained, key=lambda p: (p.series_id, p.observation_period.end, p.vintage_id)))


class SnapshotCache:
    def __init__(self, *, before_commit: Callable[[CachePlan], None] | None = None):
        # M4's synchronous transaction hook must return only after durable commit.
        # A hook failure publishes neither memory changes nor HTTP validators.
        self.before_commit = before_commit
        self._resources: dict[str, AcceptedResource] = {}
        self._candidates: tuple[NormalizedObservation, ...] = ()
        self._states: dict[str, SourceState] = {}
        self._failures: dict[str, tuple[SourceFailure, ...]] = {}

    def _commit(self, plan: CachePlan) -> None:
        if self.before_commit:
            try:
                result = self.before_commit(plan)
                if inspect.isawaitable(result):
                    if inspect.iscoroutine(result):
                        result.close()
                    raise TypeError("The M4 transaction hook must be synchronous.")
            except Exception as error:
                raise CacheCommitError("Snapshot acceptance failed.") from error

    @classmethod
    def from_plan(cls, plan: CachePlan) -> "SnapshotCache":
        """Reload a validated M4 checkpoint without committing or fetching again."""
        cache = cls()
        if plan.finished_at is None:
            raise ValueError("Checkpoint timestamp is required.")
        for key, entry in plan.resources.items():
            # Acceptance follows parsing/transaction work; it can be later than
            # the HTTP check. A later revalidation can reverse that ordering.
            if key != entry.resource_id or entry.accepted_at > plan.finished_at or entry.checked_at > plan.finished_at or any(r.body is not None for r in entry.receipts):
                raise ValueError("Invalid accepted-resource checkpoint.")
            reason = cache._check(ResourceCheck(key, entry.batch, entry.receipts, entry.checked_at), plan.finished_at)
            if reason:
                raise ValueError(reason)
        points = _bounded(plan.candidates)
        if len(points) != len(plan.candidates):
            raise ValueError("Checkpoint exceeds bounded observation/revision limits.")
        groups = defaultdict(list)
        for point in points:
            groups[point.series_id, point.observation_period.id].append(point)
        if any(_resolve(candidates)[2] for candidates in groups.values()):
            raise ValueError("Checkpoint contains unresolved revisions.")
        build_history(_batches(points))
        cache._resources, cache._candidates = dict(plan.resources), points
        cache._states = {state.source_id: state for state in plan.states}
        cache._failures = {source: tuple(f for f in plan.failures if f.source_id == source) for source in cache._states}
        return cache

    def get(self, resource_id: str) -> AcceptedResource | None:
        return self._resources.get(resource_id)

    def source_states(self) -> tuple[SourceState, ...]:
        return tuple(self._states.values())

    def seed(self, client, sources: tuple[str, ...]) -> None:
        for source in sources:
            dynamic = [entry for entry in self._resources.values() if entry.resource_id.startswith(f"{source}.release.")]
            for entry in sorted(dynamic, key=lambda e: (max(p.observation_period.end for p in e.batch.observations), e.checked_at), reverse=True)[:2]:
                client.register_discovered_release(source, entry.receipts[0].resource_url)
        for entry in self._resources.values():
            for receipt in entry.receipts:
                if receipt.source_id in client.registry.resources:
                    client.seed_validators(receipt)

    def _check(self, check: ResourceCheck, now: datetime) -> str | None:
        previous = self.get(check.resource_id)
        if check.checked_at.utcoffset() != timedelta(0) or check.checked_at > now or (previous and check.checked_at < previous.checked_at):
            return "invalid_check_timestamp"
        if not check.receipts or check.receipts[0].source_id != check.resource_id:
            return "cache_receipt_mismatch"
        source = check.batch.source_id
        registry = SourceRegistry.load()
        if check.resource_id.startswith(f"{source}.release."):
            registry, _ = registry.with_discovered_release(source, check.receipts[0].resource_url)
        if check.resource_id not in registry.observation_resources(source):
            return "cache_resource_mismatch"
        expected = (check.resource_id,) + ((f"{source}.metadata",) if f"{source}.metadata" in registry.resources else ())
        if tuple(r.source_id for r in check.receipts) != expected or any(r.resource_url != registry.resolve(r.source_id).url or r.retrieved_at.utcoffset() != timedelta(0) or r.retrieved_at > check.checked_at for r in check.receipts):
            return "cache_receipt_mismatch"
        if any(urlsplit(validate_url(r.response_url)).hostname != urlsplit(r.resource_url).hostname for r in check.receipts):
            return "cache_receipt_mismatch"
        if check.not_modified:
            if previous is None or check.batch != previous.batch or any(r.outcome != "not_modified" for r in check.receipts):
                return "conditional_snapshot_missing"
        elif any(r.outcome != "modified" for r in check.receipts):
            return "conditional_batch_not_validated"
        elif any(p.sources[0].url != check.receipts[0].response_url for p in check.batch.observations):
            return "cache_receipt_mismatch"
        build_history((check.batch,))  # Reassert selected definitions/source gate.
        definitions = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))["requirements"]
        expected_series = {sid for sid, definition in definitions.items() if definition["source_id"] == source and definition["status"] == "selected"}
        per_period = defaultdict(set)
        for point in check.batch.observations:
            per_period[point.observation_period.id].add(point.series_id)
        if any(series != expected_series for series in per_period.values()):
            return "incomplete_release_retained"
        if previous and previous.batch.observations and check.batch.observations and max(p.observation_period.end for p in check.batch.observations) < max(p.observation_period.end for p in previous.batch.observations):
            return "observation_period_regressed"
        source_points = [p for p in self._candidates if p.sources[0].source_id == source and p.value is not None]
        if not check.batch.observations and source_points:
            return "empty_refresh_retained"
        valid_keys = {(p.series_id, p.observation_period.id) for p in source_points}
        if any(p.value is None and (p.series_id, p.observation_period.id) in valid_keys for p in check.batch.observations):
            return "missing_refresh_retained"
        return None

    def accept(self, collection: HistoryCollection, sources: tuple[str, ...], *, run_id: str, started: datetime, finished: datetime, trigger: str = "unspecified") -> Acceptance:
        if started.utcoffset() != timedelta(0) or finished.utcoffset() != timedelta(0) or finished < started:
            raise ValueError("Cache acceptance requires ordered UTC run times.")
        if len({c.resource_id for c in collection.checks}) != len(collection.checks):
            raise ValueError("Duplicate resource checks require resolution before acceptance.")
        if any(f.source_id not in sources for f in collection.snapshot.failures):
            raise ValueError("Failure scope must match the requested sources.")
        checks, failures = [], list(collection.snapshot.failures)
        for check in collection.checks:
            if check.batch.source_id not in sources:
                raise ValueError("Acceptance cannot alter unrequested sources.")
            reason = self._check(check, finished)
            if reason:
                failures.append(SourceFailure(source_id=check.batch.source_id, resource_id=check.resource_id, reason_code=reason))
            else:
                checks.append(check)
        # Resolve all candidates together. On a cold cache, two conflicting pages
        # cannot establish a last-good value merely by arriving in a lucky order.
        groups = defaultdict(list)
        for point in self._candidates + tuple(p for c in checks for p in c.batch.observations):
            groups[point.series_id, point.observation_period.id].append(point)
        conflicts = {}
        for key, candidates in groups.items():
            reason = _resolve(candidates)[2]
            if reason:
                conflicts[key] = reason
        safe = []
        for check in checks:
            reason = next((conflicts[(p.series_id, p.observation_period.id)] for p in check.batch.observations if (p.series_id, p.observation_period.id) in conflicts), None)
            if reason:
                failures.append(SourceFailure(source_id=check.batch.source_id, resource_id=check.resource_id, reason_code=reason))
            else:
                safe.append(check)
        resources = dict(self._resources)
        changed_by_source, unchanged_by_source = defaultdict(int), defaultdict(int)
        accepted_points = []
        for check in safe:
            previous = resources.get(check.resource_id)
            unchanged = previous is not None and fingerprint(previous.batch) == fingerprint(check.batch)
            accepted_batch = previous.batch if unchanged else check.batch
            (unchanged_by_source if unchanged else changed_by_source)[check.batch.source_id] += 1
            receipts = previous.receipts if check.not_modified else tuple(replace(r, body=None) for r in check.receipts)
            resources[check.resource_id] = AcceptedResource(check.resource_id, accepted_batch, receipts,
                                                          previous.accepted_at if unchanged else finished, check.checked_at)
            accepted_points.extend(accepted_batch.observations)
        for source in sources:
            entries = [e for e in resources.values() if e.batch.source_id == source]
            for old in sorted(entries, key=lambda e: e.checked_at)[:-32]:
                resources.pop(old.resource_id)
        points = _bounded(self._candidates + tuple(accepted_points))
        states = dict(self._states)
        failure_map = dict(self._failures)
        for source in sources:
            old = states.get(source, SourceState(source_id=source))
            source_checks = [c for c in safe if c.batch.source_id == source]
            errors = tuple(f for f in failures if f.source_id == source)
            critical = [f for f in errors if not f.resource_id.startswith(f"{source}.history.")]
            current_checked = any(not c.resource_id.startswith(f"{source}.history.") for c in source_checks)
            success = current_checked and not critical
            outcome = ("partial" if source_checks else "failed") if errors else ("updated" if changed_by_source[source] else "unchanged")
            if source_checks and all(not c.batch.observations for c in source_checks) and not errors:
                outcome = "empty"
            states[source] = SourceState(source_id=source, run_id=run_id, outcome=outcome,
                                         last_attempt_at=started, last_checked_at=finished,
                                         last_success_at=finished if success else old.last_success_at,
                                         last_changed_at=finished if changed_by_source[source] else old.last_changed_at,
                                         last_failure_at=finished if errors else old.last_failure_at,
                                         failure_reason=critical[0].reason_code if critical else (None if success else old.failure_reason))
            failure_map[source] = errors
        plan = CachePlan(MappingProxyType(resources), points, tuple(states.values()), tuple(f for errors in failure_map.values() for f in errors), run_id, sources, started, finished, trigger)
        self._commit(plan)
        self._resources, self._candidates, self._states, self._failures = resources, points, states, failure_map
        return Acceptance(tuple(safe), tuple(failures), sum(changed_by_source.values()), sum(unchanged_by_source.values()))

    def record_failure(self, sources: tuple[str, ...], *, run_id: str, started: datetime, finished: datetime, reason: str, trigger: str = "unspecified") -> bool:
        if started.utcoffset() != timedelta(0) or finished.utcoffset() != timedelta(0) or finished < started:
            raise ValueError("Failure events require ordered UTC run times.")
        if not sources or len(set(sources)) != len(sources) or any(source not in SourceRegistry.load().source_ids for source in sources):
            raise ValueError("Failure events require unique, selected sources.")
        states, failures = dict(self._states), dict(self._failures)
        for source in sources:
            old = self._states.get(source, SourceState(source_id=source))
            fields = old.model_dump() | dict(run_id=run_id, outcome="failed", last_attempt_at=started,
                                            last_checked_at=finished, last_failure_at=finished, failure_reason=reason)
            states[source] = SourceState(**fields)
            failures[source] = (SourceFailure(source_id=source, resource_id=source, reason_code=reason),)
        plan = CachePlan(MappingProxyType(dict(self._resources)), self._candidates, tuple(states.values()),
                         tuple(f for items in failures.values() for f in items), run_id, sources, started, finished, trigger)
        try:
            self._commit(plan)
            committed = True
        except CacheCommitError:
            # DB failure cannot erase observations or leave runtime data labelled
            # fresh. This metadata overlay is explicitly NOT a durable commit.
            committed = False
        self._states, self._failures = states, failures
        return committed

    def collection(self) -> HistoryCollection:
        batches = _batches(self._candidates)
        failures = tuple(f for errors in self._failures.values() for f in errors)
        return HistoryCollection(build_history(batches, failures=failures), batches, ())

    def view(self, now: datetime) -> RetainedSnapshot:
        collection = self.collection()
        requirements = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))["requirements"]
        labels = []
        for series in collection.snapshot.series:
            definition = requirements[series.series_id]
            source = definition["source_id"]
            state = self._states.get(source, SourceState(source_id=source))
            labels.append(freshness(series.series_id, series.latest, state, now,
                                    blocked_reason=definition.get("reason_code") if definition["status"] == "blocked" else None,
                                    empty=state.outcome == "empty"))
        return RetainedSnapshot(history=collection.snapshot, freshness=tuple(labels), source_states=tuple(self._states.values()))
