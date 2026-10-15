"""Verify source gates, bounded acquisition and conditional-cache acceptance."""

import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from types import MappingProxyType
import unittest

import httpx2 as httpx
from pydantic import ValidationError

from app.config import BACKEND_DIRECTORY, CollectorSettings
from app.collectors.adapters import create_adapters
from app.collectors.catalog import SourceRegistry, SourceResource, validate_url
from app.collectors.errors import AcquisitionError, ErrorCode
from app.collectors.http_client import CollectorHttpClient


class FakeClock:
    def __init__(self):
        self.value = 0.0
        self.waits = []

    def now(self):
        return self.value

    def utc(self):
        return datetime(2026, 10, 16, tzinfo=timezone.utc) + timedelta(seconds=self.value)

    async def sleep(self, seconds):
        self.waits.append(seconds)
        self.value += seconds
        await asyncio.sleep(0)


class Chunks(httpx.AsyncByteStream):
    def __init__(self, parts, *, slow=False):
        self.parts = parts
        self.slow = slow
        self.closed = False

    async def __aiter__(self):
        for part in self.parts:
            if self.slow:
                await asyncio.sleep(0.01)
            yield part

    async def aclose(self):
        self.closed = True


def registry():
    resources = {
        "first": SourceResource("first", "https://data.example/first", "json"),
        "second": SourceResource("second", "https://data.example/second", "json"),
        "other": SourceResource("other", "https://other.example/first", "json"),
    }
    return SourceRegistry(MappingProxyType(resources), frozenset({"restricted"}), tuple(resources))


