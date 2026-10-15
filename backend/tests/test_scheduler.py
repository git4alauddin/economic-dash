"""Scheduler timing, cross-process ownership, discovery and cancellation checks."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import logging
import multiprocessing
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MappingProxyType, SimpleNamespace
import unittest
from unittest.mock import patch

import httpx2 as httpx
from pydantic import ValidationError

from app.collectors.catalog import SourceRegistry
from app.collectors.discovery import discover_releases
from app.collectors.history import HistoryCollection, build_history
from app.collectors.http_client import CollectorHttpClient, FetchResult
from app.collectors.observations import ParseError
from app.collectors.process_lock import ProcessLock
from app.collectors.refresh_policy import IST, POLICIES, selected_policies
from app.collectors.runner import CollectionRunner, collect_sources
from app.collectors.scheduler import CollectorScheduler
from app.config import CollectorSettings, SchedulerSettings, Settings
from app.main import create_app
from test_normalization import NOW, trade


def index(body):
    resource = SourceRegistry.load().resolve("pib_release_index")
    return FetchResult(resource.source_id, resource.url, resource.url, "modified", body.encode(), "text/html", NOW, 1, 1)


def index_html(href="/PressReleseDetail.aspx?PRID=2324000", title="Cumulative exports (merchandise and services) during April-September 2026"):
    return f'<h2>All Releases</h2><h3>Ministry of Commerce &amp; Industry</h3><a href="{href}">{title}</a><img style="x" style="y">'


def hold_process_lock(path, connection):
    lock = ProcessLock(Path(path))
    connection.send(lock.acquire())
    connection.recv()
    lock.release()
    connection.close()


class LockTests(unittest.TestCase):
    def test_nonblocking_lock_and_release(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "run.lock"
            first, second = ProcessLock(path), ProcessLock(path)
            self.assertTrue(first.acquire())
            try:
                self.assertFalse(second.acquire())
            finally:
                first.release()
            self.assertTrue(second.acquire())
            second.release()
            second.release()

    def test_other_process_excluded_and_crash_releases_kernel_lock(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "run.lock"
            context = multiprocessing.get_context("spawn")
            parent, child = context.Pipe()
            process = context.Process(target=hold_process_lock, args=(str(path), child))
            process.start()
            child.close()
            try:
                self.assertTrue(parent.poll(10), "Child lock startup timed out")
                self.assertTrue(parent.recv())
                self.assertFalse(ProcessLock(path).acquire())
                process.terminate()
                process.join(5)
                self.assertFalse(process.is_alive())
                replacement = ProcessLock(path)
                self.assertTrue(replacement.acquire())
                replacement.release()
            finally:
                if process.is_alive():
                    process.terminate()
                    process.join(5)
                parent.close()


class PolicyTests(unittest.TestCase):
    def test_selected_sources_only_and_blocked_tickers_have_no_schedule(self):
        registry = SourceRegistry.load()
        self.assertEqual({p.source_id for p in selected_policies(registry)}, set(registry.source_ids))
        for source in ("nse_indices", "bse_sensex", "gstn_gross", "inflation_target_gazette"):
            self.assertNotIn(source, POLICIES)

    def test_ist_release_windows_and_quiet_cadence(self):
        cpi = POLICIES["mospi_cpi_pib"]
        active = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
        quiet = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
        self.assertEqual(cpi.next_due(active), active + timedelta(hours=6))
        self.assertEqual(cpi.next_due(quiet), quiet + timedelta(days=1))
        self.assertEqual(POLICIES["world_bank_gdp"].next_due(quiet), quiet + timedelta(days=7))
        before = datetime(2026, 1, 30, 20, tzinfo=timezone.utc)
        self.assertEqual(POLICIES["mospi_gdp_pib"].next_due(before), datetime(2026, 2, 1, tzinfo=IST).astimezone(timezone.utc))
        self.assertTrue(cpi.is_active(datetime(2026, 10, 9, 19, tzinfo=timezone.utc)))  # Oct 10 IST
        with self.assertRaises(ValueError):
            cpi.next_due(active.replace(tzinfo=None))

    def test_scheduler_settings_bounds_and_environment(self):
        for fields in ({"tick_seconds": 0}, {"run_timeout": float("inf")}, {"discovery_limit": 5}, {"shutdown_timeout": -1}):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                SchedulerSettings(_env_file=None, **fields)
        with patch.dict("os.environ", {"COLLECTOR_SCHEDULER_ENABLED": "false", "COLLECTOR_SCHEDULER_TICK_SECONDS": "17"}):
            settings = SchedulerSettings(_env_file=None)
            self.assertFalse(settings.enabled)
            self.assertEqual(settings.tick_seconds, 17)


class DiscoveryTests(unittest.TestCase):
    def test_official_links_deduplicated_bounded_and_footer_image_ignored(self):
        html = index_html() + ''.join(f'<a href="/PressReleseDetail.aspx?PRID={rid}">Cumulative exports (merchandise and services) during April-September</a>' for rid in (2324000, 2324001, 2324002))
        result = discover_releases(index(html), SourceRegistry.load(), ("commerce_trade_pib",), limit=2)
        self.assertEqual([p.url.rsplit("=", 1)[-1] for p in result], ["2324002", "2324001"])
        self.assertTrue(all(p.source_id == "commerce_trade_pib" for p in result))

    def test_known_release_not_refetched_and_wrong_ministry_not_selected(self):
        known = discover_releases(index(index_html(href="/PressReleseDetail.aspx?PRID=2323944")), SourceRegistry.load(), ("commerce_trade_pib",))
        self.assertEqual(known, ())
        foreign = index_html().replace("Commerce &amp; Industry", "Tourism")
        self.assertEqual(discover_releases(index(foreign), SourceRegistry.load(), ("commerce_trade_pib",)), ())

    def test_foreign_urls_duplicate_href_changed_heading_or_hidden_links_rejected(self):
        for href in ("https://evil.example/PressReleseDetail.aspx?PRID=2324000", "http://www.pib.gov.in/PressReleseDetail.aspx?PRID=2324000", "/other?PRID=2324000", "/PressReleseDetail.aspx?PRID=1&PRID=2"):
            with self.subTest(href=href), self.assertRaises(ParseError):
                discover_releases(index(index_html(href=href)), SourceRegistry.load(), ("commerce_trade_pib",))
        with self.assertRaises(ParseError):
            discover_releases(index(index_html().replace('href="', 'href="x" href="')), SourceRegistry.load(), ("commerce_trade_pib",))
        with self.assertRaises(ParseError):
            discover_releases(index(index_html().replace("All Releases", "Error")), SourceRegistry.load(), ("commerce_trade_pib",))
        hidden = index_html().replace('<a href=', '<a hidden href=')
        self.assertEqual(discover_releases(index(hidden), SourceRegistry.load(), ("commerce_trade_pib",)), ())

    def test_discovery_registry_cannot_enable_blocked_source_or_arbitrary_resource(self):
        registry = SourceRegistry.load()
        for source, url in (("world_bank_gdp", "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2324000"), ("commerce_trade_pib", "https://evil.example/PressReleasePage.aspx?PRID=2324000"), ("commerce_trade_pib", "https://www.pib.gov.in/AllRelease.aspx?PRID=2324000")):
            with self.subTest(source=source, url=url), self.assertRaises(ValueError):
                registry.with_discovered_release(source, url)
        with self.assertRaises(Exception):
            registry.with_discovered_release("nse_indices", "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2324000")


class AsyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = SchedulerSettings(_env_file=None, state_directory=Path(self.directory.name), startup_delay=0, tick_seconds=0.01)
        self.logger = logging.Logger("test_collector")
        self.logger.addHandler(logging.NullHandler())
        self.enterContext(patch("app.collectors.runner.LOGGER", self.logger))


class AcquisitionTests(AsyncTests):
    async def test_discovered_release_parsed_before_accepted_and_no_archives_on_normal_refresh(self):
        registry = SourceRegistry.load()
        resources = {key: value for key, value in registry.resources.items() if key in {"pib_release_index", "commerce_trade_pib"} or key.startswith("commerce_trade_pib.history.")}
        registry = replace(registry, resources=MappingProxyType(resources), source_ids=("commerce_trade_pib",))
        hits = []
        def handler(request):
            hits.append(str(request.url))
            if request.url.path == "/AllRelease.aspx":
                body = index_html().encode()
            elif request.url.params["PRID"] == "2324000":
                body = trade().payload.body.replace(b"2323944", b"2324000").replace(b"15 OCT", b"16 OCT").replace(b"12.50", b"12.75")
            else:
                body = trade().payload.body
            return httpx.Response(200, content=body, headers={"content-type": "text/html"})
        async with CollectorHttpClient(registry=registry, settings=CollectorSettings(_env_file=None, min_interval=0.001), transport=httpx.MockTransport(handler), utc_now=lambda: NOW) as client:
            result = await collect_sources(client, ("commerce_trade_pib",))
            self.assertFalse(result.snapshot.failures)
            latest = next(s.latest for s in result.snapshot.series if s.series_id == "exports")
            self.assertEqual(str(latest.value), "12.75")
            self.assertIn("2324000", latest.sources[0].url)
            self.assertEqual(len(hits), 3)  # One index, starting release, discovered release.
            self.assertEqual(client._accepted, {})

    async def test_invalid_candidate_and_failed_discovery_keep_known_valid_batches(self):
        registry = SourceRegistry.load()
        registry = replace(registry, source_ids=("commerce_trade_pib",))
        for invalid_index in (False, True):
            def handler(request):
                if request.url.path == "/AllRelease.aspx":
                    return httpx.Response(200, content=("Error" if invalid_index else index_html()).encode(), headers={"content-type": "text/html"})
                body = b"<html>not a release</html>" if request.url.params["PRID"] == "2324000" else trade().payload.body
                return httpx.Response(200, content=body, headers={"content-type": "text/html"})
            async with CollectorHttpClient(registry=registry, settings=CollectorSettings(_env_file=None, min_interval=0.001), transport=httpx.MockTransport(handler), utc_now=lambda: NOW) as client:
                result = await collect_sources(client, ("commerce_trade_pib",))
                self.assertEqual(len(result.batches), 1)
                self.assertEqual(len(result.snapshot.failures), 1)
                self.assertEqual(client._accepted, {})


class FakeClient:
    async def __aenter__(self):
        self.closed = False
        return self

    async def __aexit__(self, *args):
        self.closed = True


EMPTY = HistoryCollection(build_history(()), (), ())


class RunnerTests(AsyncTests):
    async def test_manual_scheduled_and_other_runner_cannot_overlap(self):
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def collect(*args, **kwargs):
            calls.append(1)
            entered.set()
            await release.wait()
            return EMPTY
        first = CollectionRunner(self.settings, client_factory=FakeClient, collect=collect)
        second = CollectionRunner(self.settings, client_factory=FakeClient, collect=collect)
        task = asyncio.create_task(first.run(("world_bank_gdp",), trigger="scheduled"))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            self.assertEqual((await first.run(("world_bank_gdp",), trigger="manual")).status, "skipped_busy")
            self.assertEqual((await second.run(("world_bank_gdp",), trigger="manual")).status, "skipped_busy")
            self.assertEqual(calls, [1])
        finally:
            release.set()
            await task

    async def test_cancel_closes_client_releases_lock_and_logs_run_end(self):
        entered = asyncio.Event()
        client = FakeClient()
        async def collect(*args, **kwargs):
            entered.set()
            await asyncio.Event().wait()
        runner = CollectionRunner(self.settings, client_factory=lambda: client, collect=collect)
        with self.assertLogs(self.logger, "INFO") as logs:
            task = asyncio.create_task(runner.run(("world_bank_gdp",), trigger="scheduled"))
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(client.closed)
        self.assertEqual(runner.last_run.status, "cancelled")
        self.assertTrue(any('"event": "run_finished"' in line for line in logs.output))
        lock = ProcessLock(self.settings.state_directory / "collection.lock")
        self.assertTrue(lock.acquire())
        lock.release()

    async def test_timeout_and_internal_error_do_not_prevent_next_run(self):
        async def slow(*args, **kwargs):
            await asyncio.Event().wait()
        settings = SchedulerSettings(_env_file=None, state_directory=self.settings.state_directory, run_timeout=0.01)
        runner = CollectionRunner(settings, client_factory=FakeClient, collect=slow)
        self.assertEqual((await runner.run(("world_bank_gdp",), trigger="manual")).status, "timeout")
        async def broken(*args, **kwargs):
            raise RuntimeError("untrusted payload text")
        runner.collect = broken
        self.assertEqual((await runner.run(("world_bank_gdp",), trigger="scheduled")).reason_code, "collection_internal_error")
        async def good(*args, **kwargs):
            return EMPTY
        runner.collect = good
        summary = await runner.run(("world_bank_gdp",), trigger="manual")
        self.assertEqual(summary.status, "prepared")
        self.assertFalse(json.loads(summary.as_json())["persisted"])

    async def test_blocked_or_duplicate_sources_rejected_before_client_creation(self):
        def forbidden():
            self.fail("Client must not be created")
        runner = CollectionRunner(self.settings, client_factory=forbidden)
        for sources in (("nse_indices",), (), ("world_bank_gdp", "world_bank_gdp")):
            with self.subTest(sources=sources), self.assertRaises(ValueError):
                await runner.run(sources, trigger="manual")


class SchedulerTests(AsyncTests):
    async def test_startup_due_work_coalesces_without_backlog_or_archive_replay(self):
        clock = [NOW]
        calls = []
        async def run(sources, **kwargs):
            calls.append((sources, kwargs))
            return SimpleNamespace(status="prepared")
        scheduler = CollectorScheduler(SimpleNamespace(run=run), self.settings, now=lambda: clock[0])
        await scheduler.tick()
        await scheduler.tick()
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0][0]), 5)
        self.assertNotIn("history", calls[0][1])
        clock[0] += timedelta(days=100)
        await scheduler.tick()
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(due > clock[0] for due in scheduler.next_due.values()))

    async def test_owner_lock_standby_shutdown_restart_and_no_browser_trigger(self):
        entered = asyncio.Event()
        async def run(*args, **kwargs):
            entered.set()
            return SimpleNamespace(status="prepared")
        first = CollectorScheduler(SimpleNamespace(run=run), self.settings)
        second = CollectorScheduler(SimpleNamespace(run=run), self.settings)
        self.addAsyncCleanup(first.stop)
        self.addAsyncCleanup(second.stop)
        self.assertTrue(first.start())
        self.assertTrue(first.start())
        self.assertFalse(second.start())
        self.assertEqual(second.status, "standby")
        await asyncio.wait_for(entered.wait(), 1)  # No HTTP/browser request.
        await first.stop()
        self.assertTrue(second.start())
        await second.stop()
        self.assertEqual(second.status, "stopped")

    async def test_run_failure_reschedules_and_scheduler_survives_operational_exception(self):
        called = asyncio.Event()
        attempts = []
        async def run(*args, **kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                raise OSError("simulated lock I/O failure")
            called.set()
            return SimpleNamespace(status="failed")
        scheduler = CollectorScheduler(SimpleNamespace(run=run), self.settings)
        self.addAsyncCleanup(scheduler.stop)
        scheduler.start()
        await asyncio.wait_for(called.wait(), 1)
        self.assertEqual(len(attempts), 2)
        self.assertTrue(scheduler.next_due)
        await scheduler.stop()

    async def test_lifespan_starts_and_cancels_collector_without_http_requests(self):
        entered = asyncio.Event()
        closed = asyncio.Event()
        async def collect(*args, **kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()
        runner = CollectionRunner(self.settings, client_factory=FakeClient, collect=collect)
        application = create_app(Settings(_env_file=None), scheduler_settings=self.settings, runner=runner)
        async with application.router.lifespan_context(application):
            await asyncio.wait_for(entered.wait(), 1)
            self.assertEqual(application.state.collector_scheduler.status, "running")
        self.assertTrue(closed.is_set())
        self.assertEqual(application.state.collector_scheduler.status, "stopped")

    async def test_disabled_lifespan_has_no_task_or_network(self):
        def forbidden():
            self.fail("Disabled scheduler must not create a client")
        settings = SchedulerSettings(_env_file=None, enabled=False, state_directory=self.settings.state_directory)
        application = create_app(Settings(_env_file=None), scheduler_settings=settings, runner=CollectionRunner(settings, client_factory=forbidden))
        async with application.router.lifespan_context(application):
            self.assertEqual(application.state.collector_scheduler.status, "disabled")
            self.assertIsNone(application.state.collector_scheduler._task)


if __name__ == "__main__":
    unittest.main()
