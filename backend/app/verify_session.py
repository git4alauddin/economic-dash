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
from tempfile import TemporaryDirectory, gettempdir
from threading import Thread, Timer
from time import monotonic, sleep

import uvicorn
import jwt

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


def audit_public_site(directory, markers, console):
    """Inspect disposable build/console bytes; never return matching private data."""
    site = Path(directory).resolve(strict=True)
    relative = site.relative_to(Path(gettempdir()).resolve())
    require(len(relative.parts) == 2 and relative.parts[0].startswith("economic-dash-browser-") and relative.parts[1] == "site",
            "Public audit requires the isolated browser build.")
    forbidden = tuple(value.encode("utf-8") for value in markers if value)
    count = 0
    for path in site.rglob("*"):
        require(not path.is_symlink(), "Public build contains a linked path.")
        if not path.is_file():
            continue
        require(path.stat().st_size <= 2_000_000, "Public audit asset exceeded its size budget.")
        content = path.read_bytes()
        require(not any(marker in content for marker in forbidden), "Private material reached a public build asset.")
        require(b"SQLite format 3\x00" not in content and b"$argon2id$" not in content, "Private storage material reached a public build asset.")
        count += 1
    require(count > 0, "Public build audit found no assets.")
    require(isinstance(console, list) and len(console) <= 1000 and all(isinstance(line, str) for line in console),
            "Invalid private console audit input.")
    for line in console:
        require(not any(marker in line.encode("utf-8") for marker in forbidden), "Private material reached browser console output.")
    return count


async def verify(*, all_sources=False, visual=False, inspect_visual=False, reliability=False):
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
        username, password = "evaluator", token_urlsafe(32)
        users = UserStore(database)
        evaluator = users.provision(username, password).identity
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            frontend_port = probe.getsockname()[1]
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        api_url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        # Churn adds five successful logins to the existing auth matrix. Raise
        # admission only for this disposable process; production policy is unchanged.
        auth_settings = AuthSettings(_env_file=None, app_env="test", jwt_signing_key=token_hex(32),
                                     login_client_attempts=30 if reliability else 10)
        app = create_app(Settings(_env_file=None, app_env="test", cors_allowed_origins=[f"http://127.0.0.1:{frontend_port}"]),
            database_settings=settings, scheduler_settings=SchedulerSettings(_env_file=None, enabled=False),
            auth_settings=auth_settings)
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
                                           "username": username, "password": password, "world_trace": trace,
                                           "visual": visual or inspect_visual, "inspect_visual": inspect_visual,
                                           "reliability": reliability}) + "\n")
            process.stdin.flush()
            result = None
            for line in process.stdout:
                item = json.loads(line)
                if "control" in item:
                    action = item["control"]
                    require(action in {"disable", "enable", "source_timeout", "source_invalid", "source_recover", "token_cases", "audit_public"}, "Unknown private test control.")
                    if action.startswith("source_"):
                        recovered_trace = await scheduled_check(action.removeprefix("source_"))
                        reply = {"ok": True, "trace": recovered_trace}
                    elif action == "token_cases":
                        valid = app.state.auth_service.issue(evaluator).token
                        head, payload, signature = valid.split(".")
                        key = bytes.fromhex(auth_settings.jwt_signing_key.get_secret_value())
                        claims = jwt.decode(valid, key, algorithms=["HS256"], audience=auth_settings.jwt_audience, issuer=auth_settings.jwt_issuer)
                        now = int(datetime.now(timezone.utc).timestamp())
                        claims.update(iat=now - 1800, nbf=now - 1800, exp=now - 900)
                        reply = {"ok": True, "tokens": {
                            "expired": jwt.encode(claims, key, algorithm="HS256", headers={"typ": "at+jwt"}),
                            "tampered": ".".join((head, payload, ("A" if signature[0] != "A" else "B") + signature[1:])),
                        }}
                    elif action == "audit_public":
                        with database.connection(read_only=True) as connection:
                            encoded = connection.execute("SELECT password_hash FROM auth_users WHERE user_id=?", (evaluator.user_id,)).fetchone()[0]
                        local_key = AuthSettings().jwt_signing_key
                        count = audit_public_site(item["directory"], (password, encoded, auth_settings.jwt_signing_key.get_secret_value(),
                                                  local_key.get_secret_value() if local_key else ""), item.get("console", []))
                        reply = {"ok": True, "assets_checked": count}
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
                             "test_login_client_attempts": auth_settings.login_client_attempts,
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
    parser.add_argument("--visual", action="store_true", help="Audit real-data viewport/usability in memory; no evidence files.")
    parser.add_argument("--inspect-visual", action="store_true", help="Also return one in-memory JPEG for interactive inspection.")
    parser.add_argument("--reliability", action="store_true", help="Measure slow reads, request coalescing and session cleanup in memory.")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(verify(all_sources=args.all_sources, visual=args.visual,
                                      inspect_visual=args.inspect_visual, reliability=args.reliability)), sort_keys=True))


if __name__ == "__main__":
    main()
