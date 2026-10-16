"""Production launch, private config and reviewed Render service boundaries."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.production import blueprint_contract, main, production_settings, ROOT


class ProductionTests(unittest.TestCase):
    def environment(self):
        return {"APP_ENV":"production", "CORS_ALLOWED_ORIGINS":'["https://economic-web.onrender.com"]',
                "AUTH_JWT_SIGNING_KEY":"b" * 64, "PORT":"10000", "DATABASE_DIRECTORY":"/var/data/economic-dash",
                "COLLECTOR_SCHEDULER_STATE_DIRECTORY":"/var/data/economic-dash", "COLLECTOR_SCHEDULER_ENABLED":"true"}

    def test_injected_environment_validates_without_touching_database_or_echoing_secret(self):
        with patch.dict(os.environ,self.environment(),clear=True), patch("app.sqlite_runtime.sqlite3.connect") as connect:
            settings,auth,database,scheduler,port=production_settings()
        connect.assert_not_called()
        self.assertEqual(settings.app_env,"production")
        self.assertEqual(auth.access_token_minutes,15)
        self.assertEqual(database.directory,Path("/var/data/economic-dash").resolve())
        self.assertEqual(scheduler.state_directory,database.directory)
        self.assertEqual(port,10000)

    def test_runtime_starts_one_worker_with_access_and_proxy_logging_disabled(self):
        factory = Mock()
        with patch.dict(os.environ,self.environment(),clear=True), patch("sys.argv",["production"]), \
                patch.dict("sys.modules", {"app.main": SimpleNamespace(create_app=factory)}), \
                patch("app.production.Path.exists",return_value=False), patch("uvicorn.run") as run:
            self.assertEqual(main(),0)
        factory.assert_called_once()
        self.assertEqual(factory.call_args.kwargs["database_settings"].app_env,"production")
        run.assert_called_once_with(factory.return_value, host="0.0.0.0", port=10000,
                                    workers=1, reload=False, access_log=False, proxy_headers=False)

    def test_unsafe_or_incomplete_environment_is_rejected(self):
        for changes in ({"APP_ENV":"development"},{"AUTH_JWT_SIGNING_KEY":""},{"AUTH_JWT_SIGNING_KEY":"base64-format"},
                        {"CORS_ALLOWED_ORIGINS":'["http://localhost:5173"]'},
                        {"CORS_ALLOWED_ORIGINS":'["https://frontend.example.invalid"]'},
                        {"CORS_ALLOWED_ORIGINS":'["https://one.onrender.com","https://two.onrender.com"]'},
                        {"COLLECTOR_SCHEDULER_ENABLED":"false"},{"COLLECTOR_SCHEDULER_STATE_DIRECTORY":"/tmp/locks"},
                        {"DATABASE_DIRECTORY":"/tmp/database"},{"TRUSTED_PROXY_IPS":'["127.0.0.1"]'},
                        {"PORT":"0"},{"PORT":"65536"},{"PORT":""},{"COLLECTOR_TOTAL_TIMEOUT":"0"}):
            with self.subTest(keys=tuple(changes)),patch.dict(os.environ,{**self.environment(),**changes},clear=True):
                with self.assertRaises(ValueError): production_settings()

    def test_configuration_only_cli_reports_no_mount_acceptance_and_redacts_failures(self):
        output,errors=io.StringIO(),io.StringIO()
        with patch.dict(os.environ,self.environment(),clear=True),patch("sys.argv",["production","--check"]),redirect_stdout(output):
            self.assertEqual(main(),0)
        self.assertFalse(json.loads(output.getvalue())["mount_verified"])
        env={**self.environment(),"AUTH_JWT_SIGNING_KEY":"private-canary"}
        with patch.dict(os.environ,env,clear=True),patch("sys.argv",["production","--check"]),redirect_stderr(errors):
            self.assertEqual(main(),1)
        self.assertNotIn("private-canary",errors.getvalue())

    def test_reviewed_blueprint_and_secret_prompts_pass(self):
        self.assertEqual(blueprint_contract()["services"],2)

    def test_startup_diagnostics_identify_settings_without_echoing_input_or_tracebacks(self):
        cases = (
            ({"AUTH_JWT_SIGNING_KEY":"private-canary"}, "AUTH_JWT_SIGNING_KEY"),
            ({"CORS_ALLOWED_ORIGINS":"private-canary"}, "CORS_ALLOWED_ORIGINS"),
            ({"CORS_ALLOWED_ORIGINS":'["https://private-canary.onrender.com/"]'}, "CORS_ALLOWED_ORIGINS"),
            ({"DATABASE_DIRECTORY":"/tmp/private-canary"}, "DatabaseSettings"),
            ({"PORT":"private-canary"}, "PORT"),
        )
        for changes,expected in cases:
            errors=io.StringIO()
            with self.subTest(expected=expected),patch.dict(os.environ,{**self.environment(),**changes},clear=True), \
                    patch("sys.argv",["production","--check"]),redirect_stderr(errors):
                self.assertEqual(main(),1)
            self.assertIn(expected,errors.getvalue())
            self.assertNotIn("private-canary",errors.getvalue())
            self.assertNotIn("Traceback",errors.getvalue())

    def test_runtime_pin_diagnostic_is_specific_and_keeps_validation_enabled(self):
        errors=io.StringIO()
        with patch.dict(os.environ,self.environment(),clear=True),patch("sys.argv",["production","--check"]), \
                patch("app.production.sys.version_info",(3,13,8)),redirect_stderr(errors):
            self.assertEqual(main(),1)
        self.assertIn("Python runtime does not match the repository pin",errors.getvalue())

    def test_blueprint_rejects_public_db_multiworker_and_baked_secret_regressions(self):
        spec=json.loads((ROOT / "render.yaml").read_text())
        for mutate in (
            lambda value:value["services"][0].update(numInstances=2),
            lambda value:value["services"][0].update(preDeployCommand="python -m app.database"),
            lambda value:value["services"][0]["disk"].update(mountPath="/tmp"),
            lambda value:value["services"][0].update(autoDeployTrigger="commit"),
            lambda value:value["services"][1].update(staticPublishPath="../backend"),
            lambda value:value["services"][0]["envVars"][3].update(value="private-canary"),
            lambda value:value["services"][0]["envVars"][3].update(generateValue=True),
            lambda value:value["services"][1]["envVars"].append({"key":"AUTH_JWT_SIGNING_KEY","sync":False}),
            lambda value:value.update(databases=[{"name":"unreviewed-public-db"}]),
        ):
            changed=deepcopy(spec);mutate(changed)
            with self.assertRaises(ValueError):blueprint_contract(changed)


if __name__ == "__main__":
    unittest.main()
