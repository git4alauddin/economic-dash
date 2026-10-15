"""Validated M3 handoff models; the public M4 API projection remains separate."""

import calendar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
import re
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_serializer, field_validator, model_validator

from .catalog import validate_url

Unit = Literal["percent_yoy", "percent_of_gdp", "percent", "inr_crore", "usd_billion", "index_points"]
Frequency = Literal["annual", "monthly", "monthly_cumulative"]
MONTHS = {name.lower(): number for number, name in enumerate(calendar.month_name) if name}
NUMBER = r"[+-]?(?:\d+|\d{1,3}(?:,\d{3})+|\d{1,2}(?:,\d{2})*,\d{3})(?:\.\d+)?"
MISSING = {"", "-", "—", "..", "NA", "N/A"}


class ParseError(Exception):
    def __init__(self, source_id: str, code: str, field: str = "payload"):
        self.source_id, self.code, self.field = source_id, code, field
        super().__init__(f"{source_id}: {code} ({field})")


def decimal_value(value: object) -> Decimal | None:
    if value is None or (isinstance(value, str) and value.strip().upper() in MISSING):
        return None
    if type(value) not in {str, int, Decimal}:
        raise ValueError("A decimal token is required; floats and booleans are forbidden.")
    if isinstance(value, str):
        value = value.strip().replace("−", "-")
        if len(value) > 80 or not re.fullmatch(NUMBER, value, flags=re.ASCII):
            raise ValueError("Invalid number or grouping.")
        value = value.replace(",", "")
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("Invalid decimal.") from error
    if not result.is_finite() or len(result.as_tuple().digits) > 38 or not -18 <= result.as_tuple().exponent <= 18:
        raise ValueError("Non-finite or unsupported decimal precision/range.")
    return result


class ImmutableModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class ObservationPeriod(ImmutableModel):
    id: str
    label: str
    basis: Literal["calendar", "fiscal"]
    frequency: Frequency
    start: date
    end: date

    @model_validator(mode="after")
    def aligned_period(self) -> Self:
        if self.end < self.start or self.end.day != calendar.monthrange(self.end.year, self.end.month)[1]:
            raise ValueError("Invalid period bounds.")
        if self.frequency == "annual":
            if self.basis == "calendar":
                expected = (date(self.end.year, 1, 1), date(self.end.year, 12, 31), f"CY{self.end.year}")
            else:
                expected = (date(self.end.year - 1, 4, 1), date(self.end.year, 3, 31), f"FY{self.end.year - 1}-{str(self.end.year)[2:]}")
        elif self.frequency == "monthly" and self.basis == "calendar":
            expected = (self.end.replace(day=1), self.end, self.end.strftime("%Y-%m"))
        elif self.frequency == "monthly_cumulative" and self.basis == "fiscal":
            start_year = self.end.year if self.end.month >= 4 else self.end.year - 1
            expected = (date(start_year, 4, 1), self.end, f"FY{start_year}-{str(start_year + 1)[2:]}:{self.end:%Y-%m}")
        else:
            raise ValueError("Unsupported frequency/basis combination.")
        if (self.start, self.end, self.id) != expected or not self.label.strip():
            raise ValueError("Period ID, bounds and basis must align.")
        return self


def annual_period(year: int, *, fiscal: bool = False) -> ObservationPeriod:
    if fiscal:
        return ObservationPeriod(id=f"FY{year}-{str(year + 1)[2:]}", label=f"FY {year}-{str(year + 1)[2:]}", basis="fiscal", frequency="annual", start=date(year, 4, 1), end=date(year + 1, 3, 31))
    return ObservationPeriod(id=f"CY{year}", label=str(year), basis="calendar", frequency="annual", start=date(year, 1, 1), end=date(year, 12, 31))


def monthly_period(year: int, month: int, *, cumulative: bool = False) -> ObservationPeriod:
    end = date(year, month, calendar.monthrange(year, month)[1])
    if cumulative:
        start_year = year if month >= 4 else year - 1
        return ObservationPeriod(id=f"FY{start_year}-{str(start_year + 1)[2:]}:{year}-{month:02}", label=f"Apr {start_year}–{calendar.month_abbr[month]} {year} (YTD)", basis="fiscal", frequency="monthly_cumulative", start=date(start_year, 4, 1), end=end)
    return ObservationPeriod(id=f"{year}-{month:02}", label=f"{calendar.month_abbr[month]} {year}", basis="calendar", frequency="monthly", start=end.replace(day=1), end=end)


def fiscal_start(label: str) -> int:
    found = re.fullmatch(r"(\d{4})-(\d{2}|\d{4})", label, flags=re.ASCII)
    if not found:
        raise ValueError("Invalid fiscal year.")
    start = int(found[1])
    end = int(found[2]) if len(found[2]) == 4 else start // 100 * 100 + int(found[2])
    if end != start + 1:
        raise ValueError("Fiscal year must span consecutive years.")
    return start


class SourceReference(ImmutableModel):
    source_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    url: str
    is_nse: bool

    @field_validator("url")
    @classmethod
    def public_url(cls, value: str) -> str:
        return validate_url(value)


