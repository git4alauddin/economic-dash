"""Single-owner asyncio scheduling with one coalesced startup refresh."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

from app.config import SchedulerSettings
from .catalog import SourceRegistry
from .process_lock import ProcessLock
from .refresh_policy import POLICY_VERSION, selected_policies
from .runner import CollectionRunner, event


class CollectorScheduler:
    def __init__(self, runner: CollectionRunner, settings: SchedulerSettings, *,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep):
        self.runner, self.settings, self.now, self.sleep = runner, settings, now, sleep
        self.policies = selected_policies(SourceRegistry.load())
        self.next_due: dict[str, datetime] = {}
        self._owner = ProcessLock(settings.state_directory / "scheduler.lock")
        self._task: asyncio.Task | None = None
        self.status = "stopped"

    def start(self) -> bool:
        if self._task is not None:
            return True
        if not self.settings.enabled:
            self.status = "disabled"
            return False
        if not self._owner.acquire():
            self.status = "standby"
            event("scheduler_standby", reason_code="scheduler_owner_exists")
            return False
        try:
            self.next_due.clear()
            self._task = asyncio.create_task(self._loop(), name="economic-indicator-collector")
        except BaseException:
            self._owner.release()
            raise
        self.status = "running"
        event("scheduler_started", policy_version=POLICY_VERSION, sources=[p.source_id for p in self.policies],
              startup="one_refresh_per_source_no_backlog_replay", history="manual_backfill_only")
        return True

    async def tick(self) -> None:
        now = self.now()
        due = tuple(p.source_id for p in self.policies if self.next_due.get(p.source_id, now) <= now)
        if not due:
            return
        result = await self.runner.run(due, trigger="scheduled")
        finished = self.now()
        for policy in self.policies:
            if policy.source_id in due:
                self.next_due[policy.source_id] = finished + timedelta(seconds=self.settings.tick_seconds) if result.status == "skipped_busy" else policy.next_due(finished)

    async def _loop(self) -> None:
        await self.sleep(self.settings.startup_delay)
        while True:
            try:
                await self.tick()
            except Exception as error:
                # Unexpected operational errors must not permanently kill the loop.
                event("scheduler_tick_failed", error_type=type(error).__name__)
            await self.sleep(self.settings.tick_seconds)

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=self.settings.shutdown_timeout)
        if not done:
            # Keep the owner lock while a cancellation-resistant collector runs.
            event("scheduler_shutdown_timeout", reason_code="collector_did_not_stop")
            raise RuntimeError("Collector did not stop within its shutdown budget.")
        try:
            if not task.cancelled():
                task.result()
        finally:
            self._task = None
            self._owner.release()
            self.status = "stopped"
            event("scheduler_stopped")
