"""Version-1 public wire models. Economic decimals stay strings; no binary floats."""

from datetime import date, datetime
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.collectors.observations import NormalizedObservation, SourceReference

DecimalString = Annotated[str, Field(pattern=r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$", max_length=1000)]
Unit = Literal["percent_yoy", "percent_of_gdp", "percent", "percentage_points", "inr_crore", "usd_billion", "index_points"]
Status = Literal["fresh", "stale", "unavailable", "empty", "error"]


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)


class ResponsePeriod(WireModel):
    id: str
    label: str
    basis: Literal["fiscal", "calendar"]
    frequency: Literal["annual", "monthly", "monthly_cumulative"]
    start: date
    end: date


class ResponseObservation(WireModel):
    value: DecimalString | None
    unit: Unit
    definition_id: str
    observation_period: ResponsePeriod | None
    as_of: str | None
    as_of_precision: Literal["year", "month"] | None
    as_of_kind: Literal["period_end"] | None
    sources: tuple[SourceReference, ...]
    status: Status
    reason_code: str | None
    retention_allowed: bool
    published_at: datetime | None = None
    retrieved_at: datetime | None = None
    dataset_updated_at: date | None = None
    revision_kind: str | None = None
    vintage_id: str | None = None
    parser_version: str | None = None
    normalization_id: str | None = None
    transform_id: str | None = None
    inputs: tuple[NormalizedObservation, ...] = ()
    last_attempt_at: datetime | None = None
    last_checked_at: datetime | None = None
    last_success_at: datetime | None = None
    last_changed_at: datetime | None = None
    last_failure_at: datetime | None = None
    publication_deadline: datetime | None = None
    check_deadline: datetime | None = None
    freshness_policy_version: str | None = None
    failure_state_persisted: bool | None = None

    @model_validator(mode="after")
    def explicit_value_state(self):
        if self.value is not None and (self.status not in {"fresh", "stale"} or not self.sources or self.as_of is None or self.observation_period is None):
            raise ValueError("A displayed observation requires source, period, date and displayable status.")
        if self.value is None and (self.retention_allowed or self.reason_code is None):
            raise ValueError("Missing values require an explicit reason and cannot be retained.")
        return self


class ResponseComparison(WireModel):
    value: DecimalString
    unit: Literal["percentage_points", "percent"]
    precision: int = Field(ge=0, le=6)
    reference_label: str
    kind: Literal["previous_period", "previous_year"]
    reference_series_id: str
    reference_period_id: str
    verified: Literal[True] = True
    transform_id: str
    exact_numerator: str
    exact_denominator: str


class ResponseHistory(WireModel):
    status: Status
    points: tuple[ResponseObservation, ...]
    truncated: bool


class ResponseSeries(WireModel):
    name: str
    precision: int = Field(default=2, ge=0, le=6)
    latest: ResponseObservation
    comparison: ResponseComparison | None
    comparison_reason_code: str | None
    history: ResponseHistory
    policy: None = None  # No verified policy interval exists yet; never invent dates.


class ResponseChart(WireModel):
    periods: tuple[ResponsePeriod, ...]
    domain: tuple[DecimalString, DecimalString]
    ticks: tuple[DecimalString, ...]
    unit: Unit
    precision: int = 2
    annotation_precision: int = 2


class ResponseSummary(WireModel):
    slot: int
    requirement_id: str
    definition_id: str | None
    unit: Unit | None
    observation: ResponseObservation | None
    comparison: ResponseComparison | None
    comparison_reason_code: str | None
    reason_code: str | None


class ResponsePanel(WireModel):
    indicator_id: str
    series: dict[str, ResponseSeries]
    summaries: tuple[ResponseSummary, ...]
    period_label: str | None
    chart: ResponseChart | None


class ResponseQuote(ResponseObservation):
    unit: Literal["index_points"] = "index_points"
    instrument_id: str
    name: str
    change: DecimalString | None = None
    change_percent: DecimalString | None = None
    comparison_label: str | None = None
    precision: int = 2
    market_status: Literal["unknown"] = "unknown"


class ResponseTicker(WireModel):
    status: Literal["unavailable"] = "unavailable"
    cadence: Literal["unknown"] = "unknown"
    cadence_label: None = None
    items: tuple[ResponseQuote, ...]


class DashboardData(WireModel):
    panels: dict[str, ResponsePanel]
    ticker: ResponseTicker


class ResponseMeta(WireModel):
    api_version: Literal["v1"] = "v1"
    generated_at: datetime
    version: str
    partial: bool
    data_version: str
    poll_interval_seconds: Literal[60] = 60


class HealthResponse(WireModel):
    status: Literal["ok", "unavailable"]


T = TypeVar("T")


class Envelope(WireModel, Generic[T]):
    data: T
    meta: ResponseMeta


class HistoryData(WireModel):
    indicator_id: str
    series_id: str
    selected_period: ResponsePeriod | None
    series: ResponseSeries
    superseded: tuple[NormalizedObservation, ...]


class CatalogSeries(WireModel):
    series_id: str
    name: str
    definition_id: str | None
    definition: str
    unit: Unit | None
    frequency: str
    basis: Literal["fiscal", "calendar"] | None
    status: Literal["selected", "derived", "blocked"]
    reason_code: str | None
    available_periods: tuple[ResponsePeriod, ...]
    source_id: str
    limitations: tuple[str, ...]


class CatalogIndicator(WireModel):
    indicator_id: str
    series: tuple[CatalogSeries, ...]
    summary_requirements: tuple[str, ...]


class ErrorDetail(WireModel):
    location: tuple[str | int, ...]
    message: str


class ErrorBody(WireModel):
    code: str
    message: str
    details: tuple[ErrorDetail, ...] = ()


class ErrorEnvelope(WireModel):
    error: ErrorBody
