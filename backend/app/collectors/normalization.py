"""Versioned parsers for the five selected sources; rejects whole unsafe batches."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from hashlib import sha256
import json
import re
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

from .catalog import CATALOG_PATH, SourceRegistry
from .html_document import Document, table_grid
from .observations import (
    MONTHS, NUMBER, NormalizedBatch, NormalizedObservation, ObservationPeriod,
    ParseError, SourceReference, annual_period, decimal_value, fiscal_start, monthly_period,
)

if TYPE_CHECKING:
    from .adapters import SourcePayloads
    from .http_client import FetchResult

PARSER_VERSION = "m3-normalization-v2"
IST = timezone(timedelta(hours=5, minutes=30))


@dataclass(frozen=True)
class Point:
    series: str
    value: Decimal | None
    period: ObservationPeriod
    revision: str
    source_unit: str
    normalization: str = "identity_v1"


def unique(values, field: str):
    values = set(values)
    if len(values) != 1:
        raise ValueError(f"Missing or ambiguous {field}.")
    return next(iter(values))


def json_document(body: bytes):
    if len(body) > 2_000_000:
        raise ValueError("JSON parser size limit exceeded.")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key.")
            result[key] = value
        return result
    def invalid_constant(_value):
        raise ValueError("Non-finite JSON number.")
    return json.loads(body.decode("utf-8-sig"), parse_float=Decimal, parse_constant=invalid_constant, object_pairs_hook=pairs)


def scaled_amount(token: str, source_unit: str, target_unit: str) -> tuple[Decimal | None, str]:
    factors = {
        ("usd_billion", "usd_billion"): Decimal(1),
        ("usd_million", "usd_billion"): Decimal("0.001"),
        ("inr_crore", "inr_crore"): Decimal(1),
        ("inr_lakh_crore", "inr_crore"): Decimal("1e5"),
    }
    factor = factors[(source_unit, target_unit)]
    value = decimal_value(token)
    with localcontext() as context:
        context.prec = 50  # Never round the accepted <=38-digit source tokens.
        normalized = value * factor if value is not None else None
    return normalized, "identity_v1" if source_unit == target_unit else f"scale_{source_unit}_to_{target_unit}_v1"


def world_bank(bundle: "SourcePayloads"):
    data = json_document(bundle.payload.body)
    metadata = json_document(bundle.metadata.body)
    if not isinstance(data, list) or len(data) != 2 or not isinstance(data[0], dict) or not isinstance(data[1], list):
        raise ValueError("Unexpected World Bank response envelope.")
    info, rows = data
    if not isinstance(metadata, list) or len(metadata) != 2 or len(metadata[1]) != 1:
        raise ValueError("World Bank indicator metadata is required.")
    definition = metadata[1][0]
    if definition["id"] != "NY.GDP.MKTP.KD.ZG" or definition["name"] != "GDP growth (annual %)" or str(definition["source"]["id"]) != "2":
        raise ValueError("World Bank indicator/unit mismatch.")
    if not re.search(r"percentage change.*constant price", definition["sourceNote"], re.I | re.S):
        raise ValueError("World Bank real-growth methodology changed.")
    if str(info["sourceid"]) != "2" or info["page"] != 1:
        raise ValueError("Unexpected World Bank dataset/page.")
    for field in ("page", "pages", "total"):
        if type(info[field]) is not int or info[field] < (0 if field == "total" else 1):
            raise ValueError("Invalid pagination metadata.")
    raw_per_page = info["per_page"]
    if type(raw_per_page) is not int and not (isinstance(raw_per_page, str) and re.fullmatch(r"\d{1,2}", raw_per_page, re.ASCII)):
        raise ValueError("Invalid per-page metadata.")
    per_page = int(raw_per_page)
    if not 1 <= per_page <= 10 or len(rows) != min(per_page, info["total"]) or info["pages"] != max(1, (info["total"] + per_page - 1) // per_page):
        raise ValueError("Unbounded or inconsistent World Bank page.")
    if not isinstance(info["lastupdated"], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", info["lastupdated"], flags=re.ASCII):
        raise ValueError("World Bank dataset revision needs a valid source date.")
    updated = date.fromisoformat(info["lastupdated"])
    if updated > bundle.payload.retrieved_at.date():
        raise ValueError("World Bank dataset revision is in the future.")
    points = []
    for row in rows:
        if row["countryiso3code"] != "WLD" or row["country"]["value"] != "World" or row["indicator"]["id"] != definition["id"]:
            raise ValueError("Wrong World Bank geography/series.")
        if row["unit"] not in {"", "%", "percent"} or row["obs_status"] != "":
            raise ValueError("Unsupported observation unit/status.")
        if not isinstance(row["date"], str) or not re.fullmatch(r"\d{4}", row["date"], flags=re.ASCII):
            raise ValueError("Annual source year required.")
        points.append(Point("gdp_growth_world", decimal_value(row["value"]), annual_period(int(row["date"])), "published", "percent_yoy"))
    return points, None, updated, info["pages"] > 1


def pib_release(bundle: "SourcePayloads", ministry: str):
    document = Document(bundle.payload.body)
    roots = [node for node in document.root.find("div") if "innner-page-main-about-us-content-right-part" in (node.attrs.get("class") or "").split()]
    if len(roots) != 1:
        raise ValueError("PIB release container changed or is ambiguous.")
    root = roots[0]
    title = unique([node.text() for node in root.find(id="Titleh2")], "release title")
    publisher = unique([node.text() for node in root.find(id="MinistryName")], "ministry")
    if ministry.casefold() not in publisher.casefold():
        raise ValueError("Wrong issuing ministry.")
    release_id = unique(re.findall(r":\s*(\d+)\s*\)", unique([node.text() for node in root.find(id="ReleaseId")], "release ID")), "release ID")
    expected_id = parse_qs(urlsplit(bundle.payload.resource_url).query)["PRID"][0]
    if release_id != expected_id:
        raise ValueError("PIB release ID mismatch.")
    stamp = unique([node.text() for node in root.find(id="PrDateTime")], "publication time")
    found = re.fullmatch(r"(?:Posted On|प्रविष्टि तिथि):\s*(\d{1,2})\s+([A-Z]{3})\s+(\d{4})\s+(\d{1,2}):(\d{2})\s*(AM|PM)\s+by PIB Delhi", stamp, re.I)
    if not found:
        raise ValueError("Unrecognized PIB publication timestamp/timezone.")
    month = unique([number for name, number in MONTHS.items() if name[:3] == found[2].lower()], "publication month")
    hour = int(found[4])
    if not 1 <= hour <= 12:
        raise ValueError("Invalid publication hour.")
    published = datetime(int(found[3]), month, int(found[1]), hour % 12 + (12 if found[6].upper() == "PM" else 0), int(found[5]), tzinfo=IST).astimezone(timezone.utc)
    return root, title, published


def india_gdp(root, title: str):
    text = root.text()
    if "ANNUAL GROSS DOMESTIC PRODUCT" not in title.upper() or not re.search(r"(?:base year\s+|Constant\s*\()2022-23", text, re.I):
        raise ValueError("Annual GDP title or constant-price base changed.")
    if "Provisional Estimates" not in text or not re.search(r"First Revised Estimate\s*\(FRE\)", text):
        raise ValueError("GDP estimate categories changed.")
    pattern = rf"The growth rate in Real GDP during (\d{{4}}-\d{{2}}) is estimated at ({NUMBER})\s*% as compared to ({NUMBER})\s*% in (\d{{4}}-\d{{2}})"
    current, value, prior_value, prior = unique([match for node in root.find("p") for match in re.findall(pattern, node.text())], "annual real GDP growth statement")
    current_year, prior_year = fiscal_start(current), fiscal_start(prior)
    if prior_year != current_year - 1 or current not in title:
        raise ValueError("Inconsistent GDP fiscal periods.")
    return [
        Point("gdp_growth_india", decimal_value(value), annual_period(current_year, fiscal=True), "provisional", "percent_yoy"),
        Point("gdp_growth_india", decimal_value(prior_value), annual_period(prior_year, fiscal=True), "first_revised", "percent_yoy"),
    ]


def trade(root, _title: str):
    alternatives = []
    for table in root.find("table"):
        if "Merchandise" not in table.text() or "Exports" not in table.text():
            continue
        grid = table_grid(table)
        if not grid or len(grid[0]) != 4:
            continue
        headers = [re.fullmatch(r"([A-Za-z]+)\s+(\d{4})\s*\(US\$\s+(Billion|Million)\)", cell, re.I) for cell in grid[0][2:]]
        if not all(headers):  # Explicitly excludes cumulative April-September tables.
            continue
        periods = [monthly_period(int(header[2]), MONTHS[header[1].lower()]) for header in headers]
        if periods[0].end.month != periods[1].end.month or periods[0].end.year != periods[1].end.year + 1:
            raise ValueError("Trade current/prior-year periods do not align.")
        points = []
        for name, series in (("Exports", "exports"), ("Imports", "imports")):
            values = unique([tuple(row[2:]) for row in grid if row[:2] == ["Merchandise", name]], f"merchandise {name}")
            for header, period, token in zip(headers, periods, values):
                source_unit = f"usd_{header[3].lower()}"
                value, transform = scaled_amount(token, source_unit, "usd_billion")
                points.append(Point(series, value, period, "published", source_unit, transform))
        alternatives.append(tuple(points))
    return list(unique(alternatives, "monthly merchandise table"))


def cpi(root, _title: str):
    text = root.text()
    if not re.search(r"(?:base\s*:?\s*2024\s*=\s*100|2024\s*=\s*100)", text, re.I):
        raise ValueError("CPI base 2024 is not verified in the release.")
    alternatives = []
    for table in root.find("table"):
        text = table.text()
        if "CPI (General)" not in text or "Inflation (%)" not in text or "Combined" not in text:
            continue
        grid = table_grid(table)
        if len(grid[0]) == 5:  # Separate previous-month annex; the paired table supplies that month.
            continue
        data_index = unique([index for index, row in enumerate(grid) if row[:2] == ["Inflation (%)", "CPI (General)"]], "headline CPI inflation row")
        headings = grid[:data_index]
        geography = unique([tuple(row) for row in headings if row.count("Combined") == 2], "CPI geography header")
        points = []
        for column, name in enumerate(geography):
            if name != "Combined":
                continue
            raw = unique([row[column] for row in headings if re.fullmatch(r"[A-Za-z]+,?\s+\d{4}\s+\((?:Final|Provisional)\)", row[column])], "CPI observation month/category")
            found = re.fullmatch(r"([A-Za-z]+),?\s+(\d{4})\s+\((Final|Provisional)\)", raw)
            period = monthly_period(int(found[2]), MONTHS[found[1].lower()])
            points.append(Point("cpi_yoy", decimal_value(grid[data_index][column]), period, found[3].lower(), "percent_yoy"))
        points.sort(key=lambda item: item.period.start)
        if len(points) != 2 or points[1].period.start != points[0].period.end + timedelta(days=1):
            raise ValueError("CPI months are not consecutive.")
        alternatives.append(tuple(points))
    return list(unique(alternatives, "combined headline CPI table"))


def expenditure(root, title: str):
    cutoff = unique(re.findall(r"(?:upto (?:the month of )?|for )([A-Za-z]+),?\s+(\d{4})", root.text(), re.I), "expenditure cutoff")
    period = monthly_period(int(cutoff[1]), MONTHS[cutoff[0].lower()], cumulative=True)
    if not re.search(r"(?:Union Government(?: of India)?|Government of India)", title, re.I) or period.id.split(":")[0][2:] not in title:
        raise ValueError("Wrong government coverage or fiscal year.")
    rupee = r"(?:₹|Rs\.?)[\s]*"
    unit = r"(lakh crore|crore)"
    pattern = rf"Total Expenditure incurred by Government of India is\s*{rupee}({NUMBER})\s*{unit}\s*\([^)]*\),?\s*out of which\s*{rupee}({NUMBER})\s*{unit}\s*is on Revenue Account and\s*{rupee}({NUMBER})\s*{unit}\s*is on Capital Account"
    tokens = unique([match for node in root.find("p") for match in re.findall(pattern, node.text(), re.I)], "published expenditure amounts")
    points = []
    for series, token, raw_unit in zip(("expenditure_total", "expenditure_revenue", "expenditure_capital"), tokens[::2], tokens[1::2]):
        source_unit = "inr_lakh_crore" if raw_unit.lower() == "lakh crore" else "inr_crore"
        value, transform = scaled_amount(token, source_unit, "inr_crore")
        points.append(Point(series, value, period, "provisional_actual", source_unit, transform))
    if all(point.value is not None for point in points):
        with localcontext() as context:
            context.prec = 50
            tolerance = sum(Decimal(1).scaleb(point.value.as_tuple().exponent) for point in points) / 2
            if abs(points[0].value - points[1].value - points[2].value) > tolerance:
                raise ValueError("Published expenditure components do not reconcile at source precision.")
    return points


class SourceNormalizer:
    def __init__(self, registry: SourceRegistry | None = None):
        self.registry = registry if registry is not None else SourceRegistry.load()
        self.catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        requirements = json.loads((CATALOG_PATH.parent / "indicator-requirements.json").read_text(encoding="utf-8"))
        self.publishers = requirements["publishers"]
        self.indicators = {series["id"]: panel["indicator_id"] for panel in requirements["panels"] for series in panel["series"]}

    def _check_response(self, result: "FetchResult", expected: str) -> None:
        resource = self.registry.resolve(expected)
        if result.source_id != expected or result.resource_url != resource.url or urlsplit(result.response_url).hostname != urlsplit(resource.url).hostname or urlsplit(result.response_url).scheme != "https":
            raise ParseError(expected, "source_identity_mismatch")
        if result.outcome != "modified" or result.body is None:
            raise ParseError(expected, "conditional_body_required")
        if result.retrieved_at.utcoffset() != timedelta(0):
            raise ParseError(expected, "invalid_retrieval_timestamp")
        expected_types = {"json": {"application/json"}, "html": {"text/html", "application/xhtml+xml"}, "pdf": {"application/pdf"}}
        if (result.content_type or "").partition(";")[0].strip().lower() not in expected_types[resource.format]:
            raise ParseError(expected, "source_content_type_mismatch")

    def parse(self, bundle: "SourcePayloads") -> NormalizedBatch:
        source_id = bundle.source_id
        self.registry.resolve(source_id)  # Disabled feeds cannot bypass the gate via fixtures.
        try:
            resource_id = bundle.payload.source_id
            if resource_id not in self.registry.observation_resources(source_id):
                raise ParseError(source_id, "source_identity_mismatch")
            self._check_response(bundle.payload, resource_id)
            expected_metadata = f"{source_id}.metadata" in self.registry.resources
            if expected_metadata != (bundle.metadata is not None):
                raise ParseError(source_id, "source_metadata_mismatch")
            if bundle.metadata:
                self._check_response(bundle.metadata, f"{source_id}.metadata")
            if source_id == "world_bank_gdp":
                points, published, dataset_updated, more_pages = world_bank(bundle)
            else:
                parsers = {"mospi_gdp_pib": (india_gdp, "Statistics"), "commerce_trade_pib": (trade, "Commerce"), "mospi_cpi_pib": (cpi, "Statistics"), "finance_accounts_pib": (expenditure, "Finance")}
                parser, ministry = parsers[source_id]
                root, title, published = pib_release(bundle, ministry)
                points = parser(root, title)
                dataset_updated, more_pages = None, False
            if resource_id.startswith(f"{source_id}.history.") and max(point.period.end for point in points).strftime("%Y-%m") != resource_id.rsplit(".", 1)[-1]:
                raise ParseError(source_id, "history_release_period_mismatch")
            profile = self.catalog["sources"][source_id]
            publisher = self.publishers[profile["publisher_id"]]
            name = publisher["name"] + (" (via PIB)" if profile.get("delivery_publisher_id") == "pib" else "")
            source = SourceReference(source_id=source_id, name=name, url=bundle.payload.response_url, is_nse=publisher["is_nse"])
            references = (source,)
            if bundle.metadata:
                references += (SourceReference(source_id=f"{source_id}.metadata", name=f"{name} indicator metadata", url=bundle.metadata.response_url, is_nse=publisher["is_nse"]),)
            digest = sha256(bundle.payload.body + (b"\x00" + bundle.metadata.body if bundle.metadata else b"")).hexdigest()
            observations = []
            for point in points:
                definition = self.catalog["requirements"][point.series]
                unit = {"usd_million": "usd_billion", "usd_billion": "usd_billion", "inr_lakh_crore": "inr_crore", "inr_crore": "inr_crore", "percent_yoy": "percent_yoy"}[point.source_unit]
                if definition["source_id"] != source_id or definition["status"] != "selected" or definition["frequency"] != point.period.frequency or definition["basis"] != point.period.basis or definition["unit"] != unit:
                    raise ValueError("Parsed series does not match the selected definition.")
                precision = "year" if point.period.frequency == "annual" else "month"
                observations.append(NormalizedObservation(
                    indicator_id=self.indicators[point.series], series_id=point.series, definition_id=definition["definition_id"],
                    value=point.value, unit=definition["unit"], observation_period=point.period,
                    as_of=point.period.end.strftime("%Y" if precision == "year" else "%Y-%m"), as_of_precision=precision,
                    published_at=published, publication_precision="minute" if published else None, publication_timezone="Asia/Kolkata" if published else None,
                    retrieved_at=bundle.payload.retrieved_at, sources=references,
                    quality_status="missing" if point.value is None else "valid", reason_code="source_value_missing" if point.value is None else None,
                    revision_kind=point.revision, vintage_id=f"sha256:{digest}", parser_version=PARSER_VERSION,
                    source_unit=point.source_unit, normalization_id=point.normalization, dataset_updated_at=dataset_updated,
                ))
            observations.sort(key=lambda item: (item.series_id, item.observation_period.start))
            return NormalizedBatch(source_id=source_id, observations=tuple(observations), outcome="observations" if observations else "empty", reason_code=None if observations else "source_dataset_empty", coverage="bounded_page" if source_id == "world_bank_gdp" else "release_only", more_pages=more_pages)
        except ParseError:
            raise
        except (ValueError, TypeError, KeyError, IndexError, OverflowError, RecursionError) as error:
            # Reject atomically. No accepted validators, writes or numeric defaults here.
            raise ParseError(source_id, "invalid_source_payload") from error
