"""Local M6 acceptance and M7 handoff; stdout JSON only, no saved reports.

Run from backend: python -m app.verify_release --browser
Exit 0 means local checks passed, NOT submission approval. Hosted/manual/source
gates stay explicit. Uses this interpreter, disposable browser storage/accounts,
and the existing frontend build output. Never changes accounts or Git references.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from time import monotonic

from app.collectors.catalog import CATALOG_PATH, SourceRegistry
from app.config import BACKEND_DIRECTORY, CollectorSettings, DatabaseSettings, SchedulerSettings, Settings
from app.auth.settings import AuthSettings
from app.api_models import HealthResponse

ROOT = BACKEND_DIRECTORY.parent
FRONTEND = ROOT / "frontend"
LOCAL_CHECKS = ("wire_contract", "requirements", "production_config", "backend_tests", "frontend_tests", "frontend_build")


def acceptance(checks, requirements):
    """A successful test runner must never clear source or external release gates."""
    statuses = {item["name"]: item["status"] for item in checks}
    local = "FAIL" if any(value == "FAIL" for value in statuses.values()) else (
        "PASS" if all(statuses.get(name) == "PASS" for name in LOCAL_CHECKS) else "UNVERIFIED")
    blocked = [{"id": key, "reason": item["reason_code"], "owner": "M3"}
               for key, item in requirements.items() if item["status"] == "blocked"]
    unknown = [key for key, item in requirements.items() if item["status"] not in {"selected", "derived", "blocked"}]
    if unknown:
        local = "FAIL"
    return {"local_checks": local, "integrated_browser": statuses.get("real_browser", "UNVERIFIED"),
            "source_coverage": "BLOCKED" if blocked else "UNVERIFIED", "source_blockers": blocked,
            "unrecognized_requirements": unknown,
            "all_populated_panel_publisher_traces": {"status": "UNVERIFIED", "owner": "M3/M6", "note": "World GDP is independently traced when integrated_browser=PASS; remaining per-panel publisher traces need review."},
            "manual_design_accessibility": {"status": "UNVERIFIED", "owner": "M2/M6"},
            "hosted_tls_cors_storage_scheduler": {"status": "UNVERIFIED", "owner": "M7"},
            "linux_file_permissions": {"status": "UNVERIFIED", "owner": "M7"},
            "portfolio_submission_access": {"status": "UNVERIFIED", "owner": "User/M7"},
            "submission_ready": False}


def run_check(name, command, directory, timeout=120):
    print(f"Checking {name}...", file=sys.stderr, flush=True)
    start = monotonic()
    try:
        result = subprocess.run(command, cwd=directory, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return {"name": name, "status": "FAIL", "reason": "command_unavailable_or_timed_out"}
    item = {"name": name, "status": "PASS" if result.returncode == 0 else "FAIL",
            "seconds": round(monotonic() - start, 2)}
    # Child output stays transient: never echo arbitrary environment/error text.
    output = result.stdout + "\n" + result.stderr
    count = re.search(r"Ran (\d+) tests|(?:#|ℹ) tests (\d+)", output)
    if count:
        item["tests"] = int(next(value for value in count.groups() if value is not None))
    skipped = re.search(r"OK \(skipped=(\d+)\)", output)
    if skipped:
        item["skipped"] = int(skipped[1])
    if name == "real_browser" and item["status"] == "PASS":
        try:
            body = json.loads(result.stdout)
            views = body["visualAudit"]["views"]
            if (body["result"] != "PASS" or body["source_count"] != 5 or len(views) != 6
                    or any(view["issues"] for view in views) or not body["reliabilityAudit"]["timerCleanupVerified"]):
                raise ValueError()
            item.update(sources=5, viewport_modes=6, session_scenarios=body["scenarios"])
        except (ValueError, KeyError, TypeError):
            item.update(status="FAIL", reason="browser_result_invalid")
    return item


def revision():
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8", timeout=10).strip()
    head = git("rev-parse", "HEAD")
    clean = not git("status", "--porcelain")
    return {"head": head, "working_tree_clean": clean,
            "deployment_candidate": head if clean else None,
            "note": "Commit reviewed changes and rerun if dirty; no tag/branch is created."}


def checked_revision(before, after, *, checks_passed=False):
    result = dict(after)
    if not checks_passed:
        result["deployment_candidate"] = None
        result["note"] = "Full local checks and --browser must pass before naming a deployment candidate."
    elif not before["working_tree_clean"] or before["head"] != after["head"]:
        result["deployment_candidate"] = None
        result["note"] = "Verification began dirty or Git HEAD changed during checks; commit/review and rerun."
    return result


def handoff():
    from app.main import create_app
    app = create_app(Settings(_env_file=None, app_env="test"),
                     scheduler_settings=SchedulerSettings(_env_file=None, enabled=False),
                     auth_settings=AuthSettings(_env_file=None, app_env="test"))
    endpoints = [{"method": method.upper(), "path": path, "access": "bearer" if any(
        "DashboardBearer" in scheme for scheme in operation.get("security", [])) else "public"}
                 for path, methods in app.openapi()["paths"].items() for method, operation in methods.items()
                 if method in {"get", "post"}]
    environment = {}
    for group, model in (("api", Settings), ("auth", AuthSettings), ("database", DatabaseSettings),
                         ("collector", CollectorSettings), ("scheduler", SchedulerSettings)):
        prefix = model.model_config.get("env_prefix", "")
        environment[group] = [prefix + name.upper() for name in model.model_fields if name != "app_env"]
    environment["api"].append("APP_ENV")
    environment["frontend"] = ["VITE_API_BASE_URL"]
    environment["host_runtime"] = ["PORT", "PYTHON_VERSION", "NODE_VERSION", "SKIP_INSTALL_DEPS"]
    registry = SourceRegistry.load()
    return {"environment_names_only": environment, "endpoints": endpoints,
            "health": {"path": "/health", "responses": {"200": {"status": "ok"}, "503": {"status": "unavailable"}},
                       "model": HealthResponse.model_json_schema(), "scope": "Local DB/schema readiness; not upstream freshness."},
            "selected_sources": [{"id": sid, "url": registry.resources[sid].url} for sid in registry.source_ids],
            "source_url_scope": "Reviewed seed routes; observation attribution in SQL/API also includes discovered releases and metadata URLs.",
            "startup": {"local_backend_from_backend": "python run.py", "local_frontend_from_frontend": "npm run dev -- --strictPort",
                        "frontend_build_from_frontend": "npm ci && npm run build",
                        "hosted_backend_from_backend": "python -m app.production",
                        "production_env_check_from_backend": "python -m app.production --check",
                        "blueprint_check_from_backend": "python -m app.production --check-blueprint",
                        "database_bootstrap_from_backend": "python -m app.database",
                        "evaluator_provision_from_backend": "python -m app.auth.provision --username evaluator"},
            "topology": "Two independent Render services: static React CDN and paid Python API. One API worker/instance; persistent /var/data/economic-dash for DB and scheduler locks. Blueprint: render.yaml.",
            "rollback": "Manually redeploy a verified Git SHA/deploy, then verify env/CORS/key settings and health. Disk/schema are NOT rolled back; take a SQLite-consistent backup before schema changes and verify restore compatibility. Auto-deploys remain off.",
            "production_docs": "Public Swagger at /docs and schema at /openapi.json; data routes require bearer authentication. Swagger authorization is not persisted; /redoc is disabled.",
            "evaluator_walkthrough": ["Provision on hosted persistent DB using hidden prompt; share credentials privately.",
                                      "Sign in; inspect six panels/ticker and source/as-of details; unavailable feeds stay unavailable.",
                                      "Change history window/period, inspect chart/table, reset Latest view and Refresh data.",
                                      "Sign out; reload and expiry require sign-in; tokens default to 15 minutes in memory."],
            "hosted_smoke": ["Check separate HTTPS frontend/API origins and public /health; reject unauthenticated dashboard GET.",
                             "Verify allowed/rejected CORS origins, no credentials/DB assets in frontend, no upstream browser fetches.",
                             "Verify hosted evaluator, source reachability, scheduled updates and restart persistence with one worker.",
                             "Run Linux permission tests and private-storage probes; repeat 1214x2159 design/keyboard checks.",
                             "Independently trace available series per panel to publisher/SQL/API/UI; retain source blockers.",
                             "Validate repository, portfolio, submission URLs and private evaluator handoff before release."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", action="store_true", help="Also run all-five-source Chrome visual/reliability checks.")
    args = parser.parse_args()
    before = revision()
    node = shutil.which("node") or "node"
    checks = [run_check("wire_contract", [sys.executable, "-m", "app.generate_public_contract", "--check"], BACKEND_DIRECTORY),
              run_check("requirements", [node, "scripts/verify-requirements.mjs"], FRONTEND),
              run_check("production_config", [sys.executable, "-m", "app.production", "--check-blueprint"], BACKEND_DIRECTORY),
              run_check("backend_tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"], BACKEND_DIRECTORY),
              run_check("frontend_tests", [node, "--test", "--test-concurrency=1", *[
                  f"scripts/{name}.mjs" for name in ("test-ui", "test-auth", "test-panel-explorer", "test-integration-inventory", "test-boundaries", "test-production")]], FRONTEND),
              run_check("frontend_build", [node, "node_modules/typescript/bin/tsc", "--noEmit"], FRONTEND)]
    # Invoke installed package entry points directly; no shell/npm.cmd quoting or
    # arbitrary command interpolation, and no additional dependency installation.
    if checks[-1]["status"] == "PASS":
        checks[-1] = run_check("frontend_build", [node, "node_modules/vite/bin/vite.js", "build"], FRONTEND)
    if args.browser:
        checks.append(run_check("real_browser", [sys.executable, "-m", "app.verify_session", "--all-sources", "--visual", "--reliability"], BACKEND_DIRECTORY, 240))
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    gate = acceptance(checks, catalog["requirements"])
    result = {"scope": "local_acceptance_only", "revision": checked_revision(before, revision(),
              checks_passed=gate["local_checks"] == "PASS" and gate["integrated_browser"] == "PASS"),
              "checks": checks, "acceptance": gate, "handoff": handoff()}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["acceptance"]["local_checks"] == "PASS" and not result["acceptance"]["unrecognized_requirements"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
