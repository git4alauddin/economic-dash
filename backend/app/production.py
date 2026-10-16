"""Render production launcher and non-mutating config checks; never prints secrets.

python -m app.production --check-blueprint  # Local repository contract only.
python -m app.production --check            # Injected env only; no storage probe.
python -m app.production                    # Runtime mount/migrations in lifespan.
"""

import argparse
from ipaddress import ip_address
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

from pydantic import ValidationError
from pydantic_settings.exceptions import SettingsError

from app.auth.settings import AuthSettings
from app.config import BACKEND_DIRECTORY, CollectorSettings, DatabaseSettings, SchedulerSettings, Settings

ROOT = BACKEND_DIRECTORY.parent


class ProductionConfigurationError(ValueError):
    """Only application-authored messages and schema field names are public."""


def require(condition, message):
    if not condition:
        raise ProductionConfigurationError(message)


def checked_settings(model, **options):
    try:
        return model(_env_file=None, **options)
    except ValidationError as error:
        fields = sorted({item["loc"][0] for item in error.errors(include_input=False, include_context=False, include_url=False)
                         if item["loc"] and item["loc"][0] in model.model_fields})
        prefix = model.model_config.get("env_prefix", "")
        names = ", ".join((prefix + field).upper() for field in fields)
        raise ProductionConfigurationError(f"{model.__name__}: invalid {names or 'settings combination'}. Check production environment values.") from None
    except SettingsError:
        # SettingsError text can contain raw environment input; never print it.
        raise ProductionConfigurationError(f"{model.__name__}: environment parsing failed. Check JSON list formats for CORS_ALLOWED_ORIGINS/TRUSTED_PROXY_IPS.") from None


def public_origin(value):
    url = urlsplit(value)
    host = url.hostname or ""
    require(url.scheme == "https" and not (url.username or url.password or url.path or url.query or url.fragment or url.port), "Invalid public HTTPS origin.")
    require("." in host and not re.search(r"(?:^|\.)(localhost|local|internal|invalid|example|test)$", host), "Invalid public hostname.")
    require(len(host) <= 253 and all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split(".")), "Invalid public hostname.")
    try:
        ip_address(host)
    except ValueError:
        return value
    raise ProductionConfigurationError("Use the assigned HTTPS service hostname.")


def production_settings():
    # Ignore developer dotenv files. All production values must be injected.
    settings = checked_settings(Settings)
    require(settings.app_env == "production", "APP_ENV must be production.")
    require(not settings.trusted_proxy_ips, "Proxy peer verification is pending; keep TRUSTED_PROXY_IPS empty.")
    public_origin(settings.cors_allowed_origins[0])
    auth = checked_settings(AuthSettings, app_env="production")
    database = checked_settings(DatabaseSettings, app_env="production")
    scheduler = checked_settings(SchedulerSettings, state_directory=os.environ.get(
        "COLLECTOR_SCHEDULER_STATE_DIRECTORY", "/var/data/economic-dash"))
    require(database.directory == Path("/var/data/economic-dash").resolve()
            and scheduler.state_directory == database.directory, "Database and scheduler must share the reviewed private directory.")
    require(scheduler.enabled, "Production collector scheduling must be enabled.")
    checked_settings(CollectorSettings)  # Validate optional bounded acquisition overrides.
    port = os.environ.get("PORT", "")
    require(bool(re.fullmatch(r"[0-9]{1,5}", port)) and 1 <= int(port) <= 65535, "Render must supply a valid PORT.")
    pin = (BACKEND_DIRECTORY / ".python-version").read_text().strip()
    require(".".join(map(str, sys.version_info[:3])) == pin, "Python runtime does not match the repository pin.")
    return settings, auth, database, scheduler, int(port)


