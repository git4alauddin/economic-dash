"""Serialization schema stays authoritative for the checked-in browser types."""

import unittest

from app.generate_public_contract import ROOTS, TARGET, render


class PublicContractTests(unittest.TestCase):
    def test_generated_browser_types_match_current_backend_serialization(self):
        self.assertEqual(TARGET.read_text(encoding="utf-8"), render(), "Run python -m app.generate_public_contract and review changes.")

    def test_money_period_and_summary_contract_retains_required_semantics(self):
        schema = ROOTS["DashboardResponseV1"].model_json_schema(mode="serialization")
        definitions = schema["$defs"]
        normalized_value = definitions["NormalizedObservation"]["properties"]["value"]
        self.assertEqual({entry["type"] for entry in normalized_value["anyOf"]}, {"string", "null"})
        self.assertTrue({"frequency", "basis", "start", "end"} <= set(definitions["ResponsePeriod"]["required"]))
        self.assertTrue({"summaries", "indicator_id"} <= set(definitions["ResponsePanel"]["required"]))
        self.assertTrue({"reference_series_id", "reference_period_id", "exact_numerator", "exact_denominator", "transform_id"}
                        <= set(definitions["ResponseComparison"]["required"]))


if __name__ == "__main__":
    unittest.main()
