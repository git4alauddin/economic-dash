"""Shared scheduled/manual collection boundary, protected across processes."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
from typing import Literal
from uuid import uuid4

from app.config import SchedulerSettings
from .adapters import create_adapters
from .discovery import INDEX_ID, discover_releases
from .errors import AcquisitionError
from .history import HistoryCollection, SourceFailure, build_history
from .http_client import CollectorHttpClient
from .observations import ParseError
from .process_lock import ProcessLock

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


async def collect_sources(client: CollectorHttpClient, sources: tuple[str, ...], *, history: bool = False, discovery_limit: int = 2) -> HistoryCollection:
    batches, receipts, failures = [], [], []
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
                # Conditional-body/last-good handling belongs to M3.7. Validators
                # are never acknowledged before M4 accepts the observations.
                payloads = await adapters[source].acquire(resource_id=resource, conditional=False)
                batches.append(adapters[source].normalize(payloads))
                receipts.extend(p for p in (payloads.payload, payloads.metadata) if p is not None)
            except (AcquisitionError, ParseError) as error:
                code = error.code.value if isinstance(error, AcquisitionError) else error.code
                failures.append(SourceFailure(source_id=source, resource_id=resource, reason_code=code))
    frozen = tuple(batches)
    return HistoryCollection(build_history(frozen, failures=tuple(failures)), frozen, tuple(receipts))


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    trigger: str
    sources: tuple[str, ...]
    status: Literal["prepared", "partial", "failed", "timeout", "cancelled", "skipped_busy"]
    started_at: datetime
    finished_at: datetime
    batches: int = 0
    observations: int = 0
    failures: int = 0
    reason_code: str | None = None
    persisted: bool = False
    discovery_scope: str = "current_index_only"

    def as_json(self) -> str:
        return json.dumps(asdict(self), default=str, sort_keys=True)


class CollectionRunner:
    def __init__(
        self, settings: SchedulerSettings, *,
        client_factory: Callable[[], CollectorHttpClient] = CollectorHttpClient,
        collect: Callable[..., Awaitable[HistoryCollection]] = collect_sources,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.settings, self.client_factory, self.collect, self.now = settings, client_factory, collect, now
        self._active = asyncio.Lock()
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
                            collection = await self.collect(client, sources, history=history, discovery_limit=self.settings.discovery_limit)
                    self.prepared, self.prepared_sources = collection, sources
                    errors = len(collection.snapshot.failures)
                    status = ("partial" if collection.batches else "failed") if errors else "prepared"
                    result = summary(status, batches=len(collection.batches),
                                     observations=sum(len(b.observations) for b in collection.batches), failures=errors,
                                     reason_code="source_failures" if errors else None)
                except TimeoutError:
                    result = summary("timeout", reason_code="collection_deadline_exceeded")
                except asyncio.CancelledError:
                    self.last_run = summary("cancelled", reason_code="collection_cancelled")
                    event("run_finished", **asdict(self.last_run))
                    raise
                except Exception as error:
                    # Do not emit payloads or untrusted exception messages in logs.
                    result = summary("failed", reason_code="collection_internal_error")
                    event("run_error", run_id=run_id, error_type=type(error).__name__)
                self.last_run = result
                event("run_finished", **asdict(result))
                return result
        finally:
            lock.release()
