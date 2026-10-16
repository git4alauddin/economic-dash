"""Production UI + real local JWT/API browser check in disposable private storage.

Run from backend: python -m app.verify_session [--all-sources]. Requires Node,
frontend dependencies and installed Chrome/Edge. No credentials/reports saved.
"""

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from secrets import token_hex, token_urlsafe
import shutil
import socket
import subprocess
from tempfile import TemporaryDirectory
from threading import Thread, Timer
from time import monotonic, sleep

import uvicorn

from app.auth.settings import AuthSettings
from app.auth.users import UserStore
from app.collectors.catalog import SourceRegistry
from app.collectors.http_client import CollectorHttpClient, FetchResult
from app.collectors.errors import AcquisitionError, ErrorCode
from app.collectors.runner import CollectionRunner
from app.collectors.scheduler import CollectorScheduler
from app.config import BACKEND_DIRECTORY, DatabaseSettings, SchedulerSettings, Settings
from app.database import Database
from app.main import create_app
from app.repository import SQLiteCollectionRepository
from app.verify_integration import require
from app.verify_world_trace import world_gdp_trace


async def verify(*, all_sources=False):
    node = shutil.which("node")
    require(node is not None, "Node and frontend dependencies are required.")
    with TemporaryDirectory(prefix="economic-dash-session-") as temporary:
        root = Path(temporary)
        settings = DatabaseSettings(_env_file=None, app_env="test", directory=root / "database")
        database = Database(settings)
        database.bootstrap()
        sources = SourceRegistry.load().source_ids if all_sources else ("world_bank_gdp",)
        receipts = {}
        source_fault = None
        class TracedClient(CollectorHttpClient):
            async def fetch(self, resource_id, **options):
                # Private verifier injection at the publisher transport boundary;
                # real adapters/normalizers/scheduler/SQL/API remain in the path.
                if resource_id.startswith("world_bank_gdp"):
                    if source_fault == "timeout":
                        raise AcquisitionError("world_bank_gdp", ErrorCode.TIMEOUT, attempts=1)
                    if source_fault == "invalid":
                        resource = self.registry.resolve(resource_id)
                        return FetchResult(resource_id, resource.url, resource.url, "modified", b"{}", "application/json",
                                           datetime.now(timezone.utc), 1, 0)
                    if source_fault == "recover":
                        options["conditional"] = False
                result = await super().fetch(resource_id, **options)
                if resource_id in {"world_bank_gdp", "world_bank_gdp.metadata"} and result.body is not None:
                    receipts[resource_id] = result
                return result
        runner = CollectionRunner(SchedulerSettings(_env_file=None, state_directory=root / "locks"),
                                  repository=SQLiteCollectionRepository(database), client_factory=TracedClient)
        collected = await runner.run(sources, trigger="browser_session_verification", history=all_sources)
        require(collected.persisted and collected.status in {"prepared", "unchanged"} and not collected.failures,
                "Real-source browser fixture collection failed.")
        trace = world_gdp_trace(database, receipts["world_bank_gdp"], receipts["world_bank_gdp.metadata"])
        receipts.clear()  # Publisher bodies stay transient and never reach the browser.
        scheduler = CollectorScheduler(runner, runner.settings)
        async def scheduled_check(mode):
            nonlocal source_fault
            source_fault = mode
            now = datetime.now(timezone.utc)
            scheduler.next_due = {policy.source_id: now + timedelta(days=30) for policy in scheduler.policies}
            scheduler.next_due["world_bank_gdp"] = now
            previous = runner.repository_bridge.repository.load()
            def archive():
                with database.connection(read_only=True) as connection:
                    return tuple(tuple(row) for row in connection.execute("SELECT * FROM observations ORDER BY observation_id"))
            before = archive()
            try:
                await scheduler.tick()
                result = runner.last_run
                require(result is not None and result.trigger == "scheduled" and result.persisted,
                        "Scheduled source state was not committed.")
                checkpoint = runner.repository_bridge.repository.load()
                require(checkpoint.envelope.run_id == result.run_id and checkpoint.envelope.run_id != previous.envelope.run_id,
                        "Scheduled checkpoint did not reach SQL.")
                if mode != "recover":
                    require(result.failures > 0 and result.status == "failed", "Invalid publisher result was accepted.")
                    require(archive() == before,
                            "Failed scheduled collection changed archived observations.")
                    return None
                require(not result.failures and result.status in {"prepared", "unchanged"}, "Scheduled recovery failed.")
                return world_gdp_trace(database, receipts["world_bank_gdp"], receipts["world_bank_gdp.metadata"])
            finally:
                source_fault = None
                receipts.clear()
        username, password = "browser_check", token_urlsafe(32)
        users = UserStore(database)
        users.provision(username, password)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            frontend_port = probe.getsockname()[1]
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        api_url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        app = create_app(Settings(_env_file=None, app_env="test", cors_allowed_origins=[f"http://127.0.0.1:{frontend_port}"]),
            database_settings=settings, scheduler_settings=SchedulerSettings(_env_file=None, enabled=False),
            auth_settings=AuthSettings(_env_file=None, app_env="test", jwt_signing_key=token_hex(32)))
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", log_level="critical", access_log=False,
                                              proxy_headers=False, loop="asyncio"))
        thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        process = watchdog = None
        try:
            deadline = monotonic() + 10
            while not server.started and thread.is_alive() and monotonic() < deadline:
                sleep(0.02)
            require(server.started, "Isolated backend did not start.")
            process = subprocess.Popen([node, "scripts/verify-session.mjs"], cwd=BACKEND_DIRECTORY.parent / "frontend",
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
            watchdog = Timer(120, process.kill)
            watchdog.start()
            process.stdin.write(json.dumps({"api_url": api_url, "frontend_port": frontend_port,
                                           "username": username, "password": password, "world_trace": trace}) + "\n")
            process.stdin.flush()
            result = None
            for line in process.stdout:
                item = json.loads(line)
                if "control" in item:
                    action = item["control"]
                    require(action in {"disable", "enable", "source_timeout", "source_invalid", "source_recover"}, "Unknown private test control.")
                    if action.startswith("source_"):
                        recovered_trace = await scheduled_check(action.removeprefix("source_"))
                        reply = {"ok": True, "trace": recovered_trace}
                    else:
                        users.set_active(username, action == "enable")
                        reply = {"ok": True}
                    process.stdin.write(json.dumps(reply) + "\n")
                    process.stdin.flush()
                else:
                    result = item
            process.stdin.close()
            errors = process.stderr.read()
            status = process.wait(timeout=10)
            require(status == 0 and result is not None, "Browser session check failed: " + errors[-2000:])
            return result | {"source_count": len(sources), "authentication_verified": True,
                             "scope": "local_production_ui_and_real_api", "hosted_acceptance_verified": False}
        finally:
            if watchdog:
                watchdog.cancel()
            if process and process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            server.should_exit = True
            thread.join(timeout=10)
            listener.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all-sources", action="store_true")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(verify(all_sources=args.all_sources)), sort_keys=True))


if __name__ == "__main__":
    main()
