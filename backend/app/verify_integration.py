"""Real collector -> temporary SQL -> API -> frontend check; saves no reports.

Run from backend: python -m app.verify_integration [--all-sources].
Requires the frontend's installed Node dependencies. Signs in with a private
temporary account/key and exercises real JWT guards without overrides. UI and
hosted acceptance remain M6/M7. The configured application database is never used.
"""

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from secrets import token_hex, token_urlsafe
import shutil
import subprocess
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.api_models import DashboardData, Envelope
from app.auth.settings import AuthSettings
from app.collectors.catalog import SourceRegistry
from app.collectors.handoff import RepositoryBridge
from app.collectors.history import trade_balance
from app.collectors.observations import NormalizedObservation
from app.collectors.runner import CollectionRunner
from app.config import BACKEND_DIRECTORY, DatabaseSettings, SchedulerSettings, Settings
from app.database import Database
from app.main import create_app
from app.repository import SQLiteCollectionRepository, observation_from_row


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_dashboard(body, service, *, required_sources=()):
    """Check complete mapping and every displayed value against archived inputs."""
    Envelope[DashboardData].model_validate_json(json.dumps(body))
    panels, inventory = body["data"]["panels"], service.inventory
    require(set(panels) == set(service.panels), "Panel coverage differs from inventory.")
    requirements, supported = set(), set()
    unbound = {(p["indicator_id"], p["summary_slot"]): p["id"] for p in inventory["unbound_requirements"]}
    with service.database.connection(read_only=True) as connection:
        def archived(sid, point):
            row = connection.execute("""SELECT * FROM observations WHERE series_id=? AND definition_id=?
                AND period_id=? AND vintage_id=? AND parser_version=?""",
                (sid, point["definition_id"], point["observation_period"]["id"], point["vintage_id"], point["parser_version"])).fetchone()
            require(row is not None, "Displayed observation has no SQL provenance.")
            return observation_from_row(connection, row)

        def check_point(sid, point):
            definition = service.catalog["requirements"][sid]
            require(point["definition_id"] == definition["definition_id"] and point["unit"] == definition["unit"], "Definition/unit changed.")
            if definition["status"] == "blocked":
                require(point["value"] is None and point["status"] == "unavailable"
                        and point["reason_code"] == definition["reason_code"], "Blocked requirement acquired an invented value/state.")
            if point["value"] is None:
                return
            if definition["status"] == "derived":
                inputs = tuple(NormalizedObservation.model_validate_json(json.dumps(p)) for p in point["inputs"])
                require(sid == "trade_balance" and tuple(p.series_id for p in inputs) == ("exports", "imports"), "Derived inputs changed.")
                for value in inputs:
                    require(value == archived(value.series_id, value.model_dump(mode="json")), "Derived input differs from SQL.")
                expected = trade_balance(*inputs).model_dump(mode="json")
            else:
                expected = archived(sid, point).model_dump(mode="json")
            for field in ("value", "unit", "definition_id", "observation_period", "as_of", "as_of_precision", "as_of_kind",
                          "sources", "published_at", "retrieved_at", "dataset_updated_at", "revision_kind", "vintage_id",
                          "parser_version", "normalization_id", "transform_id", "inputs"):
                require(point[field] == expected[field], f"API/SQL observation mismatch: {field}.")

        for pid, panel in panels.items():
            expected_series = {entry["id"] for entry in service.panels[pid]["series"]}
            require(set(panel["series"]) == expected_series, "Series coverage differs from inventory.")
            for sid, entry in panel["series"].items():
                requirements.add(sid)
                check_point(sid, entry["latest"])
                for point in entry["history"]["points"]:
                    check_point(sid, point)
                if entry["latest"]["value"] is not None:
                    supported.add(sid)
            cards = panel["summaries"]
            require(len(cards) == len(service.panels[pid]["summaries"]), "Summary count changed.")
            for slot, sid in enumerate(service.panels[pid]["summaries"]):
                rid = sid or unbound[(pid, slot)]
                card = cards[slot]
                require(card["slot"] == slot and card["requirement_id"] == rid, "Summary mapping changed.")
                requirements.add(rid)
                if sid:
                    latest = panel["series"][sid]["latest"]
                    require(card["observation"] is not None and all(card["observation"][k] == latest[k]
                            for k in ("value", "unit", "definition_id", "as_of", "sources")), "Summary differs from its series.")
                else:
                    require(card["observation"] is None and card["reason_code"] == service.catalog["requirements"][rid]["reason_code"], "Unbound card lost its blocker.")
        quotes = body["data"]["ticker"]["items"]
        require({q["instrument_id"] for q in quotes} == {q["instrument_id"] for q in inventory["ticker"]["instruments"]}, "Ticker coverage changed.")
        for quote in quotes:
            rid = quote["instrument_id"]
            requirements.add(rid)
            require(quote["value"] is None and quote["status"] == "unavailable"
                    and quote["reason_code"] == service.catalog["requirements"][rid]["reason_code"], "Ticker blocker changed.")
    require(requirements == set(service.catalog["requirements"]), "Requirement coverage is incomplete.")
    expected_supported = {sid for sid in service.series_ids if service.catalog["requirements"][sid]["status"] != "blocked"
                          and service.catalog["requirements"][sid]["source_id"] in required_sources}
    require(expected_supported <= supported, "Selected source did not supply all supported series.")
    return {"panels": len(panels), "summary_slots": sum(len(p["summaries"]) for p in panels.values()),
            "series": sum(len(p["series"]) for p in panels.values()), "requirements": len(requirements),
            "supported_series": len(supported), "blocked_requirements": sum(d["status"] == "blocked" for d in service.catalog["requirements"].values())}