def blueprint_contract(spec=None):
    # JSON is a YAML subset, so Render accepts this without a YAML dependency.
    spec = json.loads((ROOT / "render.yaml").read_text()) if spec is None else spec
    require(set(spec) == {"previews", "services"} and spec["previews"] == {"generation": "off"}, "Only reviewed services and disabled previews are permitted.")
    require(len(spec["services"]) == 2, "Exactly two independent services are required.")
    services = {item["runtime"]: item for item in spec["services"]}
    require(set(services) == {"static", "python"}, "Static and Python runtimes are required.")
    api, web = services["python"], services["static"]
    require(api["name"] != web["name"], "Service identities must differ.")
    for item, root in ((api, "backend"), (web, "frontend")):
        require(item["type"] == "web" and item["rootDir"] == root and item["branch"] == "main"
                and item["autoDeployTrigger"] == "off" and "preDeployCommand" not in item,
                "Service roots, manual deployments or runtime migration boundary changed.")
    require(api["plan"] == "0.5c-512mb" and api["numInstances"] == 1 and "scaling" not in api
            and api["disk"] == {"name": "dashboard-data", "mountPath": "/var/data", "sizeGB": 1}
            and api["healthCheckPath"] == "/health" and api["startCommand"] == "python -m app.production"
            and api["buildCommand"] == "python -m pip install -r requirements.txt", "Private single-instance runtime changed.")
    require(web["staticPublishPath"] == "dist" and "disk" not in web and "startCommand" not in web,
            "Only frontend build assets may be published.")
    npm = json.loads((ROOT / "frontend/package.json").read_text())["packageManager"]
    require(web["buildCommand"] == f"npx --yes {npm} ci --include=dev && npx --yes {npm} run build:render", "Frontend pinned build changed.")
    environments = {}
    for role, item in (("api", api), ("web", web)):
        env = {row["key"]: row for row in item["envVars"]}
        require(len(env) == len(item["envVars"]), "Duplicate environment keys.")
        environments[role] = env
    for env, key in ((environments["api"], "AUTH_JWT_SIGNING_KEY"), (environments["api"], "CORS_ALLOWED_ORIGINS"),
                     (environments["web"], "VITE_API_BASE_URL")):
        require(env[key] == {"key": key, "sync": False}, "Secret/origin must be entered in Render, never baked into config.")
    api_env, web_env = environments["api"], environments["web"]
    for key, expected in {"APP_ENV": "production", "TRUSTED_PROXY_IPS": "[]", "DATABASE_DIRECTORY": "/var/data/economic-dash",
                          "COLLECTOR_SCHEDULER_STATE_DIRECTORY": "/var/data/economic-dash", "COLLECTOR_SCHEDULER_ENABLED": "true",
                          "AUTH_ACCESS_TOKEN_MINUTES": "15", "PYTHON_VERSION": (BACKEND_DIRECTORY / ".python-version").read_text().strip()}.items():
        require(api_env[key] == {"key": key, "value": expected}, "Required production setting changed.")
    require(set(web_env) == {"VITE_API_BASE_URL", "NODE_VERSION", "SKIP_INSTALL_DEPS"}
            and web_env["NODE_VERSION"]["value"] == (ROOT / ".node-version").read_text().strip()
            and web_env["SKIP_INSTALL_DEPS"]["value"] == "true", "Frontend environment boundary or runtime pin changed.")
    require(not any(key.startswith("VITE_") for key in api_env), "No public build variables on the backend.")
    return {"result": "PASS", "scope": "local_blueprint_contract", "services": 2, "hosted_validation": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--check-blueprint", action="store_true")
    args = parser.parse_args()
    try:
        if args.check_blueprint:
            print(json.dumps(blueprint_contract()))
            return 0
        settings, auth, database, scheduler, port = production_settings()
        if args.check:
            print(json.dumps({"result": "PASS", "scope": "environment_only", "mount_verified": False}))
            return 0
        require(not (BACKEND_DIRECTORY / ".env").exists(), "Production uses injected environment; remove local dotenv files.")
        import uvicorn
        from app.main import create_app
        app = create_app(settings, auth_settings=auth, database_settings=database, scheduler_settings=scheduler)
        uvicorn.run(app, host="0.0.0.0", port=port, workers=1, reload=False, access_log=False, proxy_headers=False)
        return 0
    except ProductionConfigurationError as error:
        print(f"Production configuration invalid: {error}", file=sys.stderr)
        return 1
    except (ValidationError, SettingsError, ValueError, KeyError, TypeError, OSError):
        print("Production configuration invalid; check blueprint, runtime pins, HTTPS origin, secret format, PORT and private paths.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
