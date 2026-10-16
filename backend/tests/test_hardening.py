"""Login admission, bounded input, production exposure and CORS boundaries."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import runpy
from secrets import token_hex
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.requests import Request

from app.api_errors import ApiError
from app.auth.routes import login_input
from app.auth.settings import AuthSettings
from app.auth.throttling import LoginLimiter
from app.config import BACKEND_DIRECTORY, DatabaseSettings, SchedulerSettings, Settings
from app.main import create_app


class LoginLimiterTests(unittest.TestCase):
    def limiter(self, **options):
        self.now = 100.0
        return LoginLimiter(AuthSettings(_env_file=None, **options), clock=lambda: self.now)

    def denied(self, limiter, client):
        with self.assertRaises(ApiError) as caught:
            limiter.admit(client)
        self.assertEqual(caught.exception.status, 429)
        return caught.exception.headers["Retry-After"]

    def test_sliding_window_expiry_and_blocked_attempts_do_not_extend_lockout(self):
        limiter = self.limiter(login_client_attempts=2, login_window_seconds=60)
        limiter.admit("one")
        self.now += 10
        limiter.admit("one")
        self.assertEqual(self.denied(limiter, "one"), "50")
        self.now = 159.5
        self.assertEqual(self.denied(limiter, "one"), "1")
        self.now = 160
        limiter.admit("one")
        self.assertEqual(self.denied(limiter, "one"), "10")

    def test_global_budget_rejects_rotating_clients(self):
        limiter = self.limiter(login_global_attempts=2)
        limiter.admit("one")
        limiter.admit("two")
        self.assertEqual(self.denied(limiter, "three"), "60")
        self.now += 60
        limiter.admit("three")

    def test_client_registry_is_bounded_without_evicting_active_budgets(self):
        limiter = self.limiter(login_max_clients=2, login_client_attempts=1)
        limiter.admit("one")
        limiter.admit("two")
        self.denied(limiter, "three")
        self.denied(limiter, "one")
        self.now += 60
        limiter.admit("three")
        limiter.admit("four")
        self.denied(limiter, "five")

    def test_concurrent_admission_cannot_exceed_client_or_global_budget(self):
        for clients, options, expected in (
            (["same"] * 40, {"login_client_attempts": 3}, 3),
            ([str(i) for i in range(40)], {"login_global_attempts": 7}, 7),
        ):
            limiter = self.limiter(**options)
            def attempt(client):
                try:
                    limiter.admit(client)
                    return 1
                except ApiError:
                    return 0
            with ThreadPoolExecutor(max_workers=16) as pool:
                self.assertEqual(sum(pool.map(attempt, clients)), expected)


class HardeningTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.app = create_app(Settings(_env_file=None, app_env="test"),
            auth_settings=AuthSettings(_env_file=None, app_env="test", jwt_signing_key=token_hex(32),
                                       login_client_attempts=2, login_global_attempts=4),
            database_settings=DatabaseSettings(_env_file=None, app_env="test", directory=Path(temporary.name) / "db"),
            scheduler_settings=SchedulerSettings(_env_file=None, enabled=False))
        self.client = self.enterContext(TestClient(self.app))
        self.users = self.app.state.auth_service.users
        self.password = "synthetic hardening passphrase"
        self.users.provision("evaluator", self.password)

    def login(self, **kwargs):
        return self.client.post("/api/v1/auth/login", json={"username": "evaluator", "password": self.password}, **kwargs)

    def test_throttled_login_never_hashes_and_returns_safe_cors_readable_429(self):
        origin = "http://localhost:5173"
        with patch.object(self.users, "authenticate", wraps=self.users.authenticate) as authenticate:
            for username in ("evaluator", "unknown"):
                failed = self.client.post("/api/v1/auth/login", json={"username": username, "password": "wrong"})
                self.assertEqual(failed.status_code, 401)
            blocked = self.login(headers={"Origin": origin})
            self.assertEqual(authenticate.call_count, 2)
        self.assertEqual(blocked.status_code, 429)
        self.assertGreaterEqual(int(blocked.headers["retry-after"]), 1)
        self.assertEqual(blocked.headers["access-control-allow-origin"], origin)
        self.assertIn("retry-after", blocked.headers["access-control-expose-headers"].lower())
        self.assertEqual(blocked.headers["cache-control"], "no-store")
        self.assertNotIn(self.password, blocked.text)
        self.assertNotIn("set-cookie", blocked.headers)
        self.assertFalse(self.app.dependency_overrides)

    def test_success_counts_but_throttling_does_not_block_existing_tokens_or_health(self):
        token = self.login().json()["access_token"]
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.login().status_code, 429)
        self.assertEqual(self.client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + token}).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/dashboard", headers={"Authorization": "Bearer " + token}).status_code, 200)
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/dashboard").status_code, 401)

    def test_malformed_attempts_count_and_forwarded_headers_do_not_change_peer(self):
        self.assertEqual(self.client.post("/api/v1/auth/login", json={}).status_code, 422)
        self.assertEqual(self.client.post("/api/v1/auth/login", content="bad").status_code, 415)
        self.assertEqual(self.login(headers={"X-Forwarded-For": "203.0.113.7", "Forwarded": "for=203.0.113.8"}).status_code, 429)

    def test_cors_preflights_do_not_consume_attempts_and_require_exact_origin_method_headers(self):
        origin = "http://localhost:5173"
        cases = [(origin, "POST", "content-type", 200), (origin, "GET", "authorization,if-none-match", 200),
                 (origin, "DELETE", "content-type", 400), (origin, "POST", "x-unapproved", 400),
                 ("http://localhost:5174", "POST", "content-type", 400),
                 ("http://localhost:5173.evil.example", "POST", "content-type", 400)]
        for supplied, method, headers, status in cases:
            result = self.client.options("/api/v1/auth/login", headers={"Origin": supplied,
                "Access-Control-Request-Method": method, "Access-Control-Request-Headers": headers})
            self.assertEqual(result.status_code, status)
            self.assertNotIn("access-control-allow-credentials", result.headers)
            if supplied != origin:
                self.assertNotIn("access-control-allow-origin", result.headers)
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.login().status_code, 200)

    def test_cors_never_replaces_the_bearer_guard_including_errors(self):
        for origin in ("http://localhost:5173", "https://unapproved.example", None):
            headers = {"Origin": origin} if origin else {}
            denied = self.client.get("/api/v1/dashboard", headers=headers)
            self.assertEqual(denied.status_code, 401)
            self.assertEqual(denied.headers.get("access-control-allow-origin"), origin if origin == "http://localhost:5173" else None)
            self.assertEqual(denied.headers["x-content-type-options"], "nosniff")
            self.assertEqual(denied.headers["referrer-policy"], "no-referrer")
            self.assertEqual(denied.headers["x-frame-options"], "DENY")
        token = self.login().json()["access_token"]
        result = self.client.get("/api/v1/dashboard", headers={"Authorization": "Bearer " + token, "Origin": "https://unapproved.example"})
        self.assertEqual(result.status_code, 200)  # Authenticated raw HTTP is valid.
        self.assertNotIn("access-control-allow-origin", result.headers)

    def test_production_disables_docs_schema_and_local_cors_without_starting_hosted_storage(self):
        origin = "https://dashboard.example.com"
        app = create_app(Settings(_env_file=None, app_env="production", cors_allowed_origins=[origin]),
            auth_settings=AuthSettings(_env_file=None, app_env="production", jwt_signing_key=token_hex(32)),
            scheduler_settings=SchedulerSettings(_env_file=None, enabled=False))
        # No lifespan: this checks production route/CORS wiring, not /var/data or TLS.
        client = TestClient(app)
        self.addCleanup(client.close)
        for path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
            self.assertEqual(client.get(path).status_code, 404)
        denied = client.get("/api/v1/dashboard", headers={"Origin": origin})
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(denied.headers["access-control-allow-origin"], origin)
        self.assertNotIn("access-control-allow-origin", client.get("/", headers={"Origin": "http://localhost:5173"}).headers)
        self.assertEqual(self.client.get("/openapi.json").status_code, 200)
        self.assertEqual(self.client.get("/docs").status_code, 200)

    def test_safe_errors_do_not_echo_body_or_internal_failures(self):
        from app.auth.passwords import PasswordWorkBusy
        with patch.object(self.users, "authenticate", side_effect=PasswordWorkBusy(self.password)):
            result = self.login()
        self.assertEqual(result.status_code, 503)
        self.assertNotIn(self.password, result.text)
        result = self.client.post("/api/v1/auth/login", content=json.dumps({"username": "evaluator", "password": self.password, "extra": self.password}),
                                  headers={"Content-Type": "application/json"})
        self.assertEqual(result.status_code, 422)
        self.assertNotIn(self.password, result.text)


class BoundedLoginInputTests(unittest.IsolatedAsyncioTestCase):
    async def parse(self, chunks, headers=None, *, delay=0):
        messages = iter(chunks)
        limiter = LoginLimiter(AuthSettings(_env_file=None))
        async def receive():
            if delay:
                await asyncio.sleep(delay)
            chunk = next(messages)
            return {"type": "http.request", "body": chunk, "more_body": True}
        request = Request({"type": "http", "method": "POST", "path": "/api/v1/auth/login", "query_string": b"",
            "client": ("127.0.0.1", 1000), "headers": headers or [(b"content-type", b"application/json")],
            "app": SimpleNamespace(state=SimpleNamespace(login_limiter=limiter))}, receive=receive)
        return await login_input(request)

    async def test_streamed_body_cap_applies_without_or_with_understated_content_length(self):
        for headers in (None, [(b"content-type", b"application/json"), (b"content-length", b"1")]):
            with self.subTest(headers=headers), self.assertRaises(ApiError) as caught:
                await self.parse([b"a" * 2048, b"b" * 2049], headers)
            self.assertEqual(caught.exception.status, 413)

    async def test_invalid_or_duplicate_length_and_media_headers_fail_before_reading(self):
        cases = [([(b"content-length", value)], status) for value, status in
                 ((b"-1", 400), (b" 10", 400), (b"9" * 100, 413), (b"4097", 413))]
        cases += [([(b"content-length", b"1"), (b"content-length", b"1")], 400),
                  ([(b"content-type", b"text/plain")], 415), ([(b"content-encoding", b"gzip")], 415)]
        for headers, status in cases:
            with self.subTest(headers=headers), self.assertRaises(ApiError) as caught:
                await self.parse([], [(b"content-type", b"application/json"), *headers])
            self.assertEqual(caught.exception.status, status)

    async def test_slow_login_body_has_a_deadline(self):
        timeout = asyncio.timeout
        with patch("app.auth.routes.asyncio.timeout", side_effect=lambda seconds: timeout(0.01)):
            with self.assertRaises(ApiError) as caught:
                await self.parse([b"{}"], delay=1)
        self.assertEqual(caught.exception.status, 408)


class HardeningConfigurationTests(unittest.TestCase):
    def test_production_rejects_local_origins_and_ambiguous_origins(self):
        for origin in ("https://localhost", "https://app.localhost", "https://127.0.0.1", "https://[::1]", "https://0.0.0.0"):
            with self.subTest(origin=origin), self.assertRaises(ValidationError):
                Settings(_env_file=None, app_env="production", cors_allowed_origins=[origin])
        for origin in ("https://example.com:", "https://exam%70le.com", "https://example.com\\evil", "https://example..com", "https://example.com\x00"):
            with self.subTest(origin=origin), self.assertRaises(ValidationError):
                Settings(_env_file=None, cors_allowed_origins=[origin])

    def test_throttling_is_mandatory_and_configuration_is_bounded(self):
        for options in ({"login_client_attempts": 0}, {"login_global_attempts": 1001},
                        {"login_window_seconds": 0}, {"login_window_seconds": 3601}, {"login_max_clients": 0}):
            with self.subTest(options=options), self.assertRaises(ValidationError):
                AuthSettings(_env_file=None, **options)

    def test_launcher_disables_raw_access_logs_and_requires_explicit_proxy_trust(self):
        for peers in ([], ["127.0.0.1", "10.20.0.0/16"]):
            settings = Settings(_env_file=None, trusted_proxy_ips=peers)
            with patch("app.config.get_settings", return_value=settings), patch("uvicorn.run") as run:
                runpy.run_path(str(BACKEND_DIRECTORY / "run.py"), run_name="__main__")
            self.assertIs(run.call_args.kwargs["access_log"], False)
            self.assertEqual(run.call_args.kwargs["proxy_headers"], bool(peers))
            self.assertEqual(run.call_args.kwargs["forwarded_allow_ips"], ",".join(peers))
        for peer in ("*", "0.0.0.0/0", "::/0", "proxy.example.com"):
            with self.subTest(peer=peer), self.assertRaises(ValidationError):
                Settings(_env_file=None, trusted_proxy_ips=[peer])


if __name__ == "__main__":
    unittest.main()