def check_api(settings, sources):
    """Reopen committed SQL with a fresh app; exercise real routes and failures."""
    require(settings.app_env == "test", "Integration checks require isolated test storage settings.")
    auth = AuthSettings(_env_file=None, app_env="test", jwt_signing_key=token_hex(32))
    username, password = "integration_check", token_urlsafe(48)
    def application():
        return create_app(Settings(_env_file=None, app_env="test"), database_settings=settings,
                          auth_settings=auth,
                          scheduler_settings=SchedulerSettings(_env_file=None, enabled=False))
    app = application()
    with TestClient(app) as client:
        users = app.state.auth_service.users
        users.provision(username, password)
        require(client.get("/health").status_code == 200, "Database health failed.")
        paths = ["/api/v1/dashboard", "/api/v1/indicators", "/api/v1/ticker"]
        service = app.state.dashboard_queries
        for pid, panel in service.panels.items():
            paths.append(f"/api/v1/indicators/{pid}")
            paths.extend(f"/api/v1/indicators/{pid}/history?series_id={s['id']}" for s in panel["series"])
        for path in paths:
            require(client.get(path).status_code == 401, "Missing credentials reached data.")
            require(client.get(path, headers={"Authorization": "Bearer unverified"}).status_code == 401, "Unverified credentials reached data.")
        login = client.post("/api/v1/auth/login", json={"username": username, "password": password})
        require(login.status_code == 200, "Private integration account could not sign in.")
        token = login.json()["access_token"]
        client.headers["Authorization"] = "Bearer " + token
        require(client.get("/api/v1/auth/me").status_code == 200, "JWT identity verification failed.")
        require(not app.dependency_overrides, "Integration must not override authorization.")
        for path in paths:
            require(client.get(path).status_code == 200, "A declared read route failed.")
        first = client.get("/api/v1/dashboard?window=24")
        body = first.json()
        counts = validate_dashboard(body, service, required_sources=sources)
        unchanged = client.get("/api/v1/dashboard?window=24", headers={"If-None-Match": first.headers["etag"]})
        require(unchanged.status_code == 304 and not unchanged.content, "Unchanged polling failed.")
        repository = app.state.collection_repository
        checkpoint = repository.load()
        require(checkpoint is not None and checkpoint.acknowledgement.verifies(checkpoint.envelope), "Checkpoint reload failed.")
        cache = RepositoryBridge(repository).open_cache()
        now = datetime.now(timezone.utc)
        require(cache.record_failure(sources, run_id="integration-controlled-outage", started=now, finished=now,
                                     reason="timeout", trigger="integration_verification"), "Controlled failure was not committed.")
        failed = client.get("/api/v1/dashboard?window=24", headers={"If-None-Match": first.headers["etag"]})
        require(failed.status_code == 200 and failed.headers["etag"] != first.headers["etag"], "Failure did not change representation.")
        validate_dashboard(failed.json(), service, required_sources=sources)
        for pid, panel in body["data"]["panels"].items():
            for sid, entry in panel["series"].items():
                old = entry["latest"]
                new = failed.json()["data"]["panels"][pid]["series"][sid]["latest"]
                if old["value"] is not None:
                    require(new["status"] == "stale" and new["retention_allowed"], "Outage lost retained state.")
                    require(all(new[k] == old[k] for k in ("value", "as_of", "retrieved_at", "sources", "observation_period")), "Outage changed observation provenance.")
        users.set_active(username, False)
        denied = client.get("/api/v1/dashboard?window=24", headers={"If-None-Match": failed.headers["etag"]})
        require(denied.status_code == 401, "Authorization failure became a cached response.")
        transcript = []
        for response, sent in ((first, None), (unchanged, first.headers["etag"]), (failed, first.headers["etag"]), (denied, failed.headers["etag"])):
            item = {"status": response.status_code, "headers": dict(response.headers), "expected_if_none_match": sent}
            if response.status_code == 200:
                item["body"] = response.json()
                item["expected_world_status"] = item["body"]["data"]["panels"]["gdp_growth"]["series"]["gdp_growth_world"]["latest"]["status"]
            transcript.append(item)
        users.set_active(username, True)
    restarted = application()
    with TestClient(restarted) as client:
        login = client.post("/api/v1/auth/login", json={"username": username, "password": password})
        require(login.status_code == 200, "Reopened private account could not sign in.")
        client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
        require(client.get("/api/v1/dashboard?window=24", headers={"Authorization": "Bearer " + token}).status_code == 401,
                "Revoked token became valid after account re-enable/restart.")
        reloaded = client.get("/api/v1/dashboard?window=24")
        require(reloaded.status_code == 200 and reloaded.json()["data"] == failed.json()["data"], "Fresh application lost durable failure/data state.")
    return counts | {"read_routes_checked": len(paths), "restart_reload": True, "failure_retention": True,
                     "authentication_verified": True}, {"polling": transcript, "bearer_token": token}


