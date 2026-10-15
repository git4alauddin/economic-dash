"""Bounded history collection and pure, versioned calculations for the M4 handoff."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, localcontext
from fractions import Fraction
import json
from typing import Literal

from pydantic import Field, field_serializer, model_validator

from .adapters import create_adapters
from .catalog import CATALOG_PATH
from .errors import AcquisitionError
from .http_client import CollectorHttpClient, FetchResult
from .observations import (
    ImmutableModel, NormalizedBatch, NormalizedObservation, ObservationPeriod,
    ParseError, annual_period, monthly_period,
)

HISTORY_VERSION = "m3-history-v1"
DEFAULT_WINDOW = 5
TRADE_TRANSFORM = "exports_minus_imports_v1"


class ExactValue(ImmutableModel):
    """Canonical rational result: never round a recurring percentage in storage."""

    numerator: int
    denominator: int = Field(gt=0)

    @classmethod
    def of(cls, value: Fraction) -> "ExactValue":
        return cls(numerator=value.numerator, denominator=value.denominator)

    @model_validator(mode="after")
    def canonical(self):
        if Fraction(self.numerator, self.denominator).denominator != self.denominator:
            raise ValueError("Rational results must be reduced.")
        return self

    @field_serializer("numerator", "denominator")
    def serialize_integer(self, value: int) -> str:
        return str(value)  # Avoid losing integer precision at a later JSON boundary.

    def display_decimal(self, places: int) -> str:
        """Explicit presentation boundary only; exact numerator/denominator survive."""
        if type(places) is not int or not 0 <= places <= 18:
            raise ValueError("Display precision must be between 0 and 18 places.")
        # Integer half-even rounding also handles values arbitrarily close to a tie.
        quotient, remainder = divmod(abs(self.numerator) * 10 ** places, self.denominator)
        if remainder * 2 > self.denominator or (remainder * 2 == self.denominator and quotient % 2):
            quotient += 1
        with localcontext() as context:
            context.prec = max(80, len(str(quotient)) + places + 2)
            value = Decimal(quotient).scaleb(-places)
            if self.numerator < 0 and quotient:
                value = -value
            return format(value, f".{places}f")


class Comparison(ImmutableModel):
    value: ExactValue | None
    unit: Literal["percentage_points", "percent"] | None
    transform_id: str | None
    current: NormalizedObservation | None
    reference: NormalizedObservation | None
    reference_period_id: str | None
    reason_code: str | None

    @model_validator(mode="after")
    def explicit_state(self):
        if (self.value is None) != (self.reason_code is not None):
            raise ValueError("Unavailable comparisons require a reason.")
        if self.value is not None and (self.current is None or self.reference is None or self.reference_period_id != self.reference.observation_period.id or self.unit is None or self.transform_id is None):
            raise ValueError("Calculated comparisons require both input references and units.")
        return self


class HistorySlot(ImmutableModel):
    """A requested chart period, explicitly distinct from a sourced observation."""

    period: ObservationPeriod
    observation: NormalizedObservation | None
    reason_code: str | None

    @model_validator(mode="after")
    def aligned(self):
        if self.observation is not None and self.observation.observation_period != self.period:
            raise ValueError("History slot/observation period mismatch.")
        if (self.observation is None or self.observation.value is None) != (self.reason_code is not None):
            raise ValueError("History gaps require explicit reasons.")
        return self


class HistoricalSeries(ImmutableModel):
    indicator_id: str
    series_id: str
    observations: tuple[NormalizedObservation, ...]
    superseded: tuple[NormalizedObservation, ...]
    latest: NormalizedObservation | None
    window: tuple[HistorySlot, ...]
    status: Literal["available", "partial", "unavailable"]
    reason_code: str | None
    comparison: Comparison


class SourceFailure(ImmutableModel):
    source_id: str
    resource_id: str
    reason_code: str


class UnavailableRequirement(ImmutableModel):
    requirement_id: str
    reason_code: str


class HistorySnapshot(ImmutableModel):
    version: str = HISTORY_VERSION
    series: tuple[HistoricalSeries, ...]
    unavailable_requirements: tuple[UnavailableRequirement, ...]
    failures: tuple[SourceFailure, ...]


@dataclass(frozen=True)
class HistoryCollection:
    snapshot: HistorySnapshot
    batches: tuple[NormalizedBatch, ...]
    receipts: tuple[FetchResult, ...]


def _catalog():
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _periods(latest: ObservationPeriod, window: int) -> tuple[ObservationPeriod, ...]:
    if latest.frequency == "annual":
        year = latest.start.year
        return tuple(annual_period(y, fiscal=latest.basis == "fiscal") for y in range(year - window + 1, year + 1))
    periods = []
    end = latest.end
    for _ in range(window):
        periods.append(monthly_period(end.year, end.month, cumulative=latest.frequency == "monthly_cumulative"))
        end = end.replace(day=1) - timedelta(days=1)
        if latest.frequency == "monthly_cumulative" and end < latest.start:
            break  # YTD snapshots from another FY are a different accumulation window.
    return tuple(reversed(periods))


def _reference_period(current: NormalizedObservation) -> ObservationPeriod:
    period = current.observation_period
    if period.frequency == "annual":
        return annual_period(period.start.year - 1, fiscal=period.basis == "fiscal")
    if current.series_id == "cpi_yoy":
        prior = period.start - timedelta(days=1)
        return monthly_period(prior.year, prior.month)
    return monthly_period(period.end.year - 1, period.end.month, cumulative=period.frequency == "monthly_cumulative")


def compare(current: NormalizedObservation | None, observations: tuple[NormalizedObservation, ...]) -> Comparison:
    def missing(reason, reference=None, period=None):
        return Comparison(value=None, unit=None, transform_id=None, current=current, reference=reference, reference_period_id=period, reason_code=reason)
    if current is None or current.value is None:
        return missing("current_observation_missing")
    if current.series_id not in {"gdp_growth_india", "gdp_growth_world", "cpi_yoy", "exports", "imports", "expenditure_total", "expenditure_capital", "expenditure_revenue"}:
        return missing("comparison_not_defined")
    definition = _catalog()["requirements"][current.series_id]
    if (current.definition_id, current.unit, current.observation_period.basis, current.observation_period.frequency) != (definition["definition_id"], definition["unit"], definition["basis"], definition["frequency"]):
        return missing("comparison_definition_unverified")
    expected = _reference_period(current)
    references = [p for p in observations if p.series_id == current.series_id and p.observation_period.id == expected.id]
    if len(references) > 1:
        return missing("reference_revision_unresolved", period=expected.id)
    reference = references[0] if references else None
    if reference is None or reference.value is None:
        return missing("reference_observation_missing", reference, expected.id)
    same_definition = (current.series_id, current.definition_id, current.unit, current.observation_period.basis, current.observation_period.frequency) == (reference.series_id, reference.definition_id, reference.unit, reference.observation_period.basis, reference.observation_period.frequency)
    same_publisher = tuple(s.source_id for s in current.sources) == tuple(s.source_id for s in reference.sources)
    expenditure = current.series_id.startswith("expenditure_")
    # Release-paired GDP estimates/CPI revisions are explicit comparable inputs.
    # Fiscal actuals use separate releases, identical cutoffs and the same category.
    allowed_revisions = {
        "gdp_growth_india": {("provisional", "first_revised")},
        "gdp_growth_world": {("published", "published")},
        "cpi_yoy": {("provisional", "final"), ("final", "final")},
        "exports": {("published", "published")}, "imports": {("published", "published")},
    }
    vintage_ok = (current.revision_kind == reference.revision_kind == "provisional_actual") if expenditure else (current.vintage_id == reference.vintage_id and (current.revision_kind, reference.revision_kind) in allowed_revisions[current.series_id])
    if not same_definition or not same_publisher or not vintage_ok:
        return missing("comparison_inputs_not_comparable", reference, expected.id)
    delta = Fraction(current.value) - Fraction(reference.value)
    if current.unit in {"percent_yoy", "percent_of_gdp"}:
        value, unit, transform = delta, "percentage_points", "prior_period_percentage_point_delta_v1"
    else:
        if reference.value == 0:
            return missing("zero_reference_denominator", reference, expected.id)
        value, unit = delta * 100 / Fraction(reference.value), "percent"
        transform = "same_fiscal_cutoff_percent_change_v1" if expenditure else "same_month_prior_year_percent_change_v1"
    return Comparison(value=ExactValue.of(value), unit=unit, transform_id=transform, current=current, reference=reference, reference_period_id=expected.id, reason_code=None)


def trade_balance(exports: NormalizedObservation | None, imports: NormalizedObservation | None) -> NormalizedObservation | None:
    if exports is None or imports is None:
        return None
    with localcontext() as context:
        context.prec = 80
        value = exports.value - imports.value if exports.value is not None and imports.value is not None else None
    fields = exports.model_dump()
    fields.update(series_id="trade_balance", definition_id="india_merchandise_balance_monthly_usd_v1", value=value,
                  quality_status="missing" if value is None else "valid", reason_code="derived_input_missing" if value is None else None,
                  retrieved_at=max(exports.retrieved_at, imports.retrieved_at), source_unit="usd_billion",
                  normalization_id=TRADE_TRANSFORM, transform_id=TRADE_TRANSFORM, inputs=(exports, imports))
    # Reconstruct all nested models; model_copy(update=...) would bypass validation.
    fields["observation_period"], fields["sources"] = exports.observation_period, exports.sources
    return NormalizedObservation(**fields)


def _resolve(candidates: list[NormalizedObservation]):
    """Latest publisher revision wins; retrieval time cannot establish a revision."""
    def version(point):
        return point.published_at.isoformat() if point.published_at else (point.dataset_updated_at.isoformat() if point.dataset_updated_at else "")
    ordered = sorted(candidates, key=lambda p: (version(p), p.retrieved_at, p.vintage_id))
    best = ordered[-1]
    peers = [p for p in ordered if version(p) == version(best)]
    if len({(p.value, p.revision_kind) for p in peers}) != 1:
        return None, tuple(ordered), "conflicting_source_revision"
    rank = {"provisional": 0, "first_revised": 1, "final": 2}
    if best.revision_kind in rank and any(rank.get(p.revision_kind, -1) > rank[best.revision_kind] for p in ordered):
        return None, tuple(ordered), "source_revision_regressed"
    return best, tuple(p for p in ordered if p != best), None


def build_history(batches: tuple[NormalizedBatch, ...], *, window: int = DEFAULT_WINDOW, failures: tuple[SourceFailure, ...] = ()) -> HistorySnapshot:
    if type(window) is not int or not 1 <= window <= 24:
        raise ValueError("History window must be between 1 and 24 periods.")
    catalog = _catalog()
    inventory = json.loads((CATALOG_PATH.parent / "indicator-requirements.json").read_text(encoding="utf-8"))
    bindings = {s["id"]: panel["indicator_id"] for panel in inventory["panels"] for s in panel["series"]}
    grouped = defaultdict(list)
    for batch in batches:
        for point in batch.observations:
            definition = catalog["requirements"].get(point.series_id, {})
            if definition.get("status") != "selected" or (point.definition_id, point.unit, point.observation_period.frequency, point.observation_period.basis, batch.source_id, point.indicator_id) != (definition.get("definition_id"), definition.get("unit"), definition.get("frequency"), definition.get("basis"), definition.get("source_id"), bindings.get(point.series_id)) or point.transform_id:
                raise ValueError("History input does not match a selected, direct catalog definition.")
            grouped[point.series_id, point.observation_period.id].append(point)
    selected, old, gaps, periods = {}, {}, {}, {}
    for key, candidates in grouped.items():
        point, superseded, reason = _resolve(candidates)
        periods[key] = candidates[0].observation_period
        if point is not None:
            selected[key] = point
        old[key] = superseded
        if reason:
            gaps[key] = reason
    trade_periods = {pid for sid, pid in grouped if sid in {"exports", "imports"}}
    for pid in trade_periods:
        key = ("trade_balance", pid)
        exports, imports = selected.get(("exports", pid)), selected.get(("imports", pid))
        periods[key] = periods.get(("exports", pid), periods.get(("imports", pid)))
        try:
            point = trade_balance(exports, imports)
            if point is None:
                gaps[key] = "derived_input_missing"
            else:
                selected[key] = point
        except ValueError:
            gaps[key] = "derived_inputs_not_comparable"
    series = []
    for sid, indicator in bindings.items():
        definition = catalog["requirements"][sid]
        blocked = definition["status"] == "blocked"
        points = tuple(sorted((p for (s, _), p in selected.items() if s == sid), key=lambda p: p.observation_period.end))
        all_periods = [period for (s, _), period in periods.items() if s == sid]
        newest = max(all_periods, key=lambda p: p.end) if all_periods else None
        latest = selected.get((sid, newest.id)) if newest else None
        slots = []
        for period in _periods(newest, window) if newest else ():
            key = sid, period.id
            point = selected.get(key)
            reason = point.reason_code if point else gaps.get(key, "historical_observation_unavailable")
            if point is None:
                unavailable = catalog["sources"][definition["source_id"]].get("history_unavailable", [])
                reason = next((item["reason_code"] for item in unavailable if item["period"] == period.end.strftime("%Y-%m")), reason)
                if sid == "gdp_growth_india" and reason == "historical_observation_unavailable":
                    reason = "comparable_base_history_unverified"
            slots.append(HistorySlot(period=period, observation=point, reason_code=reason))
        reason = definition["reason_code"] if blocked else ("source_history_unavailable" if not slots else next((s.reason_code for s in reversed(slots) if s.reason_code), None))
        source_failed = any(f.source_id == definition["source_id"] for f in failures)
        if not blocked and source_failed and reason is None:
            reason = "history_acquisition_partial"
        status = "unavailable" if not any(s.observation is not None and s.observation.value is not None for s in slots) else ("partial" if reason else "available")
        comparison = compare(latest, points)
        if blocked:
            comparison = Comparison(value=None, unit=None, transform_id=None, current=None, reference=None, reference_period_id=None, reason_code=definition["reason_code"])
        series.append(HistoricalSeries(indicator_id=indicator, series_id=sid, observations=points,
                      superseded=tuple(p for (s, _), items in sorted(old.items()) if s == sid for p in items),
                      latest=latest, window=tuple(slots), status=status, reason_code=reason, comparison=comparison))
    unavailable = tuple(UnavailableRequirement(requirement_id=sid, reason_code=d["reason_code"]) for sid, d in catalog["requirements"].items() if d["status"] == "blocked")
    return HistorySnapshot(series=tuple(series), unavailable_requirements=unavailable, failures=failures)


async def collect_history(client: CollectorHttpClient, *, window: int = DEFAULT_WINDOW) -> HistoryCollection:
    """Validate each reviewed release independently; no writes or cache acknowledgement.

    M4 must accept batches transactionally before acknowledging receipts. M3.7
    will combine this with durable last-good data and conditional response handling.
    """
    if type(window) is not int or not 1 <= window <= 24:
        raise ValueError("History window must be between 1 and 24 periods.")
    batches, receipts, failures = [], [], []
    for source_id, adapter in create_adapters(client).items():
        for resource_id in client.registry.observation_resources(source_id):
            try:
                payloads = await adapter.acquire(resource_id=resource_id, conditional=False)
                batch = adapter.normalize(payloads)
                batches.append(batch)
                receipts.extend(p for p in (payloads.payload, payloads.metadata) if p is not None)
            except (AcquisitionError, ParseError) as error:
                code = error.code.value if isinstance(error, AcquisitionError) else error.code
                failures.append(SourceFailure(source_id=source_id, resource_id=resource_id, reason_code=code))
    frozen_batches = tuple(batches)
    return HistoryCollection(build_history(frozen_batches, window=window, failures=tuple(failures)), frozen_batches, tuple(receipts))
