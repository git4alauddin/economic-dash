"""Shared scheduled/manual collection boundary, protected across processes."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import json
import logging
from typing import Literal
from uuid import uuid4

from app.config import SchedulerSettings
from .adapters import create_adapters
from .discovery import INDEX_ID, discover_releases
from .errors import AcquisitionError
from .history import HistoryCollection, ResourceCheck, SourceFailure, build_history
from .http_client import CollectorHttpClient
from .observations import ParseError
from .process_lock import ProcessLock
from .snapshot_cache import CacheCommitError, SnapshotCache

LOGGER = logging.getLogger("economic_dash.collector")


def configure_logging() -> None:
    if not LOGGER.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False


def event(name: str, **fields) -> None:
    LOGGER.info(json.dumps({"event": name, **fields}, default=str, sort_keys=True))


async def collect_sources(client: CollectorHttpClient, sources: tuple[str, ...], *, history: bool = False, discovery_limit: int = 2, cache: SnapshotCache | None = None) -> HistoryCollection:
    batches, receipts, failures, checks = [], [], [], []
    if cache is not None:
        cache.seed(client, sources)
    pib_sources = tuple(source for source in sources if client.registry.resolve(source).format == "html")
    if pib_sources:
        try:
            index = await client.fetch(INDEX_ID, conditional=False)
            for candidate in discover_releases(index, client.registry, pib_sources, limit=discovery_limit):
                client.register_discovered_release(candidate.source_id, candidate.url)
        except (AcquisitionError, ParseError) as error:
            code = error.code.value if isinstance(error, AcquisitionError) else error.code
            failures.extend(SourceFailure(source_id=s, resource_id=INDEX_ID, reason_code=code) for s in pib_sources)
    adapters = create_adapters(client)
    for source in sources:
        for resource in client.registry.observation_resources(source):
            if not history and resource.startswith(f"{source}.history."):
                continue
            try:
                accepted = cache.get(resource) if cache is not None else None
                payloads = await adapters[source].acquire(resource_id=resource, conditional=accepted is not None)
                fetched = tuple(p for p in (payloads.payload, payloads.metadata) if p is not None)
                unchanged = all(p.outcome == "not_modified" for p in fetched)
                if unchanged:
                    if accepted is None:
                        raise ParseError(source, "conditional_snapshot_missing")
                    batch = accepted.batch
                else:
                    # A mixed World Bank data/metadata response must be validated
                    # together. Re-fetch only the body-less component, once.
                    if payloads.payload.outcome == "not_modified":
                        payloads = replace(payloads, payload=await client.fetch(resource, conditional=False))
                    if payloads.metadata and payloads.metadata.outcome == "not_modified":
                        payloads = replace(payloads, metadata=await client.fetch(payloads.metadata.source_id, conditional=False))
                    fetched = tuple(p for p in (payloads.payload, payloads.metadata) if p is not None)
                    batch = adapters[source].normalize(payloads)
                batches.append(batch)
                receipts.extend(fetched)
                checks.append(ResourceCheck(resource, batch, fetched, max(p.retrieved_at for p in fetched), unchanged))
            except (AcquisitionError, ParseError) as error:
                code = error.code.value if isinstance(error, AcquisitionError) else error.code
                failures.append(SourceFailure(source_id=source, resource_id=resource, reason_code=code))
    frozen = tuple(batches)
    return HistoryCollection(build_history(frozen, failures=tuple(failures)), frozen, tuple(receipts), tuple(checks))


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    trigger: str
    sources: tuple[str, ...]
    status: Literal["prepared", "unchanged", "partial", "failed", "timeout", "cancelled", "skipped_busy"]
    started_at: datetime
    finished_at: datetime
    batches: int = 0
    observations: int = 0
    failures: int = 0
    reason_code: str | None = None
    persisted: bool = False
    discovery_scope: str = "current_index_only"
    cache_scope: str = "process_memory"
    changed_resources: int = 0
    unchanged_resources: int = 0

    def as_json(self) -> str:
        return json.dumps(asdict(self), default=str, sort_keys=True)


class CollectionRunner:
    def __init__(
        self, settings: SchedulerSettings, *,
        client_factory: Callable[[], CollectorHttpClient] = CollectorHttpClient,
        collect: Callable[..., Awaitable[HistoryCollection]] = collect_sources,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        cache: SnapshotCache | None = None,
    ):
        self.settings, self.client_factory, self.collect, self.now = settings, client_factory, collect, now
        self._active = asyncio.Lock()
        self.cache = cache if cache is not None else SnapshotCache()
        self.last_run: RunSummary | None = None
        # A bounded in-memory handoff for M3.7/M4, never a public API snapshot.
        self.prepared: HistoryCollection | None = None
        self.prepared_sources: tuple[str, ...] = ()

    async def run(self, sources: tuple[str, ...], *, trigger: str, history: bool = False) -> RunSummary:
        from .catalog import SourceRegistry
        allowed = SourceRegistry.load().source_ids
        if not sources or len(set(sources)) != len(sources) or any(source not in allowed for source in sources):
            raise ValueError("Refresh requires unique, selected source IDs.")
        started = self.now()
        run_id = str(uuid4())
        def summary(status, **fields):
            return RunSummary(run_id, trigger, sources, status, started, self.now(), **fields)
        lock = ProcessLock(self.settings.state_directory / "collection.lock")
        if self._active.locked() or not lock.acquire():
            result = summary("skipped_busy", reason_code="collection_already_running")
            event("run_skipped", **asdict(result))
            return result
        try:
            async with self._active:
                event("run_started", run_id=run_id, trigger=trigger, sources=sources, started_at=started, history=history)
                try:
                    async with asyncio.timeout(self.settings.run_timeout):
                        async with self.client_factory() as client:
                            collection = await self.collect(client, sources, history=history, discovery_limit=self.settings.discovery_limit, cache=self.cache)
                            acceptance = self.cache.accept(collection, sources, run_id=run_id, started=started, finished=self.now())
                            for check in acceptance.checks:
                                for receipt in check.receipts:
                                    if receipt.outcome == "modified":
                                        client.acknowledge(receipt)
                    self.prepared, self.prepared_sources = self.cache.collection(), sources
                    errors = len(acceptance.failures)
                    status = (("partial" if acceptance.checks else "failed") if errors else
                              ("unchanged" if acceptance.unchanged and not acceptance.changed else "prepared"))
                    result = summary(status, batches=len(acceptance.checks),
                                     observations=sum(len(c.batch.observations) for c in acceptance.checks), failures=errors,
                                     changed_resources=acceptance.changed, unchanged_resources=acceptance.unchanged,
                                     reason_code="source_failures" if errors else None)
                except TimeoutError:
                    result = summary("timeout", reason_code="collection_deadline_exceeded")
                except asyncio.CancelledError:
                    self.cache.record_failure(sources, run_id=run_id, started=started, finished=self.now(), reason="collection_cancelled")
                    self.last_run = summary("cancelled", reason_code="collection_cancelled")
                    event("run_finished", **asdict(self.last_run))
                    raise
                except Exception as error:
                    # Do not emit payloads or untrusted exception messages in logs.
                    result = summary("failed", reason_code="snapshot_acceptance_failed" if isinstance(error, CacheCommitError) else "collection_internal_error")
                    event("run_error", run_id=run_id, error_type=type(error).__name__)
                if result.status in {"failed", "timeout"} and not result.failures:
                    self.cache.record_failure(sources, run_id=run_id, started=started, finished=self.now(), reason=result.reason_code)
                    self.prepared = self.cache.collection()
                self.last_run = result
                event("run_finished", **asdict(result))
                return result
        finally:
            lock.release()
