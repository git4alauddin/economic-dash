"""Bounded async acquisition; no observation parsing, persistence or scheduler."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math
import random
import time
from typing import Literal
from urllib.parse import urljoin, urlsplit

import httpx2 as httpx

from app.config import CollectorSettings
from .catalog import SourceRegistry, SourceResource, validate_url
from .errors import AcquisitionError, ErrorCode

RETRY_STATUSES = {429, 500, 502, 503, 504}
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
CONTENT_TYPES = {"json": {"application/json"}, "html": {"text/html", "application/xhtml+xml"}, "pdf": {"application/pdf"}}


@dataclass(frozen=True)
class FetchResult:
    source_id: str
    resource_url: str
    response_url: str
    outcome: Literal["modified", "not_modified"]
    body: bytes | None
    content_type: str | None
    retrieved_at: datetime
    attempts: int
    generation: int
    etag: str | None = None
    last_modified: str | None = None


@dataclass
class HostState:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_start: float = -math.inf
    not_before: float = -math.inf


@dataclass
class AttemptProgress:
    attempts: int = 0


class CollectorHttpClient:
    def __init__(
        self, registry: SourceRegistry | None = None, settings: CollectorSettings | None = None,
        *, transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self.registry = registry if registry is not None else SourceRegistry.load()
        self.settings = settings if settings is not None else CollectorSettings()
        self._sleep, self._clock, self._utc_now, self._jitter = sleep, clock, utc_now, jitter
        self._hosts: dict[str, HostState] = {}
        self._locks = {key: asyncio.Lock() for key in self.registry.resources}
        self._generation = dict.fromkeys(self.registry.resources, 0)
        self._accepted: dict[str, tuple[str | None, str | None]] = {}
        self._slots = asyncio.Semaphore(self.settings.max_connections)
        self._http = httpx.AsyncClient(
            transport=transport, follow_redirects=False, trust_env=False,
            timeout=httpx.Timeout(
                connect=self.settings.connect_timeout, read=self.settings.read_timeout,
                write=self.settings.connect_timeout, pool=self.settings.connect_timeout,
            ),
            limits=httpx.Limits(max_connections=self.settings.max_connections, max_keepalive_connections=self.settings.max_connections),
            headers={"User-Agent": self.settings.user_agent},
        )

    async def __aenter__(self) -> "CollectorHttpClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    def register_discovered_release(self, source_id: str, url: str) -> str:
        """Extend only the bounded, same-publisher release set after index discovery."""
        registry, key = self.registry.with_discovered_release(source_id, url)
        self.registry = registry
        self._locks.setdefault(key, asyncio.Lock())
        self._generation.setdefault(key, 0)
        return key

    def acknowledge(self, result: FetchResult) -> bool:
        """Commit validators ONLY after the caller validates and accepts/stores data.

        Failed parsing/storage must not call this. M3.7/M4 own durable last-good data;
        this process-local cache stores only validators, never unvalidated bodies.
        An older in-flight result cannot replace validators for a newer response.
        """
        resource = self.registry.resolve(result.source_id)
        if (
            result.outcome != "modified" or result.resource_url != resource.url
            or result.generation != self._generation[result.source_id]
        ):
            return False
        self._accepted[result.source_id] = (result.etag, result.last_modified)
        return True

    async def fetch(self, source_id: str, *, conditional: bool = True) -> FetchResult:
        resource = self.registry.resolve(source_id)  # Gate BEFORE any request/wait.
        if self._http.is_closed:
            raise RuntimeError("Collector HTTP client is closed.")
        progress = AttemptProgress()
        deadline = self._clock() + self.settings.total_timeout
        try:
            async with asyncio.timeout(self.settings.total_timeout):
                async with self._locks[source_id]:
                    for number in range(1, self.settings.max_attempts + 1):
                        try:
                            # Waiting for pacing is not counted as a sent attempt.
                            result = await self._attempt(resource, conditional, deadline, number, progress)
                            return result
                        except AcquisitionError as error:
                            error.attempts = progress.attempts
                            retryable = error.code in {ErrorCode.TIMEOUT, ErrorCode.TRANSPORT} or error.http_status in RETRY_STATUSES
                            if not retryable or number == self.settings.max_attempts:
                                raise
                            backoff = min(self.settings.backoff_cap, self.settings.backoff_base * 2 ** (number - 1)) * self._jitter()
                            delay = max(backoff, error.retry_after_seconds or 0)
                            if delay >= deadline - self._clock():
                                raise
                            await self._sleep(delay)
        except TimeoutError as error:
            raise AcquisitionError(source_id, ErrorCode.TIMEOUT, progress.attempts) from error
        raise AssertionError("Acquisition attempts exhausted without a result.")

    async def _attempt(self, resource: SourceResource, conditional: bool, deadline: float, number: int, progress: AttemptProgress) -> FetchResult:
        host = urlsplit(resource.url).hostname
        state = self._hosts.setdefault(host, HostState())
        async with state.lock:
            await self._pace(state, resource.source_id, deadline)
            try:
                async with asyncio.timeout(self.settings.attempt_timeout):
                    async with self._slots:
                        return await self._request(resource, state, conditional, deadline, number, progress)
            except (TimeoutError, httpx.TimeoutException) as error:
                raise AcquisitionError(resource.source_id, ErrorCode.TIMEOUT, progress.attempts) from error
            except httpx.RequestError as error:
                raise AcquisitionError(resource.source_id, ErrorCode.TRANSPORT, progress.attempts) from error

    async def _pace(self, state: HostState, source_id: str, deadline: float) -> None:
        delay = max(state.not_before, state.last_start + self.settings.min_interval) - self._clock()
        if delay > 0:
            if delay >= deadline - self._clock():
                code = ErrorCode.RATE_LIMITED if state.not_before > self._clock() else ErrorCode.TIMEOUT
                raise AcquisitionError(source_id, code, retry_after_seconds=max(0, state.not_before - self._clock()) or None)
            await self._sleep(delay)

    async def _request(self, resource: SourceResource, state: HostState, conditional: bool, deadline: float, number: int, progress: AttemptProgress) -> FetchResult:
        headers = {"Accept": ", ".join(sorted(CONTENT_TYPES[resource.format]))}
        etag, modified = self._accepted.get(resource.source_id, (None, None))
        if conditional:
            if etag:
                headers["If-None-Match"] = etag
            if modified:
                headers["If-Modified-Since"] = modified
        url = resource.url
        for hop in range(4):
            if hop:
                await self._pace(state, resource.source_id, deadline)
            state.last_start = self._clock()
            progress.attempts = number
            async with self._http.stream("GET", url, headers=headers) as response:
                status = response.status_code
                if status in REDIRECT_STATUSES:
                    target = urljoin(url, response.headers.get("location", ""))
                    try:
                        validate_url(target)
                        valid = bool(response.headers.get("location")) and urlsplit(target).hostname == urlsplit(resource.url).hostname
                    except ValueError:
                        valid = False
                    if not valid or hop == 3:
                        raise AcquisitionError(resource.source_id, ErrorCode.REDIRECT, number, status)
                    url = target
                    continue
                if status == 304:
                    if not conditional or not (etag or modified):
                        raise AcquisitionError(resource.source_id, ErrorCode.NOT_MODIFIED, number, status)
                    return self._result(resource, url, response, None, "not_modified", number)
                if status != 200:
                    code = ErrorCode.RATE_LIMITED if status == 429 else ErrorCode.UPSTREAM if status >= 500 else ErrorCode.HTTP_STATUS
                    delay = self._retry_after(response.headers.get("retry-after")) if status in RETRY_STATUSES else None
                    if delay is not None:
                        state.not_before = max(state.not_before, self._clock() + delay)
                    raise AcquisitionError(resource.source_id, code, number, status, delay)
                content_type = response.headers.get("content-type", "").partition(";")[0].strip().lower()
                if content_type not in CONTENT_TYPES[resource.format]:
                    raise AcquisitionError(resource.source_id, ErrorCode.CONTENT_TYPE, number, status)
                declared = response.headers.get("content-length", "")
                normalized_length = declared.lstrip("0") or "0"
                if declared.isdecimal() and (len(normalized_length) > 10 or int(normalized_length) > self.settings.max_bytes):
                    raise AcquisitionError(resource.source_id, ErrorCode.SIZE, number, status)
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=16_384):
                    if len(body) + len(chunk) > self.settings.max_bytes:
                        raise AcquisitionError(resource.source_id, ErrorCode.SIZE, number, status)
                    body.extend(chunk)
                if not body:
                    raise AcquisitionError(resource.source_id, ErrorCode.EMPTY, number, status)
                self._generation[resource.source_id] += 1
                return self._result(resource, url, response, bytes(body), "modified", number)
        raise AssertionError("Redirect limit was not enforced.")

    def _result(self, resource: SourceResource, url: str, response: httpx.Response, body: bytes | None, outcome: Literal["modified", "not_modified"], attempts: int) -> FetchResult:
        return FetchResult(
            resource.source_id, resource.url, url, outcome, body,
            response.headers.get("content-type"), self._utc_now(), attempts,
            self._generation[resource.source_id], response.headers.get("etag"), response.headers.get("last-modified"),
        )

    def _retry_after(self, value: str | None) -> float | None:
        if not value:
            return None
        try:
            seconds = float(int(value.strip())) if value.strip().isascii() and value.strip().isdecimal() else (parsedate_to_datetime(value) - self._utc_now()).total_seconds()
            return max(0, seconds) if math.isfinite(seconds) else None
        except (ValueError, TypeError, OverflowError):
            return None
