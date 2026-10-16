"""Keep local verification distinct from submission/release approval."""

import json
import os
import subprocess
import unittest
from unittest.mock import patch

from app.verify_release import LOCAL_CHECKS, acceptance, checked_revision, handoff, run_check


class ReleaseHandoffTests(unittest.TestCase):
    def checks(self):
        return [{"name": name, "status": "PASS"} for name in (*LOCAL_CHECKS, "real_browser")]

    def test_passing_local_and_browser_checks_do_not_clear_source_or_hosted_gates(self):
        requirements = {"world": {"status": "selected"}, "debt": {"status": "blocked", "reason_code": "definition_unverified"}}
        result = acceptance(self.checks(), requirements)
        self.assertEqual(result["local_checks"], "PASS")
        self.assertEqual(result["integrated_browser"], "PASS")
        self.assertEqual(result["source_coverage"], "BLOCKED")
        self.assertEqual(result["source_blockers"][0]["id"], "debt")
        self.assertFalse(result["submission_ready"])
        self.assertEqual(result["hosted_tls_cors_storage_scheduler"]["status"], "UNVERIFIED")
        self.assertFalse(acceptance(self.checks(), {"world": {"status": "selected"}})["submission_ready"])

    def test_failure_or_omission_cannot_be_reported_as_pass(self):
        for name in (*LOCAL_CHECKS, "real_browser"):
            checks = self.checks()
            next(item for item in checks if item["name"] == name)["status"] = "FAIL"
            self.assertEqual(acceptance(checks, {})["local_checks"], "FAIL")
        self.assertEqual(acceptance([], {})["local_checks"], "UNVERIFIED")
        offline = acceptance(self.checks()[:-1], {})
        self.assertEqual(offline["integrated_browser"], "UNVERIFIED")
        self.assertFalse(offline["submission_ready"])
        self.assertEqual(acceptance(self.checks(), {"x": {"status": "invented"}})["local_checks"], "FAIL")

    def test_dirty_or_changed_git_revision_cannot_be_a_frozen_candidate(self):
        clean = {"head": "a" * 40, "working_tree_clean": True, "deployment_candidate": "a" * 40}
        self.assertEqual(checked_revision(clean, clean, checks_passed=True)["deployment_candidate"], clean["head"])
        self.assertIsNone(checked_revision(clean, clean, checks_passed=False)["deployment_candidate"])
        dirty = {**clean, "working_tree_clean": False, "deployment_candidate": None}
        changed = {**clean, "head": "b" * 40, "deployment_candidate": "b" * 40}
        for before, after in ((dirty, clean), (clean, dirty), (clean, changed)):
            self.assertIsNone(checked_revision(before, after, checks_passed=True)["deployment_candidate"])

    def test_browser_zero_exit_with_incomplete_result_is_rejected_without_echoing_output(self):
        result = subprocess.CompletedProcess([], 0, stdout='{"result":"PASS","private":"do-not-echo"}', stderr="")
        with patch("app.verify_release.subprocess.run", return_value=result):
            check = run_check("real_browser", ["unused"], ".")
        self.assertEqual(check["status"], "FAIL")
        self.assertNotIn("do-not-echo", json.dumps(check))

    def test_handoff_lists_contracts_and_names_without_exposing_configured_secret(self):
        secret = "b" * 64
        with patch.dict(os.environ, {"AUTH_JWT_SIGNING_KEY": secret}):
            result = handoff()
        self.assertNotIn(secret, json.dumps(result))
        self.assertIn("AUTH_JWT_SIGNING_KEY", result["environment_names_only"]["auth"])
        self.assertEqual(result["health"]["responses"]["503"], {"status": "unavailable"})
        self.assertEqual(len(result["selected_sources"]), 5)
        routes = {(item["method"], item["path"]): item["access"] for item in result["endpoints"]}
        self.assertEqual(routes[("GET", "/health")], "public")
        self.assertEqual(routes[("POST", "/api/v1/auth/login")], "public")
        self.assertEqual(routes[("GET", "/api/v1/dashboard")], "bearer")


if __name__ == "__main__":
    unittest.main()
