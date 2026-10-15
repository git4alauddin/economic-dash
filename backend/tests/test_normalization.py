"""Synthetic source structures only; no saved upstream payloads or financial defaults."""

import asyncio
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
import json
import unittest

import httpx2 as httpx
from pydantic import ValidationError

from app.collectors.adapters import SourcePayloads, create_adapters
from app.collectors.catalog import SourceRegistry
from app.collectors.errors import AcquisitionError
from app.collectors.http_client import CollectorHttpClient, FetchResult
from app.collectors.html_document import Document, table_grid
from app.collectors.normalization import SourceNormalizer, scaled_amount
from app.collectors.observations import (
    NormalizedBatch, NormalizedObservation, ParseError, annual_period,
    decimal_value, fiscal_start, monthly_period,
)
from app.config import CollectorSettings

NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
REGISTRY = SourceRegistry.load()


def response(source_id, body, *, metadata=False):
    key = source_id + (".metadata" if metadata else "")
    resource = REGISTRY.resolve(key)
    return FetchResult(key, resource.url, resource.url, "modified", body.encode("utf-8"), "application/json" if resource.format == "json" else "text/html", NOW, 1, 1, '"synthetic"')


def wb(value="2.123456789012345678", *, year="2025", flag="", total=1):
    info = {"page": 1, "pages": 1, "per_page": 10, "total": total, "sourceid": "2", "lastupdated": "2026-10-08"}
    row = {"countryiso3code": "WLD", "country": {"value": "World"}, "indicator": {"id": "NY.GDP.MKTP.KD.ZG"}, "date": year, "value": "TOKEN", "unit": "", "obs_status": flag}
    data = json.dumps([info, [row] if total else []]).replace('"TOKEN"', value)
    metadata = json.dumps([{}, [{"id": "NY.GDP.MKTP.KD.ZG", "name": "GDP growth (annual %)", "source": {"id": "2"}, "sourceNote": "Percentage change over the previous year of the constant price series."}]])
    return SourcePayloads("world_bank_gdp", response("world_bank_gdp", data), response("world_bank_gdp", metadata, metadata=True))


def pib(source_id, ministry, title, body, *, posted="15 OCT 2026 4:00PM", hindi=False):
    release = REGISTRY.resolve(source_id).url.split("PRID=")[1].split("&")[0]
    prefix = "प्रविष्टि तिथि" if hindi else "Posted On"
    label = "रिलीज़ आईडी" if hindi else "Release ID"
    html = f'''<html><body><div class="innner-page-main-about-us-content-right-part">
    <div id="MinistryName">Ministry of {ministry}</div><h1 id="Titleh2">{title}</h1>
    <div id="PrDateTime">{prefix}: {posted} by PIB Delhi</div>{body}
    <span id="ReleaseId">({label}: {release})</span></div></body></html>'''
    return SourcePayloads(source_id, response(source_id, html))


def gdp():
    return pib("mospi_gdp_pib", "Statistics &amp; Programme Implementation", "PROVISIONAL ESTIMATES OF ANNUAL GROSS DOMESTIC PRODUCT FOR 2025-26", '''
    <p>Provisional Estimates, constant prices with base year 2022-23.</p>
    <p>First Revised Estimate (FRE) is the prior vintage.</p>
    <p>The growth rate in Real GDP during 2025-26 is estimated at 8.10% as compared to 6.20 % in 2024-25.
    Nominal GDP growth is 90% and Q4 GDP growth is 70%.</p>''', posted="05 JUN 2026 4:00PM")


def trade(*, million=False):
    unit = "Million" if million else "Billion"
    return pib("commerce_trade_pib", "Commerce &amp; Industry", "Monthly foreign trade", f'''
    <table><tr><td></td><td></td><td>September 2026 (US$ {unit})</td><td>September 2025 (US$ {unit})</td></tr>
    <tr><td rowspan="2">Merchandise</td><td>Exports</td><td>12.50</td><td>11.25</td></tr>
    <tr><td>Imports</td><td>17.20</td><td>16.00</td></tr>
    <tr><td rowspan="2">Services</td><td>Exports</td><td>999</td><td>999</td></tr>
    <tr><td>Imports</td><td>999</td><td>999</td></tr></table>
    <table><tr><td>Merchandise Exports</td><td>April-September 2026-27 (US$ Billion)</td><td>9999</td></tr></table>''')


