"""Independent publisher-token -> SQL trace used by the disposable browser check."""

from decimal import Decimal, ROUND_HALF_UP, localcontext
from hashlib import sha256
import json

from app.verify_integration import require


def world_gdp_trace(database, receipt, metadata):
    # Parse source tokens independently of SourceNormalizer. Keep exact decimals,
    # and choose the latest completed non-null World observation from this fetch.
    document = json.loads(receipt.body.decode("utf-8-sig"), parse_float=Decimal, parse_int=Decimal)
    rows = document[1]
    require(all(row["countryiso3code"] == "WLD" and row["indicator"]["id"] == "NY.GDP.MKTP.KD.ZG" for row in rows),
            "World trace publisher identity changed.")
    candidates = [row for row in rows if row["value"] is not None and int(row["date"]) < receipt.retrieved_at.year]
    require(bool(candidates), "World trace has no completed publisher observation.")
    source = max(candidates, key=lambda row: int(row["date"]))
    year, value = source["date"], source["value"]
    require(isinstance(value, Decimal) and value.is_finite(), "World trace requires an exact finite publisher value.")
    vintage = "sha256:" + sha256(receipt.body + b"\0" + metadata.body).hexdigest()
    with database.connection(read_only=True) as connection:
        stored = connection.execute("""SELECT * FROM observations WHERE series_id=? AND value_decimal IS NOT NULL
            ORDER BY period_end DESC,vintage_id DESC LIMIT 1""", ("gdp_growth_world",)).fetchone()
        require(stored is not None, "World trace SQL observation is missing.")
        expected = {"value_decimal": format(value, "f"), "unit": "percent_yoy",
            "definition_id": "wdi_wld_real_gdp_annual_v1", "period_id": "CY" + year,
            "period_label": year, "basis": "calendar", "frequency": "annual",
            "period_start": year + "-01-01", "period_end": year + "-12-31",
            "as_of": year, "as_of_precision": "year", "as_of_kind": "period_end",
            "dataset_updated_at": document[0]["lastupdated"], "vintage_id": vintage,
            "published_at": None}
        require(all(stored[key] == item for key, item in expected.items()), "World publisher token/period differs from SQL.")
        sources = [dict(row) for row in connection.execute(
            "SELECT source_id,name,url,is_nse FROM observation_sources WHERE observation_id=? ORDER BY ordinal",
            (stored["observation_id"],))]
    require([source["url"] for source in sources] == [receipt.response_url, metadata.response_url],
            "World SQL attribution differs from fetched publisher URLs.")
    require(all(not source["is_nse"] for source in sources), "World publisher was incorrectly attributed to NSE.")
    with localcontext() as context:
        context.prec = max(80, len(value.as_tuple().digits) + 4)
        rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        display = format(abs(rounded) if rounded == 0 else rounded, ",.2f") + "%"
    return {"value": format(value, "f"), "display": display, "unit": "percent_yoy",
        "definition_id": expected["definition_id"], "year": year,
        "period": {"id": "CY" + year, "label": year, "basis": "calendar", "frequency": "annual",
                   "start": year + "-01-01", "end": year + "-12-31"},
        "vintage_id": vintage, "sources": [{**source, "is_nse": bool(source["is_nse"])} for source in sources]}
