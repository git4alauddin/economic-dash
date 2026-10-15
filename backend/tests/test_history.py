"""Reproducible history/calculation cases using synthetic observations only."""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal, localcontext
from fractions import Fraction
from types import MappingProxyType
import unittest

import httpx2 as httpx
from pydantic import ValidationError

from app.collectors.adapters import create_adapters
from app.collectors.catalog import SourceRegistry
from app.collectors.history import ExactValue, build_history, collect_history, compare, trade_balance
from app.collectors.http_client import CollectorHttpClient
from app.collectors.normalization import SourceNormalizer
from app.collectors.observations import NormalizedBatch, NormalizedObservation, ParseError, annual_period, monthly_period
from app.config import CollectorSettings
from test_normalization import NOW, changed, cpi, expenditure, gdp, trade, wb


def record(point, **changes):
    values = {name: getattr(point, name) for name in type(point).model_fields}
    if "observation_period" in changes:
        period = changes["observation_period"]
        changes["as_of"] = period.end.strftime("%Y" if period.frequency == "annual" else "%Y-%m")
    return NormalizedObservation(**(values | changes))


def batch(points):
    return NormalizedBatch(source_id=points[0].sources[0].source_id, observations=tuple(points), coverage="release_only")


def series(snapshot, sid):
    return next(s for s in snapshot.series if s.series_id == sid)


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.normalizer = SourceNormalizer()

    def test_trade_balance_exact_sign_and_complete_provenance(self):
        source = self.normalizer.parse(trade())
        result = series(build_history((source,)), "trade_balance")
        self.assertEqual([p.value for p in result.observations], [Decimal("-4.75"), Decimal("-4.70")])
        latest = result.latest
        self.assertEqual(latest.transform_id, "exports_minus_imports_v1")
        self.assertEqual(tuple(p.series_id for p in latest.inputs), ("exports", "imports"))
        self.assertTrue(all(p.vintage_id == latest.vintage_id for p in latest.inputs))
        self.assertEqual(latest.sources, latest.inputs[0].sources)
        wire = latest.model_dump(mode="json")
        self.assertEqual(wire["value"], "-4.70")
        self.assertEqual(wire["inputs"][1]["value"], "17.20")

    def test_derived_model_rejects_wrong_sign_inputs_and_missing_transform(self):
        result = series(build_history((self.normalizer.parse(trade()),)), "trade_balance").latest
        for changes in ({"value": Decimal("4.70")}, {"transform_id": None}, {"inputs": tuple(reversed(result.inputs))}, {"definition_id": "different"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                record(result, **changes)
        exports = next(p for p in self.normalizer.parse(trade()).observations if p.series_id == "exports")
        with self.assertRaises(ValidationError):
            record(exports, value=Decimal("-1"))

    def test_trade_missing_and_incompatible_inputs_never_invent_balance(self):
        source = self.normalizer.parse(trade())
        exports = next(p for p in source.observations if p.series_id == "exports" and p.as_of == "2026-09")
        imports = next(p for p in source.observations if p.series_id == "imports" and p.as_of == "2026-09")
        missing = record(imports, value=None, quality_status="missing", reason_code="source_value_missing")
        point = trade_balance(exports, missing)
        self.assertIsNone(point.value)
        self.assertEqual(point.reason_code, "derived_input_missing")
        self.assertIsNone(trade_balance(exports, None))
        for changes in ({"vintage_id": "different"}, {"observation_period": monthly_period(2026, 8)}, {"revision_kind": "provisional"}, {"definition_id": "goods_plus_services"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                trade_balance(exports, record(imports, **changes))
        incomplete = series(build_history((batch([exports]),)), "trade_balance")
        self.assertIsNone(incomplete.latest)
        self.assertEqual(incomplete.window[-1].reason_code, "derived_input_missing")

    def test_trade_yoy_percent_and_gdp_cpi_percentage_points(self):
        result = build_history(tuple(self.normalizer.parse(f()) for f in (trade, gdp, cpi)))
        exports = series(result, "exports").comparison
        self.assertEqual((exports.value.numerator, exports.value.denominator), (100, 9))
        self.assertEqual(exports.value.display_decimal(2), "11.11")
        self.assertEqual(exports.unit, "percent")
        self.assertEqual(exports.reference_period_id, "2025-09")
        self.assertEqual(series(result, "gdp_growth_india").comparison.value.display_decimal(2), "1.90")
        self.assertEqual(series(result, "cpi_yoy").comparison.value.display_decimal(2), "0.20")
        self.assertEqual(series(result, "cpi_yoy").comparison.unit, "percentage_points")
        self.assertEqual(series(result, "trade_balance").comparison.reason_code, "comparison_not_defined")

    def test_five_month_trade_window_sorted_with_prior_year_outside_chart(self):
        template = self.normalizer.parse(trade())
        releases = []
        for month in range(5, 10):
            points = [record(p, observation_period=monthly_period(p.observation_period.end.year, month), vintage_id=f"release-{month}") for p in template.observations]
            releases.append(batch(points))
        result = build_history(tuple(reversed(releases)))
        for sid in ("exports", "imports", "trade_balance"):
            history = series(result, sid)
            self.assertEqual([p.period.id for p in history.window], [f"2026-{m:02}" for m in range(5, 10)])
            self.assertEqual(len(history.observations), 10)
            self.assertEqual(history.status, "available")
        self.assertEqual(series(result, "exports").comparison.reference.observation_period.id, "2025-09")
        self.assertEqual(series(result, "exports").comparison.current.vintage_id, "release-9")

    def test_five_month_cpi_window_uses_later_final_revisions(self):
        template = self.normalizer.parse(cpi()).observations[-1]
        releases = []
        for month in range(6, 10):
            publication = NOW.replace(month=month + 1, day=12)
            vintage = f"cpi-{month}"
            current = record(template, observation_period=monthly_period(2026, month), value=Decimal(month), published_at=publication, vintage_id=vintage)
            prior = record(current, observation_period=monthly_period(2026, month-1), value=Decimal(month-1), revision_kind="final")
            releases.append(batch([current, prior]))
        result = series(build_history(tuple(reversed(releases))), "cpi_yoy")
        self.assertEqual([p.period.id for p in result.window], [f"2026-{m:02}" for m in range(5, 10)])
        self.assertEqual([p.revision_kind for p in result.observations], ["final"] * 4 + ["provisional"])
        self.assertEqual(len(result.superseded), 3)
        self.assertEqual(result.comparison.value.display_decimal(2), "1.00")

    def test_world_previous_year_no_skipping_missing_reference(self):
        current = self.normalizer.parse(wb("3.25")).observations[0]
        prior = record(current, value=Decimal("2.00"), observation_period=annual_period(2024))
        old = record(prior, observation_period=annual_period(2023))
        self.assertEqual(compare(current, (old, prior, current)).value.display_decimal(2), "1.25")
        self.assertEqual(compare(current, (old, current)).reason_code, "reference_observation_missing")
        self.assertEqual(compare(current, (record(prior, value=None, quality_status="missing", reason_code="source_value_missing"), current)).reason_code, "reference_observation_missing")

    def test_ytd_uses_prior_fiscal_cutoff_not_previous_month(self):
        current = next(p for p in self.normalizer.parse(expenditure()).observations if p.series_id == "expenditure_total")
        prior = record(current, value=Decimal("100000"), observation_period=monthly_period(2025, 8, cumulative=True), published_at=NOW - timedelta(days=380), vintage_id="prior")
        july = record(current, value=Decimal("90000"), observation_period=monthly_period(2026, 7, cumulative=True))
        result = compare(current, (july, prior, current))
        self.assertEqual(result.value.display_decimal(3), "23.456")
        self.assertEqual(result.reference_period_id, "FY2025-26:2025-08")
        self.assertEqual(result.transform_id, "same_fiscal_cutoff_percent_change_v1")
        self.assertEqual(compare(current, (july, current)).reason_code, "reference_observation_missing")
        self.assertEqual(compare(current, (record(prior, revision_kind="published"), current)).reason_code, "comparison_inputs_not_comparable")

    def test_comparison_definition_vintage_and_zero_denominator_gates(self):
        source = self.normalizer.parse(trade())
        current, prior = sorted((p for p in source.observations if p.series_id == "exports"), key=lambda p: p.observation_period.end, reverse=True)
        self.assertEqual(compare(current, (record(prior, value=Decimal(0)), current)).reason_code, "zero_reference_denominator")
        for changes in ({"vintage_id": "other"}, {"definition_id": "nominal_different"}, {"unit": "inr_crore"}):
            with self.subTest(changes=changes):
                self.assertEqual(compare(current, (record(prior, **changes), current)).reason_code, "comparison_inputs_not_comparable")
        self.assertEqual(compare(record(current, value=None, quality_status="missing", reason_code="source_value_missing"), (prior,)).reason_code, "current_observation_missing")
        self.assertEqual(compare(record(current, definition_id="unknown"), (prior,)).reason_code, "comparison_definition_unverified")
        self.assertEqual(compare(current, (prior, prior)).reason_code, "reference_revision_unresolved")
        self.assertEqual(compare(current, (record(prior, revision_kind="provisional"), current)).reason_code, "comparison_inputs_not_comparable")

    def test_revision_merge_uses_publication_not_retrieval_and_retains_trace(self):
        current = self.normalizer.parse(cpi()).observations[-1]
        revised = record(current, value=Decimal("0.10"), revision_kind="final", published_at=current.published_at + timedelta(days=1))
        old_refetched = record(current, retrieved_at=NOW + timedelta(days=2))
        first = build_history((batch([revised]), batch([old_refetched]), batch([current])))
        second = build_history((batch([current]), batch([revised]), batch([old_refetched])))
        a, b = series(first, "cpi_yoy"), series(second, "cpi_yoy")
        self.assertEqual(a.latest, b.latest)
        self.assertEqual(a.latest.value, Decimal("0.10"))
        self.assertEqual(len(a.observations), 1)
        self.assertEqual(len(a.superseded), 2)

    def test_conflicting_equal_version_is_gap_not_arbitrary_latest(self):
        point = self.normalizer.parse(wb("2.5")).observations[0]
        conflict = record(point, value=Decimal("3.5"), retrieved_at=NOW + timedelta(days=1))
        result = series(build_history((batch([point]), batch([conflict]))), "gdp_growth_world")
        self.assertIsNone(result.latest)
        self.assertEqual(result.window[-1].reason_code, "conflicting_source_revision")
        self.assertEqual(result.status, "unavailable")

    def test_world_dataset_revision_date_wins_and_same_data_deduplicates(self):
        point = self.normalizer.parse(wb("2.5")).observations[0]
        revised = record(point, value=Decimal("3.5"), dataset_updated_at=date(2026, 10, 9), vintage_id="new")
        old_refetch = record(point, retrieved_at=NOW + timedelta(days=1))
        result = series(build_history((batch([old_refetch]), batch([revised]), batch([point]))), "gdp_growth_world")
        self.assertEqual(result.latest.value, Decimal("3.5"))
        self.assertEqual(len(result.observations), 1)
        duplicate = series(build_history((batch([point]), batch([point]))), "gdp_growth_world")
        self.assertEqual(len(duplicate.observations), 1)

    def test_regression_final_to_provisional_is_rejected(self):
        current = self.normalizer.parse(cpi()).observations[-1]
        final = record(current, revision_kind="final")
        regressed = record(current, published_at=current.published_at + timedelta(days=1))
        result = series(build_history((batch([final]), batch([regressed]))), "cpi_yoy")
        self.assertIsNone(result.latest)
        self.assertEqual(result.window[-1].reason_code, "source_revision_regressed")

    def test_missing_latest_remains_missing_and_never_forward_filled(self):
        current = self.normalizer.parse(wb("null")).observations[0]
        prior = record(current, value=Decimal("2.5"), quality_status="valid", reason_code=None, observation_period=annual_period(2024))
        result = series(build_history((batch([current, prior]),)), "gdp_growth_world")
        self.assertEqual(result.latest.observation_period.id, "CY2025")
        self.assertIsNone(result.latest.value)
        self.assertEqual(result.window[-1].reason_code, "source_value_missing")
        self.assertEqual(result.comparison.reason_code, "current_observation_missing")

    def test_annual_and_ytd_windows_preserve_basis_and_gaps(self):
        result = build_history((self.normalizer.parse(gdp()), self.normalizer.parse(expenditure())))
        india = series(result, "gdp_growth_india")
        self.assertEqual([s.period.id for s in india.window], [f"FY{year}-{str(year+1)[2:]}" for year in range(2021, 2026)])
        self.assertEqual(sum(s.observation is not None for s in india.window), 2)
        self.assertEqual(india.window[0].reason_code, "comparable_base_history_unverified")
        govt = series(result, "expenditure_total")
        self.assertEqual(govt.window[0].reason_code, "published_components_do_not_reconcile")
        self.assertTrue(all(s.period.start == date(2026, 4, 1) for s in govt.window))
        with self.assertRaises(ValueError):
            build_history((), window=25)

    def test_all_thirteen_series_and_eight_blockers_have_explicit_states(self):
        result = build_history(())
        self.assertEqual(len(result.series), 13)
        self.assertEqual(len(result.unavailable_requirements), 8)
        self.assertTrue(all(s.status == "unavailable" and s.reason_code for s in result.series))
        self.assertEqual(series(result, "gst_monthly_average").reason_code, "gstn_reuse_unverified")
        self.assertEqual(series(result, "rbi_target").observations, ())
        result.model_dump(mode="json")

    def test_history_rejects_definition_and_source_gate_bypasses(self):
        current = self.normalizer.parse(wb()).observations[0]
        for changes in ({"definition_id": "different"}, {"unit": "inr_crore"}, {"indicator_id": "trade"}, {"series_id": "gst_total"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                build_history((batch([record(current, **changes)]),))

    def test_exact_results_ignore_decimal_context_and_round_only_for_display(self):
        with localcontext() as context:
            context.prec = 3
            value = ExactValue.of(Fraction(100, 9))
            self.assertEqual(value.display_decimal(18), "11.111111111111111111")
            self.assertEqual(value.model_dump(mode="json"), {"numerator": "100", "denominator": "9"})
            for raw, expected in (("1.005", "1.00"), ("1.015", "1.02"), ("-1.005", "-1.00"), ("-0.001", "0.00")):
                self.assertEqual(ExactValue.of(Fraction(Decimal(raw))).display_decimal(2), expected)
        with self.assertRaises(ValidationError):
            ExactValue(numerator=2, denominator=4)

    def test_cpi_previous_month_annex_does_not_replace_paired_table(self):
        annex = '''<table><tr><td></td><td></td><td>August, 2026 (Final) at Base 2024=100</td><td></td><td></td></tr>
        <tr><td></td><td></td><td>Rural</td><td>Urban</td><td>Combined</td></tr>
        <tr><td>Inflation (%)</td><td>CPI (General)</td><td>81</td><td>71</td><td>-0.20</td></tr></table>'''
        sample = changed(cpi(), '</div></body>', annex + '</div></body>')
        self.assertEqual(len(self.normalizer.parse(sample).observations), 2)

    def test_reviewed_archives_require_family_identity_period_and_release_id(self):
        registry = SourceRegistry.load()
        key = "commerce_trade_pib.history.2026-08"
        resource = registry.resolve(key)
        original = trade()
        body = original.payload.body.replace(b"2323944", b"2310636").replace(b"September", b"August")
        sample = replace(original, payload=replace(original.payload, source_id=key, resource_url=resource.url, response_url=resource.url, body=body))
        self.assertEqual(len(self.normalizer.parse(sample).observations), 4)
        with self.assertRaises(ParseError):
            self.normalizer.parse(replace(sample, payload=replace(sample.payload, body=body.replace(b"August", b"September"))))
        with self.assertRaises(ParseError):
            self.normalizer.parse(replace(sample, source_id="mospi_cpi_pib"))
        self.assertNotIn("finance_accounts_pib.history.2026-04", registry.resources)

    def test_older_finance_titles_and_inconsistent_totals(self):
        sample = changed(expenditure(), "Union Government of India", "Government of India")
        self.assertEqual(len(self.normalizer.parse(sample).observations), 3)
        sample = changed(sample, "upto the month of August, 2026", "for April 2026")
        sample = changed(sample, "1,23,456", "5,74,892")
        sample = changed(sample, "1,00,000", "3,85,151")
        sample = changed(sample, "23,456", "1,89,831")
        with self.assertRaises(ParseError):
            self.normalizer.parse(sample)


class HistoryAcquisitionTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_source_isolated_no_automatic_ack_or_blocked_requests(self):
        registry = SourceRegistry.load()
        ids = ("commerce_trade_pib", "world_bank_gdp")
        resources = {key: value for key, value in registry.resources.items() if key in (*ids, "world_bank_gdp.metadata")}
        registry = replace(registry, source_ids=ids, resources=MappingProxyType(resources))
        hits = []
        def handler(request):
            hits.append(request)
            if request.url.host == "api.worldbank.org":
                return httpx.Response(404)
            return httpx.Response(200, content=trade().payload.body, headers={"content-type": "text/html", "etag": '"new"'})
        async with CollectorHttpClient(registry=registry, settings=CollectorSettings(_env_file=None, min_interval=0.001, max_attempts=1), transport=httpx.MockTransport(handler), utc_now=lambda: NOW) as client:
            result = await collect_history(client)
            self.assertEqual(len(result.batches), 1)
            self.assertEqual(len(result.receipts), 1)
            self.assertEqual(result.snapshot.failures[0].reason_code, "rejected_http_status")
            self.assertEqual(series(result.snapshot, "exports").latest.value, Decimal("12.50"))
            self.assertEqual(series(result.snapshot, "gdp_growth_world").status, "unavailable")
            self.assertEqual(client._accepted, {})
            with self.assertRaises(ValueError):
                await create_adapters(client)["commerce_trade_pib"].acquire(resource_id="world_bank_gdp")
            self.assertEqual(len(hits), 2)


if __name__ == "__main__":
    unittest.main()