def cpi():
    return pib("mospi_cpi_pib", "Statistics &amp; Programme Implementation", "CONSUMER PRICE INDEX ON BASE 2024=100", '''
    <table><tr><td colspan="2" rowspan="2"></td><td colspan="3" rowspan="2">August, 2026 (Final)</td><td colspan="3" rowspan="2">September, 2026 (Provisional)</td></tr>
    <tr></tr><tr><td></td><td></td><td>Rural</td><td>Urban</td><td>Combined</td><td>Rural</td><td>Urban</td><td>Combined</td></tr>
    <tr><td rowspan="2">Inflation (%)</td><td>CPI (General)</td><td>81</td><td>71</td><td>-0.20</td><td>82</td><td>72</td><td>0.00</td></tr>
    <tr><td>CFPI</td><td>55</td><td>55</td><td>55</td><td>55</td><td>55</td><td>55</td></tr>
    <tr><td>Index</td><td>CPI (General)</td><td>111</td><td>111</td><td>111</td><td>112</td><td>112</td><td>112</td></tr></table>''', posted="12 OCT 2026 4:00PM", hindi=True)


def expenditure():
    return pib("finance_accounts_pib", "Finance", "Monthly Review of Accounts of Union Government of India (FY 2026-27)", '''
    <p>The Monthly Accounts upto the month of August, 2026 have been consolidated.</p>
    <p>Total Expenditure incurred by Government of India is ₹1,23,456 crore (20% of corresponding BE 2026-27), out of which ₹1,00,000 crore is on Revenue Account and ₹23,456 crore is on Capital Account. Interest payments are ₹999 crore.</p>''', posted="30 SEP 2026 4:41PM")


def changed(bundle, old, new):
    body = bundle.payload.body.decode("utf-8").replace(old, new)
    return replace(bundle, payload=replace(bundle.payload, body=body.encode("utf-8")))


