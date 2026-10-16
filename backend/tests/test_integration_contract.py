"""Exercise the repeatable M4 acceptance check with deterministic source fixtures."""

from copy import deepcopy
from datetime import timedelta
import unittest
from unittest.mock import patch

from app.collectors.catalog import SourceRegistry
from app.verify_integration import check_api, validate_dashboard
import test_api
from test_normalization import NOW


class IntegrationContractTests(unittest.TestCase):
    setUp = test_api.ApiTests.setUp
    populate = test_api.ApiTests.populate

    def test_reopened_sql_routes_outage_and_frontend_transcript_cover_all_requirements(self):
        self.populate()
        with patch("app.verify_integration.datetime") as clock:
            clock.now.return_value = NOW + timedelta(hours=2)
            self.clock.now.return_value = clock.now.return_value
            result, transcript = check_api(self.application.state.database.settings, SourceRegistry.load().source_ids)
        self.assertEqual((result["panels"], result["series"], result["summary_slots"], result["requirements"]), (6, 13, 12, 17))
        self.assertEqual((result["supported_series"], result["blocked_requirements"], result["read_routes_checked"]), (9, 8, 22))
        self.assertTrue(result["restart_reload"] and result["failure_retention"])
        self.assertEqual([r["status"] for r in transcript["polling"]], [200, 304, 200, 401])

    def test_acceptance_rejects_tampered_values_attribution_and_missing_requirements(self):
        self.populate()
        original = self.client.get("/api/v1/dashboard").json()
        service = self.application.state.dashboard_queries
        validate_dashboard(original, service, required_sources=SourceRegistry.load().source_ids)
        for change in ("value", "source", "panel", "blocker", "summary"):
            body = deepcopy(original)
            if change == "value":
                body["data"]["panels"]["gdp_growth"]["series"]["gdp_growth_world"]["latest"]["value"] = "999"
            elif change == "source":
                body["data"]["panels"]["gdp_growth"]["series"]["gdp_growth_world"]["latest"]["sources"][0]["name"] = "Wrong attribution"
            elif change == "panel":
                del body["data"]["panels"]["trade"]
            elif change == "blocker":
                body["data"]["panels"]["gst_collection"]["series"]["gst_total"]["latest"]["reason_code"] = "wrong_blocker"
            else:
                body["data"]["panels"]["trade"]["summaries"][0]["requirement_id"] = "imports"
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_dashboard(body, service)


if __name__ == "__main__":
    unittest.main()
