"""Verify environment loading and the browser-origin boundary."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import BACKEND_DIRECTORY, SchedulerSettings, Settings
from app.main import create_app


class ConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment_patch = patch.dict(os.environ, {}, clear=True)
        self.environment_patch.start()
        self.addCleanup(self.environment_patch.stop)

    def test_example_environment_loads(self) -> None:
        settings = Settings(_env_file=BACKEND_DIRECTORY / ".env.example")
        self.assertEqual(settings.app_env, "development")
        self.assertEqual(settings.api_port, 8000)
        self.assertIn("http://127.0.0.1:5173", settings.cors_allowed_origins)

    def test_process_environment_overrides_dotenv(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            env_file = Path(temporary_directory) / ".env"
            env_file.write_text("API_PORT=8100\n", encoding="utf-8")
            self.assertEqual(Settings(_env_file=env_file).api_port, 8100)
            os.environ["API_PORT"] = "8200"
            self.assertEqual(Settings(_env_file=env_file).api_port, 8200)

    def test_invalid_ports_are_rejected(self) -> None:
        for port in [0, 65536]:
            with self.subTest(port=port), self.assertRaises(ValidationError):
                Settings(_env_file=None, api_port=port)

    def test_invalid_cors_origins_are_rejected(self) -> None:
        for origin in [
            "*", "https://*.example.com", "https://example.com/path",
            "https://example.com/", "https://example.com?query=1",
            "https://user:password@example.com", "https://example.com:bad",
        ]:
            with self.subTest(origin=origin), self.assertRaises(ValidationError):
                Settings(_env_file=None, cors_allowed_origins=[origin])

    def test_production_rejects_development_defaults(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, app_env="production")

    def test_production_allows_only_configured_https_frontend(self) -> None:
        origin = "https://dashboard.example.com"
        settings = Settings(
            _env_file=None, app_env="production", cors_allowed_origins=[origin],
        )
        with TestClient(create_app(settings, scheduler_settings=SchedulerSettings(_env_file=None, enabled=False))) as client:
            allowed = client.get("/", headers={"Origin": origin})
            denied = client.get("/", headers={"Origin": "http://localhost:5173"})
        self.assertEqual(allowed.headers["access-control-allow-origin"], origin)
        self.assertNotIn("access-control-allow-origin", denied.headers)

    def test_development_cors_preflight_and_bootstrap(self) -> None:
        with TestClient(create_app(Settings(_env_file=None), scheduler_settings=SchedulerSettings(_env_file=None, enabled=False))) as client:
            response = client.get("/")
            allowed = client.options("/", headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "GET",
            })
            denied = client.options("/", headers={
                "Origin": "https://untrusted.example.com",
                "Access-Control-Request-Method": "GET",
            })
        self.assertEqual(response.json(), {"message": "Economic Indicators API"})
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.headers["access-control-allow-origin"], "http://127.0.0.1:5173")
        self.assertEqual(denied.status_code, 400)
        self.assertNotIn("access-control-allow-origin", denied.headers)


if __name__ == "__main__":
    unittest.main()