class NormalizationTests(unittest.TestCase):
    def setUp(self):
        self.normalizer = SourceNormalizer()

    def test_world_bank_exact_decimals_year_precision_and_revision_date(self):
        result = self.normalizer.parse(wb())
        point = result.observations[0]
        self.assertEqual(point.value, Decimal("2.123456789012345678"))
        self.assertEqual(point.model_dump(mode="json")["value"], "2.123456789012345678")
        self.assertEqual(point.as_of, "2025")
        self.assertEqual(point.as_of_precision, "year")
        self.assertEqual(point.dataset_updated_at, date(2026, 10, 8))
        self.assertIsNone(point.published_at)
        self.assertEqual(len(point.sources), 2)
        self.assertTrue(all(not source.is_nse for source in point.sources))

    def test_null_is_missing_but_zero_is_valid(self):
        missing = self.normalizer.parse(wb("null")).observations[0]
        zero = self.normalizer.parse(wb("0")).observations[0]
        self.assertIsNone(missing.value)
        self.assertEqual(missing.reason_code, "source_value_missing")
        self.assertEqual(zero.quality_status, "valid")
        self.assertEqual(zero.value, Decimal(0))

    def test_empty_source_is_explicit_and_supplies_no_observations(self):
        batch = self.normalizer.parse(wb(total=0))
        self.assertEqual(batch.outcome, "empty")
        self.assertEqual(batch.reason_code, "source_dataset_empty")
        self.assertEqual(batch.observations, ())

    def test_nonfinite_invalid_precision_boolean_and_implausible_numbers_rejected(self):
        for value in ["NaN", "Infinity", "-Infinity", "true", "1e99999", "1e-99999", "-100.01", "1001", '"1,23,4"', '"not a number"']:
            with self.subTest(value=value), self.assertRaises(ParseError):
                self.normalizer.parse(wb(value))
        with self.assertRaises(ValueError):
            decimal_value(0.1)
        with self.assertRaises(ValueError):
            decimal_value(True)

    def test_world_bank_identity_units_metadata_and_pagination_fail_closed(self):
        sample = wb()
        for old, new in [('"WLD"', '"IND"'), ('"World"', '"India"'), ('"unit": ""', '"unit": "usd"'), ('"page": 1', '"page": 2'), ('"per_page": 10', '"per_page": 1000'), ('"2026-10-08"', '"2027-10-08"'), ('"2026-10-08"', '"2026-99-99"')]:
            with self.subTest(old=old), self.assertRaises(ParseError):
                self.normalizer.parse(changed(sample, old, new))
        for old, new in [('constant price', 'current price'), ('GDP growth (annual %)', 'GDP (current US$)')]:
            invalid = replace(sample, metadata=replace(sample.metadata, body=sample.metadata.body.replace(old.encode(), new.encode())))
            with self.assertRaises(ParseError):
                self.normalizer.parse(invalid)
        for invalid in [replace(sample, metadata=None), replace(sample, metadata=replace(sample.metadata, outcome="not_modified", body=None)), wb(flag="E"), wb(year="2026")]:
            with self.assertRaises(ParseError):
                self.normalizer.parse(invalid)

    def test_duplicate_json_keys_and_duplicate_periods_are_not_overwritten(self):
        sample = wb()
        with self.assertRaises(ParseError):
            self.normalizer.parse(changed(sample, '"page": 1', '"page": 1, "page": 1'))
        data = json.loads(sample.payload.body)
        data[0]["total"] = 2
        data[1] *= 2
        with self.assertRaises(ParseError):
            self.normalizer.parse(replace(sample, payload=replace(sample.payload, body=json.dumps(data).encode())))

    def test_gdp_uses_annual_real_growth_and_preserves_estimate_categories(self):
        points = self.normalizer.parse(gdp()).observations
        self.assertEqual([point.value for point in points], [Decimal("6.20"), Decimal("8.10")])
        self.assertEqual([point.revision_kind for point in points], ["first_revised", "provisional"])
        self.assertEqual(points[1].observation_period.id, "FY2025-26")
        self.assertEqual(points[1].as_of, "2026")
        self.assertEqual(points[1].published_at, datetime(2026, 6, 5, 10, 30, tzinfo=timezone.utc))
        self.assertEqual(points[1].publication_timezone, "Asia/Kolkata")
        self.assertEqual(points[1].publication_precision, "minute")

    def test_gdp_rejects_base_and_definition_drift(self):
        for old, new in [("2022-23", "2011-12"), ("growth rate in Real GDP", "growth rate in Nominal GDP"), ("2024-25.", "2023-24."), ("First Revised Estimate (FRE)", "Budget estimate")]:
            with self.subTest(old=old), self.assertRaises(ParseError):
                self.normalizer.parse(changed(gdp(), old, new))

    def test_trade_expands_rowspans_and_excludes_services_and_cumulative_totals(self):
        points = self.normalizer.parse(trade()).observations
        self.assertEqual(len(points), 4)
        current = {point.series_id: point.value for point in points if point.observation_period.id == "2026-09"}
        self.assertEqual(current, {"exports": Decimal("12.50"), "imports": Decimal("17.20")})
        self.assertNotIn("trade_balance", {point.series_id for point in points})  # M3.5 owns derivation.
        missing = self.normalizer.parse(changed(trade(), "12.50", "—"))
        self.assertEqual(sum(point.value is None for point in missing.observations), 1)

    def test_units_convert_exactly_and_wrong_currency_is_rejected(self):
        points = self.normalizer.parse(trade(million=True)).observations
        self.assertIn(Decimal("0.01250"), [point.value for point in points])
        self.assertTrue(all(point.unit == "usd_billion" and point.source_unit == "usd_million" for point in points))
        self.assertEqual(scaled_amount("12.50", "inr_lakh_crore", "inr_crore")[0], Decimal("1250000"))
        with self.assertRaises(ParseError):
            self.normalizer.parse(changed(trade(), "US$ Billion", "INR Crore"))
        self.normalizer.catalog["requirements"]["exports"]["unit"] = "percent_yoy"
        with self.assertRaises(ParseError):
            self.normalizer.parse(trade())

    def test_conflicting_duplicate_tables_and_bad_spans_rejected(self):
        sample = trade()
        body = sample.payload.body.decode()
        table = body[body.index("<table>"):body.index("</table>")+8]
        with self.assertRaises(ParseError):
            self.normalizer.parse(changed(sample, "</span></div>", table.replace("12.50", "99.00") + "</span></div>"))
        with self.assertRaises(ParseError):
            self.normalizer.parse(changed(sample, 'rowspan="2"', 'rowspan="99999"'))

    def test_cpi_uses_combined_inflation_not_rural_food_or_index_level(self):
        points = self.normalizer.parse(cpi()).observations
        self.assertEqual([point.value for point in points], [Decimal("-0.20"), Decimal("0.00")])
        self.assertEqual([point.revision_kind for point in points], ["final", "provisional"])
        self.assertEqual([point.observation_period.id for point in points], ["2026-08", "2026-09"])
        self.assertTrue(all(point.unit == "percent_yoy" for point in points))

    def test_cpi_requires_base_geography_rate_header_and_consecutive_months(self):
        for old, new in [("2024=100", "2012=100"), ("Combined", "Total"), ("Inflation (%)", "Index"), ("August, 2026", "July, 2026")]:
            with self.subTest(old=old), self.assertRaises(ParseError):
                self.normalizer.parse(changed(cpi(), old, new))

    def test_expenditure_preserves_cumulative_actuals_and_published_total(self):
        points = self.normalizer.parse(expenditure()).observations
        self.assertEqual({point.series_id: point.value for point in points}, {"expenditure_total": Decimal(123456), "expenditure_revenue": Decimal(100000), "expenditure_capital": Decimal(23456)})
        for point in points:
            self.assertEqual(point.revision_kind, "provisional_actual")
            self.assertEqual(point.observation_period.id, "FY2026-27:2026-08")
            self.assertEqual(point.observation_period.start, date(2026, 4, 1))
            self.assertEqual(point.observation_period.end, date(2026, 8, 31))
            self.assertEqual(point.as_of, "2026-08")
        with self.assertRaises(ParseError):
            self.normalizer.parse(changed(expenditure(), "₹23,456", "₹29,999"))
        with self.assertRaises(ParseError):
            self.normalizer.parse(changed(expenditure(), "1,23,456", "1,23,45"))

    def test_foreign_pages_hidden_decoys_and_release_id_mismatch(self):
        for old, new in [("Ministry of Commerce", "Ministry of Tourism"), ("2323944)", "9999999)"), ("4:00PM", "4:00PM EST"), ("15 OCT 2026", "15 OCT 2027")]:
            with self.subTest(old=old), self.assertRaises(ParseError):
                self.normalizer.parse(changed(trade(), old, new))
        sample = changed(trade(), "<table>", '<script>Merchandise 9999</script><div style="display: none">bad</div><table>')
        self.assertEqual(len(self.normalizer.parse(sample).observations), 4)

    def test_source_gate_and_transport_identity_cannot_be_bypassed(self):
        sample = wb()
        with self.assertRaises(AcquisitionError):
            self.normalizer.parse(replace(sample, source_id="nse_indices"))
        for change in [{"response_url": "https://evil.example/"}, {"content_type": "text/html"}, {"outcome": "not_modified", "body": None}, {"retrieved_at": NOW.replace(tzinfo=None)}]:
            with self.subTest(change=change), self.assertRaises(ParseError):
                self.normalizer.parse(replace(sample, payload=replace(sample.payload, **change)))

    def test_period_and_observation_invariants(self):
        self.assertEqual(annual_period(2025, fiscal=True).end, date(2026, 3, 31))
        self.assertEqual(monthly_period(2024, 2).end, date(2024, 2, 29))
        with self.assertRaises(ValueError):
            fiscal_start("2025-27")
        point = self.normalizer.parse(wb()).observations[0]
        for change in [{"value": 1.5}, {"value": None}, {"as_of": "2025-12-31"}, {"published_at": NOW, "publication_timezone": None}, {"unit": "USD"}]:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                NormalizedObservation(**(point.model_dump() | change))
        with self.assertRaises(ValidationError):
            NormalizedBatch(source_id="world_bank_gdp", observations=(point, point), coverage="bounded_page")
        with self.assertRaises(ValidationError):
            NormalizedBatch(source_id="world_bank_gdp", observations=(), coverage="bounded_page")


class AdapterNormalizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_response_never_commits_cache_validators(self):
        requests = []
        sample = trade()
        def handler(request):
            requests.append(request)
            body = sample.payload.body if len(requests) > 1 else b"<html>unrelated error page</html>"
            return httpx.Response(200, content=body, headers={"content-type": "text/html", "etag": '"upstream"'})
        async with CollectorHttpClient(settings=CollectorSettings(_env_file=None, min_interval=0.001), transport=httpx.MockTransport(handler)) as client:
            adapter = create_adapters(client)["commerce_trade_pib"]
            with self.assertRaises(ParseError):
                adapter.normalize(await adapter.acquire())
            batch = adapter.normalize(await adapter.acquire())
            self.assertEqual(len(batch.observations), 4)
            self.assertTrue(all("if-none-match" not in request.headers for request in requests))


if __name__ == "__main__":
    unittest.main()
