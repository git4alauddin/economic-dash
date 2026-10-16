"""Real signed-token auth tests in temporary storage; no auth dependency overrides."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from secrets import token_hex
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import jwt
from pydantic import ValidationError

from app.auth.passwords import PasswordWorkBusy
from app.auth.settings import AuthSettings
from app.auth.tokens import REQUIRED
from app.config import DatabaseSettings, SchedulerSettings, Settings
from app.main import create_app

PASSWORD = "synthetic auth test passphrase 42"


class AuthTokenTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.settings = AuthSettings(_env_file=None, app_env="test", jwt_signing_key=token_hex(32))
        self.key = bytes.fromhex(self.settings.jwt_signing_key.get_secret_value())
        self.app = create_app(Settings(_env_file=None, app_env="test"), auth_settings=self.settings,
            database_settings=DatabaseSettings(_env_file=None, app_env="test", directory=Path(temporary.name) / "db"),
            scheduler_settings=SchedulerSettings(_env_file=None, enabled=False))
        self.client = self.enterContext(TestClient(self.app))
        self.service = self.app.state.auth_service
        self.user = self.service.users.provision("evaluator", PASSWORD).identity

    def login(self):
        response = self.client.post("/api/v1/auth/login", json={"username": " EVALUATOR ", "password": PASSWORD})
        self.assertEqual(response.status_code, 200, response.text)
        return response

    def signed(self, changes=None, *, remove=None, headers=None, key=None, algorithm="HS256"):
        claims = jwt.decode(self.login().json()["access_token"], self.key,
                            algorithms=["HS256"], audience=self.settings.jwt_audience, issuer=self.settings.jwt_issuer)
        claims.update(changes or {})
        if remove:
            claims.pop(remove)
        return jwt.encode(claims, key if key is not None else self.key, algorithm=algorithm,
                          headers=headers if headers is not None else {"typ": "at+jwt"})

    def me(self, token):
        return self.client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + token})

    def test_login_and_me_issue_real_short_lived_token_with_minimal_identity(self):
        response = self.login()
        data = response.json()
        self.assertEqual(data["expires_in"], 900)
        self.assertEqual(data["token_type"], "bearer")
        self.assertNotIn(PASSWORD, response.text)
        self.assertNotIn("password_hash", response.text)
        claims = jwt.decode(data["access_token"], self.key, algorithms=["HS256"],
                            audience=self.settings.jwt_audience, issuer=self.settings.jwt_issuer)
        self.assertEqual(set(claims), set(REQUIRED))
        self.assertEqual(claims["exp"] - claims["iat"], 900)
        self.assertEqual(claims["nbf"], claims["iat"])
        self.assertEqual((claims["sub"], claims["ver"], claims["token_use"]), (self.user.user_id, 1, "access"))
        self.assertEqual(datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00")).timestamp(), claims["exp"])
        identity = self.me(data["access_token"])
        self.assertEqual(identity.status_code, 200)
        self.assertEqual(identity.json(), {"user_id": self.user.user_id, "username": "evaluator"})
        self.assertFalse(self.app.dependency_overrides)
        self.assertNotEqual(self.login().json()["access_token"], data["access_token"])
        for result in (response, identity):
            self.assertEqual(result.headers["cache-control"], "no-store")
            self.assertNotIn("set-cookie", result.headers)
        # M5.4 owns replacing the existing data-route placeholder guard.
        self.assertEqual(self.client.get("/api/v1/dashboard", headers={"Authorization": "Bearer " + data["access_token"]}).status_code, 503)

    def test_unknown_wrong_and_inactive_credentials_have_identical_generic_failure(self):
        failures = []
        for username, password in (("evaluator", "wrong"), ("unknown", PASSWORD), ("invalid name", PASSWORD)):
            result = self.client.post("/api/v1/auth/login", json={"username": username, "password": password})
            self.assertEqual(result.status_code, 401)
            self.assertEqual(result.headers["www-authenticate"], "Bearer")
            self.assertNotIn(password, result.text)
            failures.append(result.json())
        self.service.users.set_active("evaluator", False)
        result = self.client.post("/api/v1/auth/login", json={"username": "evaluator", "password": PASSWORD})
        self.assertEqual(result.status_code, 401)
        self.assertTrue(all(f == result.json() for f in failures))

    def test_missing_malformed_tampered_wrong_key_and_wrong_algorithm_are_401(self):
        self.assertEqual(self.client.get("/api/v1/auth/me").status_code, 401)
        valid = self.login().json()["access_token"]
        tokens = ["malformed.fixture.token", "a.b.c", valid + "x", "x" * 4097,
                  self.signed(key=bytes.fromhex(token_hex(32))), self.signed(algorithm="HS512", key=bytes.fromhex(token_hex(64))),
                  self.signed(key="", algorithm="none"), self.signed(headers={"typ": "JWT"}),
                  self.signed(headers={"typ": "at+jwt", "kid": "untrusted"}), " " + valid]
        for token in tokens:
            with self.subTest(kind=token[:6]):
                result = self.me(token)
                self.assertEqual(result.status_code, 401)
                self.assertNotIn(token, result.text)
                self.assertEqual(result.headers["www-authenticate"], "Bearer")

    def test_claim_presence_types_scope_and_lifetime_are_enforced(self):
        now = int(datetime.now(timezone.utc).timestamp())
        changes = [{"iss": "other-api"}, {"aud": "other-client"}, {"aud": [self.settings.jwt_audience]},
            {"sub": "missing-subject"}, {"jti": "bad-id"}, {"ver": 0}, {"ver": True}, {"token_use": "refresh"},
            {"exp": str(now + 60)}, {"iat": float(now)}, {"nbf": True},
            {"iat": now, "nbf": now, "exp": now + 1801},
            {"iat": now + 60, "nbf": now + 60, "exp": now + 900},
            {"iat": now, "nbf": now + 1, "exp": now + 900}, {"extra": "claim"}]
        for change in changes:
            with self.subTest(claim=list(change)):
                self.assertEqual(self.me(self.signed(change)).status_code, 401)
        for claim in REQUIRED:
            with self.subTest(missing=claim):
                self.assertEqual(self.me(self.signed(remove=claim)).status_code, 401)

    def test_expiry_and_not_before_use_bounded_clock_tolerance(self):
        now = int(datetime.now(timezone.utc).timestamp())
        self.assertEqual(self.me(self.signed({"iat": now - 900, "nbf": now - 900, "exp": now - 6})).status_code, 401)
        self.assertEqual(self.me(self.signed({"iat": now - 900, "nbf": now - 900, "exp": now - 2})).status_code, 200)
        self.assertEqual(self.me(self.signed({"iat": now + 2, "nbf": now + 2, "exp": now + 900})).status_code, 200)
        self.assertEqual(self.me(self.signed({"iat": now + 8, "nbf": now + 8, "exp": now + 900})).status_code, 401)

    def test_password_reset_disable_and_reenable_invalidate_prior_tokens(self):
        token = self.login().json()["access_token"]
        self.service.users.provision("evaluator", "replacement synthetic passphrase 73", reset_password=True)
        self.assertEqual(self.me(token).status_code, 401)
        token = self.service.issue(self.service.users.authenticate("evaluator", "replacement synthetic passphrase 73")).token
        self.service.users.set_active("evaluator", False)
        self.assertEqual(self.me(token).status_code, 401)
        self.service.users.set_active("evaluator", True)
        self.assertEqual(self.me(token).status_code, 401)
        with self.app.state.database.transaction() as connection:
            connection.execute("DELETE FROM auth_users WHERE user_id=?", (self.user.user_id,))
        self.assertEqual(self.me(token).status_code, 401)

    def test_key_rotation_rejects_old_tokens(self):
        token = self.login().json()["access_token"]
        from app.auth.tokens import AuthService
        rotated = AuthService(AuthSettings(_env_file=None, jwt_signing_key=token_hex(32)), self.service.users)
        with patch.object(self.app.state, "auth_service", rotated):
            self.assertEqual(self.me(token).status_code, 401)

    def test_request_types_duplicates_oversize_and_form_credentials_do_not_reach_hashing(self):
        with patch.object(self.service.users, "authenticate", side_effect=AssertionError("Invalid request reached hashing")):
            cases = [("{}", "application/json", 422), ("[]", "application/json", 422),
                ('{"username":1,"password":"secret-fixture"}', "application/json", 422),
                ('{"username":"evaluator","username":"other","password":"secret-fixture"}', "application/json", 422),
                ('{"username":"evaluator","password":"secret-fixture","unexpected":true}', "application/json", 422),
                ("bad json", "application/json", 422), ("x" * 4097, "application/json", 413),
                ("username=evaluator&password=secret-fixture", "application/x-www-form-urlencoded", 415)]
            for body, content_type, status in cases:
                result = self.client.post("/api/v1/auth/login", content=body, headers={"Content-Type": content_type})
                self.assertEqual(result.status_code, status)
                self.assertNotIn("secret-fixture", result.text)
            result = self.client.post("/api/v1/auth/login?password=secret-fixture", json={"username": "evaluator", "password": PASSWORD})
            self.assertEqual(result.status_code, 422)
            result = self.client.post("/api/v1/auth/login", content=iter([b"x" * 2048, b"y" * 2049]), headers={"Content-Type": "application/json"})
            self.assertEqual(result.status_code, 413)

    def test_query_or_cookie_tokens_cannot_authenticate_and_duplicate_headers_are_rejected(self):
        token = self.login().json()["access_token"]
        self.assertEqual(self.client.get("/api/v1/auth/me", params={"access_token": token}).status_code, 401)
        self.assertEqual(self.client.get("/api/v1/auth/me", headers={"Cookie": "access_token=" + token}).status_code, 401)
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=[("Authorization", "Bearer " + token), ("Authorization", "Bearer " + token)]).status_code, 401)

    def test_storage_or_hash_capacity_errors_are_safe_503(self):
        for error in (sqlite3.OperationalError("private-path " + PASSWORD), PasswordWorkBusy("busy " + PASSWORD)):
            with patch.object(self.service.users, "authenticate", side_effect=error):
                result = self.client.post("/api/v1/auth/login", json={"username": "evaluator", "password": PASSWORD})
                self.assertEqual(result.status_code, 503)
                self.assertNotIn(PASSWORD, result.text)
                self.assertEqual(result.headers["retry-after"], "1")
        token = self.login().json()["access_token"]
        with patch.object(self.service.users, "get", side_effect=sqlite3.OperationalError("private secret")):
            result = self.me(token)
        self.assertEqual(result.status_code, 503)
        self.assertNotIn("private secret", result.text)

    def test_unconfigured_auth_has_no_fallback_key_and_missing_credentials_still_401(self):
        with patch.object(self.app.state, "auth_service", None):
            self.assertEqual(self.client.post("/api/v1/auth/login", json={"username": "evaluator", "password": PASSWORD}).status_code, 503)
            self.assertEqual(self.client.get("/api/v1/auth/me").status_code, 401)
            self.assertEqual(self.me("unverified").status_code, 503)

    def test_cors_supports_json_post_only_for_configured_frontend(self):
        for origin, allowed in (("http://localhost:5173", True), ("https://unapproved.example", False)):
            response = self.client.options("/api/v1/auth/login", headers={"Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"})
            self.assertEqual(response.status_code, 200 if allowed else 400)
            self.assertEqual(response.headers.get("access-control-allow-origin"), origin if allowed else None)
            self.assertNotIn("access-control-allow-credentials", response.headers)
        self.assertEqual(self.client.post("/api/v1/auth/login", headers={"Origin": "https://unapproved.example"}, json={"username": "evaluator", "password": "wrong"}).status_code, 401)

    def test_openapi_declares_public_login_and_guarded_me_without_secret_examples(self):
        schema = self.client.get("/openapi.json").json()
        login = schema["paths"]["/api/v1/auth/login"]["post"]
        self.assertNotIn("security", login)
        self.assertEqual(login["requestBody"]["content"]["application/json"]["schema"]["required"], ["username", "password"])
        self.assertEqual(schema["paths"]["/api/v1/auth/me"]["get"]["security"], [{"DashboardBearer": []}])
        self.assertNotIn(PASSWORD, str(schema))
        self.assertNotIn(self.settings.jwt_signing_key.get_secret_value(), str(schema))


class AuthSettingsTests(unittest.TestCase):
    def test_secret_is_required_in_production_and_never_in_repr_or_dump(self):
        key = token_hex(32)
        config = AuthSettings(_env_file=None, app_env="production", jwt_signing_key=key)
        self.assertNotIn(key, repr(config))
        self.assertNotIn(key, str(config.model_dump()))
        with self.assertRaises(ValidationError):
            AuthSettings(_env_file=None, app_env="production", jwt_signing_key=None)
        for bad in ("short-fixture-secret", "x" * 64):
            with self.assertRaises(ValidationError) as error:
                AuthSettings(_env_file=None, jwt_signing_key=bad)
            self.assertNotIn(bad, str(error.exception))

    def test_expiry_skew_and_identifiers_have_bounded_configuration(self):
        for options in ({"access_token_minutes": 4}, {"access_token_minutes": 31},
                        {"clock_skew_seconds": -1}, {"clock_skew_seconds": 31},
                        {"jwt_issuer": "bad issuer"}, {"jwt_audience": ""}):
            with self.subTest(options=options), self.assertRaises(ValidationError):
                AuthSettings(_env_file=None, **options)


if __name__ == "__main__":
    unittest.main()