async def verify(*, all_sources=False):
    node = shutil.which("node")
    require(node is not None, "Install the configured Node runtime and frontend dependencies first.")
    frontend = BACKEND_DIRECTORY.parent / "frontend"
    with TemporaryDirectory(prefix="economic-dash-integration-") as temporary:
        root = Path(temporary)
        settings = DatabaseSettings(_env_file=None, app_env="test", directory=root / "database")
        database = Database(settings)
        database.bootstrap()
        repository = SQLiteCollectionRepository(database)
        sources = SourceRegistry.load().source_ids if all_sources else ("world_bank_gdp",)
        runner = CollectionRunner(SchedulerSettings(_env_file=None, state_directory=root / "locks"), repository=repository)
        result = await runner.run(sources, trigger="integration_verification", history=all_sources)
        require(result.status in {"prepared", "unchanged"} and result.persisted and not result.failures,
                f"Real-source collection did not pass: {result.status}/{result.reason_code}.")
        counts, transcript = check_api(settings, sources)
        completed = subprocess.run([node, "scripts/verify-api-contract.mjs"], cwd=frontend,
            input=json.dumps(transcript), capture_output=True, text=True, encoding="utf-8", timeout=60)
        require(completed.returncode == 0, "Frontend contract verification failed: " + completed.stderr[-2000:])
        return counts | {"result": "PASS", "scope": "local_integration_test", "source_count": len(sources),
            "frontend_adapter_verified": True, "conditional_statuses": [r["status"] for r in transcript["polling"]],
            "authentication_verified": True, "authentication_mode": "real_jwt_private_temporary_account",
            "ui_e2e_verified": False, "hosted_acceptance_verified": False, "controlled_outage": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all-sources", action="store_true", help="Collect all five selected sources plus reviewed history; default: World Bank first slice.")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(verify(all_sources=args.all_sources)), sort_keys=True))


if __name__ == "__main__":
    main()
