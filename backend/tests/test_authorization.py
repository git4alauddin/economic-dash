"""Every dashboard read and validator must pass the real JWT/account guard."""

from datetime import datetime, timedelta, timezone
from secrets import token_hex
import sqlite3
import unittest
from unittest.mock import patch

import test_api
import test_auth_tokens
from test_normalization import NOW


class AuthorizationTests(unittest.TestCase):
    login = test_auth_tokens.AuthTokenTests.login
    signed = test_auth_tokens.AuthTokenTests.signed

    def setUp(self):
        test_auth_tokens.AuthTokenTests.setUp(self)
        self.repository = self.app.state.collection_repository
        test_api.ApiTests.populate(self)
        self.clock = self.enterContext(patch("app.api.datetime"))
        self.clock.now.return_value = NOW + timedelta(hours=1)
        self.paths = ["/api/v1/dashboard", "/api/v1/indicators", "/api/v1/ticker"]
        for pid, panel in self.app.state.dashboard_queries.panels.items():
            self.paths.append(f"/api/v1/indicators/{pid}")
            self.paths.extend(f"/api/v1/indicators/{pid}/history?series_id={s['id']}" for s in panel["series"])

    def denied_everywhere(self, token):
        for path in self.paths + ["/api/v1/auth/me"]:
            response = self.client.get(path, headers={"Authorization": "Bearer " + token, "If-None-Match": "*"})
            self.assertEqual(response.status_code, 401, path)
            self.assertEqual(response.headers["www-authenticate"], "Bearer")
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertNotIn("etag", response.headers)
            self.assertEqual(set(response.json()), {"error"})

    def test_valid_login_reads_all_panels_period_controls_and_bodyless_conditional_responses(self):
        token = self.login().json()["access_token"]
        self.assertEqual(len(self.paths), 22)
        before = self.repository.load()
        for path in self.paths:
            first = self.client.get(path, headers={"Authorization": "Bearer " + token})
            self.assertEqual(first.status_code, 200, path)
            self.assertEqual(first.headers["cache-control"], "no-store")
            self.assertEqual(first.headers["x-poll-interval"], "60")
            unchanged = self.client.get(path, headers={"Authorization": "Bearer " + token, "If-None-Match": first.headers["etag"]})
            self.assertEqual(unchanged.status_code, 304, path)
            self.assertEqual(unchanged.content, b"")
        selected = self.client.get("/api/v1/indicators/gdp_growth?period=gdp_growth_world:CY2024",
                                   headers={"Authorization": "Bearer " + token})
        self.assertEqual(selected.status_code, 200)
        self.assertEqual(selected.json()["data"]["series"]["gdp_growth_world"]["latest"]["as_of"], "2024")
        self.assertEqual(self.repository.load(), before)
        self.assertFalse(self.app.dependency_overrides)

    def test_all_invalid_token_kinds_fail_before_dashboard_queries_even_with_validators(self):
        now = int(datetime.now(timezone.utc).timestamp())
        valid = self.login().json()["access_token"]
        cases = ["malformed.fixture.token", valid + "x",
            self.signed({"iat": now - 1800, "nbf": now - 1800, "exp": now - 900}),
            self.signed({"iss": "wrong-api"}), self.signed({"aud": "wrong-client"}),
            self.signed({"sub": token_hex(16)}), self.signed({"token_use": "refresh"}),
            self.signed(algorithm="HS512", key=bytes.fromhex(token_hex(64))),
            self.signed(key=bytes.fromhex(token_hex(32)))]
        queries = self.app.state.dashboard_queries
        with patch.object(queries, "dashboard", side_effect=AssertionError("Unauthorized dashboard read")), \
                patch.object(queries, "indicator", side_effect=AssertionError("Unauthorized panel read")), \
                patch.object(queries, "series", side_effect=AssertionError("Unauthorized history read")), \
                patch.object(queries, "ticker_version", side_effect=AssertionError("Unauthorized ticker read")):
            for token in cases:
                self.denied_everywhere(token)
            for path in self.paths:
                self.assertEqual(self.client.get(path, headers={"If-None-Match": "*"}).status_code, 401)

    def test_disable_and_reenable_cannot_resurrect_previously_authorized_etag_or_token(self):
        token = self.login().json()["access_token"]
        first = self.client.get("/api/v1/dashboard", headers={"Authorization": "Bearer " + token})
        self.service.users.set_active("evaluator", False)
        self.denied_everywhere(token)
        self.assertEqual(self.client.get("/api/v1/dashboard", headers={"Authorization": "Bearer " + token,
            "If-None-Match": first.headers["etag"]}).status_code, 401)
        self.service.users.set_active("evaluator", True)
        self.denied_everywhere(token)
        replacement = self.login().json()["access_token"]
        self.assertEqual(self.client.get("/api/v1/dashboard", headers={"Authorization": "Bearer " + replacement,
            "If-None-Match": first.headers["etag"]}).status_code, 304)

    def test_password_reset_and_deleted_identity_reject_all_data_routes(self):
        old = self.login().json()["access_token"]
        password = "replacement authorization fixture password"
        self.service.users.provision("evaluator", password, reset_password=True)
        self.denied_everywhere(old)
        login = self.client.post("/api/v1/auth/login", json={"username": "evaluator", "password": password})
        self.assertEqual(login.status_code, 200)
        token = login.json()["access_token"]
        with self.app.state.database.transaction() as connection:
            connection.execute("DELETE FROM auth_users WHERE user_id=?", (self.user.user_id,))
        self.denied_everywhere(token)

    def test_cors_and_cookies_never_replace_authorization(self):
        token = self.login().json()["access_token"]
        for path in self.paths:
            for headers in ({"Origin": "http://localhost:5173"}, {"Origin": "https://unapproved.example"},
                            {"Cookie": "access_token=" + token}):
                self.assertEqual(self.client.get(path, headers=headers).status_code, 401)
            invalid_query_token = path + ("&" if "?" in path else "?") + "access_token=" + token
            self.assertEqual(self.client.get(invalid_query_token).status_code, 401)
        response = self.client.get("/api/v1/dashboard", headers={"Authorization": "Bearer " + token,
                                                               "Origin": "https://unapproved.example"})
        self.assertEqual(response.status_code, 200)  # Raw authenticated HTTP remains valid.
        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_auth_storage_and_configuration_failures_cannot_return_conditional_success(self):
        token = self.login().json()["access_token"]
        headers = {"Authorization": "Bearer " + token, "If-None-Match": "*"}
        with patch.object(self.service.users, "get", side_effect=sqlite3.OperationalError("private account storage")):
            for path in self.paths:
                response = self.client.get(path, headers=headers)
                self.assertEqual(response.status_code, 503)
                self.assertNotIn("etag", response.headers)
                self.assertNotIn("private account storage", response.text)
        with patch.object(self.app.state, "auth_service", None):
            for path in self.paths:
                self.assertEqual(self.client.get(path, headers=headers).status_code, 503)
                self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_route_inventory_has_no_unclassified_public_data_route_or_external_write_surface(self):
        public = {("/", "get"), ("/health", "get"), ("/api/v1/auth/login", "post")}
        protected = {"/api/v1/dashboard", "/api/v1/indicators", "/api/v1/indicators/{indicator_id}",
                     "/api/v1/indicators/{indicator_id}/history", "/api/v1/ticker", "/api/v1/auth/me"}
        seen = set()
        for path, operations in self.app.openapi()["paths"].items():
            for method, operation in operations.items():
                if method not in {"get", "post", "put", "patch", "delete", "head", "options", "trace"}:
                    continue
                if (path, method) in public:
                    self.assertFalse(operation.get("security"))
                else:
                    self.assertIn(path, protected)
                    self.assertEqual(method, "get")
                    self.assertEqual(operation["security"], [{"DashboardBearer": []}])
                    seen.add(path)
        self.assertEqual(seen, protected)
        for path in ("/api/v1/internal/ingest", "/api/v1/updates", "/dashboard.sqlite3"):
            self.assertEqual(self.client.get(path).status_code, 404)
            self.assertEqual(self.client.post(path, json={}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