class NormalizedObservation(ImmutableModel):
    indicator_id: str = Field(min_length=1)
    series_id: str = Field(min_length=1)
    definition_id: str = Field(min_length=1)
    value: Decimal | None
    unit: Unit
    observation_period: ObservationPeriod
    as_of: str
    as_of_precision: Literal["year", "month"]
    as_of_kind: Literal["period_end"] = "period_end"
    published_at: datetime | None
    publication_precision: Literal["minute"] | None = None
    publication_timezone: str | None
    retrieved_at: datetime
    sources: tuple[SourceReference, ...] = Field(min_length=1)
    quality_status: Literal["valid", "missing"]
    reason_code: str | None
    revision_kind: Literal["published", "provisional", "first_revised", "final", "provisional_actual"]
    vintage_id: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    source_unit: str
    normalization_id: str = "identity_v1"
    dataset_updated_at: date | None = None
    transform_id: Literal["exports_minus_imports_v1"] | None = None
    inputs: tuple["NormalizedObservation", ...] = ()

    @field_validator("value", mode="before")
    @classmethod
    def exact_decimal(cls, value: object, info: ValidationInfo) -> Decimal | None:
        if info.mode == "json" and isinstance(value, str):
            # Versioned storage JSON uses decimal strings; Python acquisition
            # still requires Decimal and JSON numeric floats remain forbidden.
            if not re.fullmatch(r"-?(?:0|[1-9]\d*)(?:\.\d+)?", value, re.ASCII):
                raise ValueError("Storage values require canonical decimal strings or null.")
            value = decimal_value(value)
        if value is not None and not isinstance(value, Decimal):
            raise ValueError("Normalized financial values must already be Decimal.")
        return decimal_value(value)

    @field_serializer("value")
    def serialize_decimal(self, value: Decimal | None) -> str | None:
        return format(value, "f") if value is not None else None

    @model_validator(mode="after")
    def observation_invariants(self) -> Self:
        for instant in (self.retrieved_at, self.published_at):
            if instant is not None and (instant.utcoffset() is None or instant.utcoffset() != timedelta(0)):
                raise ValueError("Normalized timestamps must be timezone-aware UTC.")
        if self.observation_period.end > self.retrieved_at.date():
            raise ValueError("A completed observation period cannot be in the future.")
        if self.published_at and (self.published_at > self.retrieved_at or self.published_at.date() < self.observation_period.end):
            raise ValueError("Publication and observation dates are inconsistent.")
        if bool(self.published_at) != bool(self.publication_timezone):
            raise ValueError("Publication timezone must accompany a known publication time.")
        if bool(self.published_at) != bool(self.publication_precision):
            raise ValueError("Publication precision must accompany a known publication time.")
        expected_as_of = self.observation_period.end.strftime("%Y" if self.as_of_precision == "year" else "%Y-%m")
        if self.as_of != expected_as_of or (self.observation_period.frequency == "annual") != (self.as_of_precision == "year"):
            raise ValueError("As-of precision must match the source period.")
        missing_reason = "derived_input_missing" if self.transform_id else "source_value_missing"
        if (self.value is None and (self.quality_status != "missing" or self.reason_code != missing_reason)) or (self.value is not None and (self.quality_status != "valid" or self.reason_code is not None)):
            raise ValueError("Missing values require explicit quality/reason metadata.")
        if self.value is not None:
            if self.unit == "percent_yoy" and not Decimal(-100) <= self.value <= Decimal(1000):
                raise ValueError("Growth/inflation outside supported review bounds.")
            lower = Decimal("-1e12") if self.transform_id else Decimal(0)
            if self.unit in {"inr_crore", "usd_billion", "index_points", "percent_of_gdp"} and not lower <= self.value <= Decimal("1e12"):
                raise ValueError("Amount/ratio outside supported bounds.")
        if self.dataset_updated_at and self.dataset_updated_at > self.retrieved_at.date():
            raise ValueError("Future dataset revision date.")
        if self.transform_id:
            if self.series_id != "trade_balance" or self.indicator_id != "trade" or self.definition_id != "india_merchandise_balance_monthly_usd_v1" or self.unit != "usd_billion" or self.normalization_id != self.transform_id or len(self.inputs) != 2:
                raise ValueError("Unsupported derived observation.")
            exports, imports = self.inputs
            for point, series in zip(self.inputs, ("exports", "imports")):
                if point.series_id != series or point.definition_id != f"india_merchandise_{series}_monthly_usd_v1" or point.inputs or point.transform_id or point.observation_period != self.observation_period or point.unit != self.unit or point.vintage_id != self.vintage_id or point.revision_kind != self.revision_kind or point.sources != self.sources or point.published_at != self.published_at or point.retrieved_at > self.retrieved_at:
                    raise ValueError("Derived inputs must have aligned definitions, periods and release vintage.")
            with localcontext() as context:
                context.prec = 80
                expected = exports.value - imports.value if exports.value is not None and imports.value is not None else None
            if self.value != expected:
                raise ValueError("Trade balance must equal exports minus imports, including missing inputs.")
        elif self.inputs or self.series_id == "trade_balance":
            raise ValueError("Derived series require a versioned transform and input references.")
        return self


class NormalizedBatch(ImmutableModel):
    source_id: str
    observations: tuple[NormalizedObservation, ...]
    outcome: Literal["observations", "empty"] = "observations"
    reason_code: Literal["source_dataset_empty"] | None = None
    coverage: Literal["release_only", "bounded_page"]
    more_pages: bool = False

    @model_validator(mode="after")
    def unique_observations(self) -> Self:
        if (not self.observations) != (self.outcome == "empty") or (not self.observations) != (self.reason_code == "source_dataset_empty"):
            raise ValueError("Empty source batches must be explicit and cannot supply observations.")
        keys = [(item.series_id, item.observation_period.id) for item in self.observations]
        if len(set(keys)) != len(keys):
            raise ValueError("Duplicate observation periods are not silently overwritten.")
        if any(item.sources[0].source_id != self.source_id for item in self.observations):
            raise ValueError("Batch/source mismatch.")
        return self