class CollectionTests(unittest.IsolatedAsyncioTestCase):
    def client(self, handler, **overrides):
        clock = FakeClock()
        client = CollectorHttpClient(
            registry(), CollectorSettings(_env_file=None, **overrides),
            transport=httpx.MockTransport(handler), clock=clock.now,
            utc_now=clock.utc, sleep=clock.sleep, jitter=lambda: 1,
        )
        self.addAsyncCleanup(client.aclose)
        return client, clock

    async def test_catalog_enables_only_reviewed_routes(self):
        loaded = SourceRegistry.load()
        self.assertEqual(len(loaded.source_ids), 5)
        self.assertIn("world_bank_gdp.metadata", loaded.resources)
        for key in ["nse_indices", "nse_pulse", "bse_sensex", "imf_debt", "gstn_gross", "inflation_target_gazette"]:
            with self.subTest(key=key), self.assertRaises(AcquisitionError) as error:
                loaded.resolve(key)
            self.assertEqual(error.exception.code, ErrorCode.SOURCE_BLOCKED)
        for url in ["http://data.example", "https://user:pw@data.example", "https://data.example:8443", "https://data.example/#fragment", "https://data.example/ bad"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_url(url)

    async def test_blocked_and_unknown_sources_never_request(self):
        hits = []
        client, clock = self.client(lambda request: hits.append(request))
        for key, code in [("restricted", ErrorCode.SOURCE_BLOCKED), ("missing", ErrorCode.UNKNOWN_SOURCE)]:
            with self.assertRaises(AcquisitionError) as error:
                await client.fetch(key)
            self.assertEqual(error.exception.code, code)
            self.assertEqual(error.exception.attempts, 0)
        self.assertEqual(hits, [])
        self.assertEqual(clock.waits, [])

    async def test_success_has_identifiable_headers_timeouts_and_raw_payload(self):
        def handler(request):
            self.assertEqual(request.headers["user-agent"], "EconomicDashboard/0.1 source-collector")
            self.assertEqual(request.headers["accept"], "application/json")
            self.assertNotIn("authorization", request.headers)
            self.assertEqual(request.extensions["timeout"]["connect"], 5)
            self.assertEqual(request.extensions["timeout"]["read"], 10)
            return httpx.Response(200, content=b'{"decimal":"0.00"}', headers={"content-type": "application/json; charset=utf-8"})
        client, clock = self.client(handler)
        result = await client.fetch("first")
        self.assertEqual(result.body, b'{"decimal":"0.00"}')
        self.assertEqual(result.outcome, "modified")
        self.assertEqual(result.retrieved_at, clock.utc())
        self.assertEqual(result.attempts, 1)

    async def test_transient_5xx_retries_are_bounded_and_paced(self):
        for status in [500, 502, 503, 504]:
            starts = []
            def handler(request):
                starts.append(clock.now())
                return httpx.Response(status if len(starts) < 3 else 200, json={})
            client, clock = self.client(handler)
            result = await client.fetch("first")
            self.assertEqual(result.attempts, 3)
            self.assertEqual(len(starts), 3)
            self.assertTrue(all(right - left >= 1 for left, right in zip(starts, starts[1:])))
            self.assertTrue(all(wait <= 5 for wait in clock.waits))

    async def test_exhausted_5xx_and_timeouts_do_not_retry_forever(self):
        for failure in [503, "timeout", "connection"]:
            hits = []
            def handler(request):
                hits.append(request)
                if failure == "timeout":
                    raise httpx.ReadTimeout("synthetic timeout", request=request)
                if failure == "connection":
                    raise httpx.ConnectError("synthetic failure", request=request)
                return httpx.Response(failure)
            client, _ = self.client(handler)
            with self.assertRaises(AcquisitionError) as error:
                await client.fetch("first")
            self.assertEqual(len(hits), 3)
            self.assertEqual(error.exception.attempts, 3)
            self.assertEqual(error.exception.code, {503: ErrorCode.UPSTREAM, "timeout": ErrorCode.TIMEOUT, "connection": ErrorCode.TRANSPORT}[failure])

    async def test_permanent_statuses_are_not_retried(self):
        for status in [400, 401, 403, 404, 501]:
            hits = []
            def handler(request):
                hits.append(request)
                return httpx.Response(status)
            client, _ = self.client(handler)
            with self.assertRaises(AcquisitionError) as error:
                await client.fetch("first")
            self.assertEqual(error.exception.http_status, status)
            self.assertEqual(len(hits), 1)

    async def test_retry_after_seconds_and_http_date_are_honoured(self):
        for kind in ["seconds", "date"]:
            starts = []
            def handler(request):
                starts.append(clock.now())
                delay = "3" if kind == "seconds" else format_datetime(clock.utc() + timedelta(seconds=3), usegmt=True)
                return httpx.Response(429, headers={"retry-after": delay}) if len(starts) == 1 else httpx.Response(200, json={})
            client, clock = self.client(handler)
            result = await client.fetch("first")
            self.assertEqual(result.attempts, 2)
            self.assertGreaterEqual(starts[1] - starts[0], 3)

    async def test_large_retry_after_defers_shared_host_without_early_retry(self):
        hits = []
        def handler(request):
            hits.append(request)
            return httpx.Response(429, headers={"retry-after": "3600"})
        client, clock = self.client(handler)
        with self.assertRaises(AcquisitionError) as first:
            await client.fetch("first")
        self.assertEqual(first.exception.code, ErrorCode.RATE_LIMITED)
        self.assertEqual(first.exception.retry_after_seconds, 3600)
        with self.assertRaises(AcquisitionError) as second:
            await client.fetch("second")
        self.assertEqual(second.exception.attempts, 0)
        self.assertEqual(second.exception.code, ErrorCode.RATE_LIMITED)
        self.assertEqual(len(hits), 1)
        self.assertEqual(clock.waits, [])

    async def test_malformed_retry_after_falls_back_to_bounded_backoff(self):
        hits = []
        def handler(request):
            hits.append(request)
            return httpx.Response(503, headers={"retry-after": "not a date"})
        client, clock = self.client(handler)
        with self.assertRaises(AcquisitionError):
            await client.fetch("first")
        self.assertEqual(len(hits), 3)
        self.assertLessEqual(sum(clock.waits), 10)

    async def test_conditional_cache_requires_explicit_acceptance_and_survives_failure(self):
        requests = []
        responses = [
            httpx.Response(200, content=b'malformed', headers={"content-type": "application/json", "etag": '"bad"'}),
            httpx.Response(200, json={}, headers={"etag": '"good"', "last-modified": "Thu, 15 Oct 2026 00:00:00 GMT"}),
            httpx.Response(503), httpx.Response(304),
        ]
        def handler(request):
            requests.append(request)
            return responses[len(requests)-1]
        client, _ = self.client(handler, max_attempts=1)
        rejected = await client.fetch("first")  # A later parser rejects it; no acknowledge.
        accepted = await client.fetch("first")
        self.assertNotIn("if-none-match", requests[1].headers)
        self.assertFalse(client.acknowledge(rejected))  # Outdated response.
        self.assertTrue(client.acknowledge(accepted))
        with self.assertRaises(AcquisitionError):
            await client.fetch("first")
        result = await client.fetch("first")
        self.assertEqual(requests[3].headers["if-none-match"], '"good"')
        self.assertIn("if-modified-since", requests[3].headers)
        self.assertEqual(result.outcome, "not_modified")
        self.assertIsNone(result.body)
        self.assertFalse(client.acknowledge(result))

    async def test_forced_fetch_and_new_response_without_validators(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={}, headers={"etag": '"first"'} if len(requests) == 1 else {})
        client, _ = self.client(handler)
        client.acknowledge(await client.fetch("first"))
        client.acknowledge(await client.fetch("first", conditional=False))
        await client.fetch("first")
        self.assertTrue(all("if-none-match" not in request.headers for request in requests))

    async def test_unsolicited_304_is_rejected(self):
        client, _ = self.client(lambda request: httpx.Response(304))
        with self.assertRaises(AcquisitionError) as error:
            await client.fetch("first")
        self.assertEqual(error.exception.code, ErrorCode.NOT_MODIFIED)
        self.assertEqual(error.exception.attempts, 1)

    async def test_redirects_are_same_host_https_and_bounded(self):
        for target in ["https://other.example/leak", "http://data.example/plain", "https://user:pw@data.example/private", "/loop"]:
            hits = []
            def handler(request):
                hits.append(request)
                return httpx.Response(302, headers={"location": target})
            client, clock = self.client(handler)
            with self.assertRaises(AcquisitionError) as error:
                await client.fetch("first")
            self.assertEqual(error.exception.code, ErrorCode.REDIRECT)
            self.assertEqual(len(hits), 4 if target == "/loop" else 1)
            self.assertTrue(all(request.url.host == "data.example" for request in hits))
        def handler(request):
            return httpx.Response(302, headers={"location": "/canonical"}) if request.url.path == "/first" else httpx.Response(200, json={})
        client, clock = self.client(handler)
        result = await client.fetch("first")
        self.assertEqual(result.resource_url, "https://data.example/first")
        self.assertEqual(result.response_url, "https://data.example/canonical")
        self.assertGreaterEqual(sum(clock.waits), 1)

    async def test_invalid_content_empty_and_oversized_bodies_are_rejected(self):
        for response, code in [
            (httpx.Response(200, text="HTML error"), ErrorCode.CONTENT_TYPE),
            (httpx.Response(200, content=b"", headers={"content-type": "application/json"}), ErrorCode.EMPTY),
            (httpx.Response(200, content=b"{}", headers={"content-type": "application/json", "content-length": "9999"}), ErrorCode.SIZE),
            (httpx.Response(200, stream=Chunks([b"a" * 60, b"b" * 60]), headers={"content-type": "application/json"}), ErrorCode.SIZE),
        ]:
            client, _ = self.client(lambda request: response, max_bytes=100)
            with self.assertRaises(AcquisitionError) as error:
                await client.fetch("first")
            self.assertEqual(error.exception.code, code)
            self.assertEqual(error.exception.attempts, 1)

    async def test_dripping_stream_has_a_hard_attempt_deadline_and_closes(self):
        streams = []
        def handler(request):
            stream = Chunks([b"a"] * 100, slow=True)
            streams.append(stream)
            return httpx.Response(200, stream=stream, headers={"content-type": "application/json"})
        client, _ = self.client(handler, attempt_timeout=0.025, total_timeout=0.2, max_attempts=2, min_interval=0.001, backoff_base=0.001)
        with self.assertRaises(AcquisitionError) as error:
            await client.fetch("first")
        self.assertEqual(error.exception.code, ErrorCode.TIMEOUT)
        self.assertEqual(error.exception.attempts, 2)
        self.assertEqual(len(streams), 2)
        self.assertTrue(all(stream.closed for stream in streams))

    async def test_total_deadline_and_cancellation_stop_requests(self):
        started = asyncio.Event()
        hits = []
        async def handler(request):
            hits.append(request)
            started.set()
            await asyncio.Event().wait()
        client, _ = self.client(handler, total_timeout=0.03, attempt_timeout=0.03)
        with self.assertRaises(AcquisitionError) as error:
            await client.fetch("first")
        self.assertEqual(error.exception.code, ErrorCode.TIMEOUT)
        self.assertEqual(error.exception.attempts, 1)
        self.assertEqual(len(hits), 1)
        started.clear()
        task = asyncio.create_task(client.fetch("other"))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(len(hits), 2)

    async def test_shared_host_is_serialized_and_other_hosts_can_progress(self):
        active = {}
        peak = {}
        global_peak = 0
        starts = {}
        async def handler(request):
            nonlocal global_peak
            host = request.url.host
            active[host] = active.get(host, 0) + 1
            peak[host] = max(peak.get(host, 0), active[host])
            global_peak = max(global_peak, sum(active.values()))
            starts.setdefault(host, []).append(clock.now())
            await asyncio.sleep(0)
            active[host] -= 1
            return httpx.Response(200, json={})
        client, clock = self.client(handler, max_connections=2)
        await asyncio.gather(client.fetch("first"), client.fetch("second"), client.fetch("other"), client.fetch("first"))
        self.assertTrue(all(value == 1 for value in peak.values()))
        self.assertEqual(global_peak, 2)
        self.assertTrue(all(b - a >= 1 for a, b in zip(starts["data.example"], starts["data.example"][1:])))

    async def test_catalog_adapters_acquire_world_bank_metadata_without_accepting(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={}, headers={"etag": '"synthetic"'})
        async with CollectorHttpClient(
            SourceRegistry.load(), CollectorSettings(_env_file=None, min_interval=0.001),
            transport=httpx.MockTransport(handler),
        ) as client:
            adapters = create_adapters(client)
            self.assertNotIn("nse_indices", adapters)
            bundle = await adapters["world_bank_gdp"].acquire()
            self.assertEqual(bundle.payload.source_id, "world_bank_gdp")
            self.assertEqual(bundle.metadata.source_id, "world_bank_gdp.metadata")
            await adapters["world_bank_gdp"].acquire()
            self.assertEqual(len(requests), 4)
            self.assertTrue(all("if-none-match" not in request.headers for request in requests))

    async def test_settings_reject_unbounded_or_invalid_limits(self):
        for values in [
            {"max_attempts": 6}, {"min_interval": 0}, {"max_bytes": 0},
            {"read_timeout": float("inf")}, {"total_timeout": float("nan")},
            {"attempt_timeout": 60, "total_timeout": 30},
            {"backoff_base": 10, "backoff_cap": 1}, {"user_agent": "bad\r\nheader"},
        ]:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                CollectorSettings(_env_file=None, **values)
        self.assertEqual(CollectorSettings(_env_file=BACKEND_DIRECTORY / ".env.example").max_attempts, 3)


if __name__ == "__main__":
    unittest.main()
